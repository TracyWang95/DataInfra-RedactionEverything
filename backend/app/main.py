"""
匿名化数据基础设施 - FastAPI 应用入口
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.types import Message

from app.api import auth as auth_api
from app.api import (
    entity_types,
    files,
    jobs,
    model_config,
    ner_backend,
    presets,
    redaction,
    structured,
    vision_pipeline,
)
from app.api import safety as safety_api
from app.core.auth import require_auth, require_super_admin
from app.core.config import settings
from app.core.errors import AppError, app_error_handler, http_exception_handler, validation_exception_handler
from app.core.gpu_memory import query_gpu_memory as _query_gpu_memory
from app.core.gpu_memory import query_gpu_memory_all as _query_gpu_memory_all
from app.core.health_checks import check_has_ner_health, check_ocr_health_sync, check_service_health_sync
from app.core.logging_config import setup_logging
from app.models.schemas import HealthResponse

# 生产环境用 JSON 格式；DEBUG 模式用文本格式（人类可读）
setup_logging(json_mode=settings.LOG_JSON and not settings.DEBUG, level=logging.DEBUG if settings.DEBUG else logging.INFO)
logger = logging.getLogger(__name__)


def _storage_files() -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for directory in (settings.UPLOAD_DIR, settings.OUTPUT_DIR):
        if not os.path.isdir(directory):
            continue
        for fname in os.listdir(directory):
            fpath = os.path.join(directory, fname)
            if os.path.isfile(fpath):
                files.append((directory, fpath))
    return files


def _known_file_store_paths(file_store) -> set[str]:
    known_paths: set[str] = set()
    snapshot = dict(file_store.items())
    for info in snapshot.values():
        if not isinstance(info, dict):
            continue
        for key in ("file_path", "output_path"):
            path = info.get(key)
            if path:
                known_paths.add(os.path.realpath(path))
    return known_paths


def _job_referenced_upload_paths() -> set[str]:
    """Protect upload files that are still referenced by batch jobs."""
    try:
        from app.services.job_store import get_job_store

        referenced_file_ids = get_job_store().list_referenced_file_ids()
    except Exception:
        logger.exception("Orphan cleanup: failed to read job item file references")
        return set()

    if not referenced_file_ids or not os.path.isdir(settings.UPLOAD_DIR):
        return set()

    known_paths: set[str] = set()
    for fname in os.listdir(settings.UPLOAD_DIR):
        stem, _ext = os.path.splitext(fname)
        if stem in referenced_file_ids:
            known_paths.add(os.path.realpath(os.path.join(settings.UPLOAD_DIR, fname)))
    return known_paths

def cleanup_orphan_files() -> int:
    """Remove orphan files from upload/output directories that are not tracked in file_store.

    Safety guard: if no persisted state can explain any file while the storage
    directories are populated, skip cleanup entirely to avoid accidental mass
    deletion after a failed migration.
    """
    import time

    from app.services.file_management_service import get_file_store
    file_store = get_file_store()

    disk_files = _storage_files()
    disk_count = len(disk_files)
    known_paths = _known_file_store_paths(file_store)
    known_paths.update(_job_referenced_upload_paths())
    # Safety: if populated storage has no known references, something is wrong.
    if disk_count > 5 and not known_paths:
        logger.warning(
            "Orphan cleanup SKIPPED: disk has %d files but no file_store/job references were found. "
            "Possible migration issue - refusing to delete.",
            disk_count,
        )
        return 0

    removed = 0
    for _directory, fpath in disk_files:
        real = os.path.realpath(fpath)
        if real in known_paths:
            continue
        age = time.time() - os.path.getmtime(fpath)
        if age <= settings.ORPHAN_CLEANUP_AGE_SEC:
            continue
        try:
            os.remove(fpath)
            removed += 1
            logger.info("Orphan cleanup: removed %s (age %.0fs)", os.path.basename(fpath), age)
        except OSError:
            logger.exception("Orphan cleanup: failed to remove %s", fpath)
    return removed


async def _periodic_cleanup():
    """Background task: run orphan file cleanup every hour."""
    while True:
        await asyncio.sleep(3600)
        try:
            removed = cleanup_orphan_files()
            if removed:
                logger.info("Periodic cleanup removed %d orphan files", removed)
        except Exception:
            logger.exception("periodic orphan cleanup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # === Startup ===

    # 0. Database integrity check + restore from backup if corrupted
    from app.core.db_backup import backup_sqlite, ensure_db_healthy
    ensure_db_healthy(settings.JOB_DB_PATH)

    # Also check file_store and token_blacklist databases
    from app.services.file_management_service import get_file_store
    _fs = get_file_store()
    if hasattr(_fs, 'db_path'):
        ensure_db_healthy(_fs.db_path)
    from app.core.token_blacklist import get_blacklist
    _bl = get_blacklist()
    if hasattr(_bl, 'db_path'):
        ensure_db_healthy(_bl.db_path)

    # 0b. Run file-store migrations (JSON->SQLite, path normalization)
    from app.services.file_management_service import run_startup_migrations
    run_startup_migrations()

    # 0c. Seed the entity-type store on disk (moved out of import time)
    from app.services.entity_type_service import persist_entity_types_at_startup
    persist_entity_types_at_startup()

    # 1. Clean up orphan files (once at startup)
    removed = cleanup_orphan_files()
    if removed:
        logger.info("Cleaned up %d orphan files", removed)

    # 2. Check external services
    from app.services.ocr_service import ocr_service
    if ocr_service.is_available():
        logger.info("OCR service online (%s)", ocr_service.get_model_name())
    else:
        logger.info("OCR service offline (expected at %s)", ocr_service.base_url)

    # 2b. Repair dirty data
    from app.services.job_store import get_job_store
    _store = get_job_store()

    _repaired = _store.repair_completed_without_output()
    if _repaired:
        logger.info("Repaired %d completed items without output (reset to awaiting_review)", _repaired)

    _requeued = _store.repair_failed_missing_files()
    if _requeued:
        logger.info("Requeued %d failed items after repairing missing-file path records", _requeued)

    # 3. 启动进程内任务队列
    from app.services.task_queue import TaskItem, get_task_queue
    _task_queue = get_task_queue()
    _task_queue.start()

    # 恢复未完成的任务：根据 item 状态区分 recognition / redaction
    from app.services.job_store import JobItemStatus
    _all_jobs = _store.list_schedulable_jobs()
    _redispatched = 0
    _recognition_statuses = {
        JobItemStatus.PENDING.value,
        JobItemStatus.PROCESSING.value,
        JobItemStatus.QUEUED.value,
        JobItemStatus.PARSING.value,
        JobItemStatus.NER.value,
        JobItemStatus.VISION.value,
    }
    _redaction_statuses = {
        JobItemStatus.REVIEW_APPROVED.value,
        JobItemStatus.REDACTING.value,
    }
    for _j in _all_jobs:
        for _it in _store.list_items(_j["id"]):
            if _it["status"] in _recognition_statuses:
                _task_type = "structured" if _j.get("job_type") == "structured_batch" else "recognition"
                _task_queue.enqueue(TaskItem(
                    job_id=_j["id"], item_id=_it["id"], file_id=_it["file_id"],
                    task_type=_task_type,
                ))
                _redispatched += 1
            elif _it["status"] in _redaction_statuses:
                _task_queue.enqueue(TaskItem(
                    job_id=_j["id"], item_id=_it["id"], file_id=_it["file_id"],
                    task_type="redaction",
                ))
                _redispatched += 1
    if _redispatched:
        logger.info("Startup: re-enqueued %d items (recognition + redaction)", _redispatched)

    # 4. Start periodic orphan cleanup
    _cleanup_task = asyncio.create_task(_periodic_cleanup())

    # 5. Start periodic database backup (every hour) - all SQLite databases
    async def _periodic_backup():
        while True:
            await asyncio.sleep(3600)
            try:
                backup_sqlite(settings.JOB_DB_PATH)
            except Exception:
                logger.exception("periodic database backup failed: jobs")
            try:
                from app.services.file_management_service import get_file_store
                fs = get_file_store()
                if hasattr(fs, 'db_path'):
                    backup_sqlite(fs.db_path)
            except Exception:
                logger.exception("periodic database backup failed: file_store")
            try:
                from app.core.token_blacklist import get_blacklist
                bl = get_blacklist()
                if hasattr(bl, 'db_path'):
                    backup_sqlite(bl.db_path)
            except Exception:
                logger.exception("periodic database backup failed: token_blacklist")

    _backup_task = asyncio.create_task(_periodic_backup())

    yield

    # === Shutdown (graceful: wait up to 30s for in-progress work) ===
    logger.info("Shutting down: stopping task queue and background tasks...")
    _worker_tasks = _task_queue.stop()
    _cleanup_task.cancel()
    _backup_task.cancel()
    tasks_to_wait = [_cleanup_task, _backup_task] + _worker_tasks
    done, pending = await asyncio.wait(tasks_to_wait, timeout=30.0)
    for t in pending:
        t.cancel()
    for t in done | pending:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    logger.info("Shutdown complete.")


# 创建 FastAPI 应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="匿名化数据基础设施，支持 Word/PDF/图片等多格式文档的敏感信息自动识别与匿名化处理，基于 GB/T 37964-2019 国家标准",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)


# ---------------------------------------------------------------------------
# Request body size limit middleware (runs before CORS)
# ---------------------------------------------------------------------------
class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        max_body_size: int = 60 * 1024 * 1024,  # 60MB for uploads
        max_json_body_size: int = 1 * 1024 * 1024,  # 1MB for JSON requests
    ):
        super().__init__(app)
        self.max_body_size = max_body_size
        self.max_json_body_size = max_json_body_size

    @staticmethod
    def _body_too_large_response() -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={"error_code": "BODY_TOO_LARGE", "message": "Request body is too large.", "detail": {}},
        )

    @staticmethod
    def _install_cached_body(request: Request, body: bytes) -> None:
        async def receive() -> Message:
            return {"type": "http.request", "body": body, "more_body": False}

        request._body = body
        request._receive = receive

    async def _buffer_limited_json_body(self, request: Request) -> bytes | None:
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > self.max_json_body_size:
                return None
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        content_type = (request.headers.get("content-type") or "").lower()
        limit = self.max_body_size
        is_json_request = "application/json" in content_type or content_type.endswith("+json")
        if is_json_request:
            limit = self.max_json_body_size

        if content_length:
            try:
                if int(content_length) > limit:
                    return self._body_too_large_response()
            except ValueError:
                logger.warning("Ignoring invalid content-length header: %s", content_length)

        if is_json_request:
            body = await self._buffer_limited_json_body(request)
            if body is None:
                return self._body_too_large_response()
            self._install_cached_body(request, body)

        return await call_next(request)


# NOTE: Starlette processes middleware in reverse registration order (last added
# runs first). Register MaxBodySizeMiddleware AFTER CORSMiddleware so that the
# body-size check executes BEFORE CORS headers are evaluated.

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Idempotency-Key", "X-CSRF-Token"],
    expose_headers=["X-Request-ID"],
)

app.add_middleware(MaxBodySizeMiddleware)

# CSRF protection (double-submit cookie)
from app.core.csrf import CSRFMiddleware  # noqa: E402

app.add_middleware(CSRFMiddleware)

# Security headers on all responses
from app.core.security_headers import SecurityHeadersMiddleware  # noqa: E402

app.add_middleware(SecurityHeadersMiddleware)

# Request-ID: outermost middleware (registered last = runs first in Starlette)
from app.core.request_id import RequestIdMiddleware  # noqa: E402

app.add_middleware(RequestIdMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)

# 确保上传和输出目录存在
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

# 注意：不再挂载 /uploads 和 /outputs 为 StaticFiles，
# 因为 StaticFiles 会绕过 require_auth 认证中间件。
# 所有文件访问统一通过 /api/v1/files/{file_id}/download 端点（已有鉴权保护）。

# 注册路由
app.include_router(auth_api.router, prefix=settings.API_PREFIX)
app.include_router(files.router, prefix=settings.API_PREFIX, tags=["文件管理"], dependencies=[Depends(require_auth)])
app.include_router(redaction.router, prefix=settings.API_PREFIX, tags=["redaction"], dependencies=[Depends(require_auth)])
app.include_router(entity_types.router, prefix=settings.API_PREFIX, tags=["文本识别类型管理"], dependencies=[Depends(require_auth)])
app.include_router(vision_pipeline.router, prefix=settings.API_PREFIX, tags=["图像识别Pipeline管理"], dependencies=[Depends(require_auth)])
app.include_router(model_config.router, prefix=settings.API_PREFIX, tags=["推理模型配置"], dependencies=[Depends(require_super_admin)])
app.include_router(ner_backend.router, prefix=settings.API_PREFIX, tags=["文本NER后端"], dependencies=[Depends(require_auth)])
app.include_router(presets.router, prefix=settings.API_PREFIX, tags=["识别配置预设"], dependencies=[Depends(require_auth)])
app.include_router(jobs.router, prefix=settings.API_PREFIX, tags=["批量任务"], dependencies=[Depends(require_auth)])
app.include_router(structured.router, prefix=settings.API_PREFIX, tags=["structured"], dependencies=[Depends(require_auth)])
app.include_router(safety_api.router, prefix=settings.API_PREFIX, tags=["数据安全"], dependencies=[Depends(require_auth)])

logger.info("presets API: GET/POST %s/presets (若前端仍 404，请重启本进程以加载最新路由", settings.API_PREFIX)

# ---- Serve the built frontend from this process (single origin: browser -> uvicorn for UI + API) ----
_FRONTEND_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
_FRONTEND_INDEX = (
    os.path.join(_FRONTEND_DIST, "index.html")
    if os.path.isfile(os.path.join(_FRONTEND_DIST, "index.html"))
    else None
)
if _FRONTEND_INDEX is not None and os.path.isdir(os.path.join(_FRONTEND_DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(_FRONTEND_DIST, "assets")), name="assets")
    logger.info("Serving built frontend from %s", _FRONTEND_DIST)
else:
    logger.warning("Frontend dist not found at %s; API-only mode", _FRONTEND_DIST)

# Prometheus metrics endpoint
from datetime import UTC  # noqa: E402, I001
from app.core.metrics import metrics_endpoint  # noqa: E402

@app.get("/metrics", tags=["监控"], dependencies=[Depends(require_auth)])
async def metrics_view(request: Request):
    return await metrics_endpoint(request)


@app.get("/", tags=["root"], include_in_schema=False)
async def root():
    """Serve the built SPA when present, else API info."""
    if _FRONTEND_INDEX is not None:
        return FileResponse(_FRONTEND_INDEX)
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs" if settings.DEBUG else None,
    }


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Basic health check."""
    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
    )


@app.get("/health/services", tags=["health"])
async def services_health():
    """Return model service health."""



    import asyncio
    import time
    from datetime import datetime

    from app.core.health_checks import get_visual_features_runtime_detail
    from app.services import model_config_service

    services = {}

    # 在线程池中并行检查所有服务（避免阻塞事件循环）
    loop = asyncio.get_event_loop()
    t0 = time.perf_counter()
    ocr_url = f"{model_config_service.get_paddle_ocr_base_url()}/health"
    ocr_timeout = float(settings.OCR_HEALTH_PROBE_TIMEOUT)
    visual_base = model_config_service.get_visual_features_base_url()
    visual_models_url = (
        f"{visual_base}/models"
        if visual_base.rstrip("/").endswith("/v1")
        else f"{visual_base}/v1/models"
    )
    ocr_result, has_result, visual_detect_result, visual_chat_result = await asyncio.gather(
        loop.run_in_executor(
            None,
            lambda: check_ocr_health_sync(ocr_url, "PaddleOCR-VL-1.6-0.9B", ocr_timeout),
        ),
        loop.run_in_executor(None, check_has_ner_health),
        loop.run_in_executor(
            None,
            lambda: check_service_health_sync(
                f"{visual_base}/health",
                "LocateAnything Visual Features",
                service_kind="visual_features",
            ),
        ),
        loop.run_in_executor(
            None,
            lambda: check_service_health_sync(
                visual_models_url,
                settings.VISUAL_FEATURES_MODEL_NAME,
                timeout=3.0,
                service_kind="visual_features",
            ),
        ),
    )
    probe_ms = round((time.perf_counter() - t0) * 1000, 1)

    gpu_mem = await loop.run_in_executor(None, _query_gpu_memory)
    gpu_mem_all = await loop.run_in_executor(None, _query_gpu_memory_all)

    services["paddle_ocr"] = ocr_result.as_service_payload()
    services["has_ner"] = has_result.as_service_payload()
    visual_detect_payload = visual_detect_result.as_service_payload()
    visual_chat_payload = visual_chat_result.as_service_payload()
    if visual_chat_payload["status"] == "online":
        visual_chat_payload.setdefault("detail", {}).update(get_visual_features_runtime_detail())
    def combine_visual_status(*statuses: str) -> str:
        if any(status == "offline" for status in statuses):
            return "offline"
        if any(status == "degraded" for status in statuses):
            return "degraded"
        if any(status == "checking" for status in statuses):
            return "checking"
        return "online"

    visual_detail = {
        "detect_endpoint": visual_detect_payload.get("status"),
        "chat_endpoint": visual_chat_payload.get("status"),
        "detect_detail": visual_detect_payload.get("detail", {}),
        "chat_detail": visual_chat_payload.get("detail", {}),
    }
    # Surface runtime fields at the top level so the service card renders a GPU
    # badge for visual features, consistent with OCR/HaS (the frontend reads
    # top-level detail.runtime_mode only).
    visual_chat_detail = visual_chat_payload.get("detail", {}) or {}
    visual_detect_detail = visual_detect_payload.get("detail", {}) or {}
    for key in (
        "runtime",
        "runtime_mode",
        "gpu_available",
        "device",
        "gpu_only_mode",
        "cpu_fallback_risk",
    ):
        if key in visual_chat_detail:
            visual_detail[key] = visual_chat_detail[key]
        elif key in visual_detect_detail:
            visual_detail[key] = visual_detect_detail[key]
    services["visual_features"] = {
        "name": "LocateAnything Visual Features",
        "status": combine_visual_status(
            str(visual_detect_payload.get("status") or "offline"),
            str(visual_chat_payload.get("status") or "offline"),
        ),
        "detail": visual_detail,
    }
    all_online = all(
        services[key]["status"] == "online"
        for key in ("paddle_ocr", "has_ner", "visual_features")
    )

    return {
        "all_online": all_online,
        "services": services,
        "probe_ms": probe_ms,
        "checked_at": datetime.now(UTC).isoformat(),
        "gpu_memory": gpu_mem,
        "gpu_memory_all": gpu_mem_all,
        # Endpoint is intentionally unauthenticated (dev.mjs waitJson probes it),
        # so process names/PIDs are not exposed. Field kept for the frontend hook.
        "gpu_processes": [],
    }



@app.get("/{full_path:path}", include_in_schema=False)
async def _spa_fallback(full_path: str):
    """SPA deep-link fallback: real static file if present, else index.html.
    Reserved prefixes 404 so API/docs/health are never masked (they also match
    their own routes first, registered before this catch-all)."""
    if _FRONTEND_INDEX is None:
        raise StarletteHTTPException(status_code=404)
    if full_path.startswith(("api/", "api", "health", "metrics", "docs", "openapi", "redoc")):
        raise StarletteHTTPException(status_code=404)
    candidate = os.path.normpath(os.path.join(_FRONTEND_DIST, full_path))
    if full_path and candidate.startswith(_FRONTEND_DIST) and os.path.isfile(candidate):
        return FileResponse(candidate)
    return FileResponse(_FRONTEND_INDEX)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )

