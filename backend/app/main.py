# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

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
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.auth import require_auth
from app.core.config import settings
from app.core.gpu_memory import query_gpu_memory as _query_gpu_memory
from app.core.health_checks import check_sync, check_has_ner
from app.api import safety as safety_api
from app.core.errors import AppError, app_error_handler, http_exception_handler, validation_exception_handler
from app.api import auth as auth_api
from app.api import files, redaction, entity_types, vision_pipeline, model_config, ner_backend, presets, jobs
from app.models.schemas import HealthResponse

from app.core.logging_config import setup_logging
# 生产环境用 JSON 格式；DEBUG 模式用文本格式（人类可读）
setup_logging(json_mode=settings.LOG_JSON and not settings.DEBUG, level=logging.DEBUG if settings.DEBUG else logging.INFO)
logger = logging.getLogger(__name__)

def cleanup_orphan_files() -> int:
    """Remove orphan files from upload/output directories that are not tracked in file_store.

    Safety guard: if file_store has far fewer entries than the number of files
    on disk, skip cleanup entirely to avoid accidental mass deletion (e.g. after
    a failed migration that left file_store empty).
    """
    import time
    from app.services.file_management_service import get_file_store
    file_store = get_file_store()

    # Count files on disk first
    disk_count = 0
    for directory in (settings.UPLOAD_DIR, settings.OUTPUT_DIR):
        if os.path.isdir(directory):
            disk_count += sum(1 for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f)))

    store_count = len(file_store)
    # Safety: if disk has files but file_store is nearly empty, something is wrong — skip cleanup
    if disk_count > 5 and store_count < disk_count // 2:
        logger.warning(
            "Orphan cleanup SKIPPED: disk has %d files but file_store only tracks %d. "
            "Possible migration issue — refusing to delete.",
            disk_count, store_count,
        )
        return 0

    # Build known paths set
    known_paths = set()
    snapshot = dict(file_store.items())
    for info in snapshot.values():
        if isinstance(info, dict):
            fp = info.get("file_path")
            if fp:
                known_paths.add(os.path.realpath(fp))
            op = info.get("output_path")
            if op:
                known_paths.add(os.path.realpath(op))

    removed = 0
    for directory in (settings.UPLOAD_DIR, settings.OUTPUT_DIR):
        if not os.path.isdir(directory):
            continue
        for fname in os.listdir(directory):
            fpath = os.path.join(directory, fname)
            if not os.path.isfile(fpath):
                continue
            real = os.path.realpath(fpath)
            if real not in known_paths:
                age = time.time() - os.path.getmtime(fpath)
                if age > settings.ORPHAN_CLEANUP_AGE_SEC:
                    try:
                        os.remove(fpath)
                        removed += 1
                        logger.info("Orphan cleanup: removed %s (age %.0fs)", fname, age)
                    except OSError:
                        pass
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

    # 0a. Run schema migrations (idempotent, safe on every startup)
    from app.core.migrations import run_migrations
    run_migrations(settings.JOB_DB_PATH)

    # 0b. Database integrity check + restore from backup if corrupted
    from app.core.db_backup import ensure_db_healthy, backup_sqlite
    ensure_db_healthy(settings.JOB_DB_PATH)

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
    from app.services.task_queue import get_task_queue, TaskItem
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
                _task_queue.enqueue(TaskItem(
                    job_id=_j["id"], item_id=_it["id"], file_id=_it["file_id"],
                    task_type="recognition",
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

    # 5. Start periodic database backup (every hour)
    async def _periodic_backup():
        while True:
            await asyncio.sleep(3600)
            try:
                backup_sqlite(settings.JOB_DB_PATH)
            except Exception:
                logger.exception("periodic database backup failed")

    _backup_task = asyncio.create_task(_periodic_backup())

    yield

    # === Shutdown (graceful: wait up to 30s for in-progress work) ===
    logger.info("Shutting down: stopping task queue and background tasks...")
    _task_queue.stop()
    _cleanup_task.cancel()
    _backup_task.cancel()
    tasks_to_wait = [_cleanup_task, _backup_task]
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
    def __init__(self, app, max_body_size: int = 60 * 1024 * 1024):  # 60MB
        super().__init__(app)
        self.max_body_size = max_body_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_body_size:
            return JSONResponse(
                status_code=413,
                content={"error_code": "BODY_TOO_LARGE", "message": "请求体过大", "detail": {}},
            )
        return await call_next(request)


# NOTE: Starlette processes middleware in reverse registration order (last added
# runs first). Register MaxBodySizeMiddleware AFTER CORSMiddleware so that the
# body-size check executes BEFORE CORS headers are evaluated.

# CSRF protection (double-submit cookie; inner to CORS so preflight is handled first)
from app.core.csrf import CSRFMiddleware  # noqa: E402
app.add_middleware(CSRFMiddleware)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Idempotency-Key", "X-CSRF-Token"],
)

# Security response headers (outer to CORS so headers appear on all responses incl. preflight)
from app.core.security_headers import SecurityHeadersMiddleware  # noqa: E402
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(MaxBodySizeMiddleware)

# Rate-limit: 600 requests/minute per IP（批量任务含高频轮询，120 太紧）
from app.core.rate_limit import RateLimitMiddleware  # noqa: E402
app.add_middleware(RateLimitMiddleware, max_requests=600, window_seconds=60)

# Request-ID: outermost middleware (registered last = runs first in Starlette)
from app.core.request_id import RequestIdMiddleware  # noqa: E402
app.add_middleware(RequestIdMiddleware)

# 确保上传和输出目录存在
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

# 注意：不再挂载 /uploads 和 /outputs 为 StaticFiles，
# 因为 StaticFiles 会绕过 require_auth 认证中间件。
# 所有文件访问统一通过 /api/v1/files/{file_id}/download 端点（已有认证保护）。

# 注册路由
app.include_router(auth_api.router, prefix=settings.API_PREFIX)
app.include_router(files.router, prefix=settings.API_PREFIX, tags=["文件管理"], dependencies=[Depends(require_auth)])
app.include_router(redaction.router, prefix=settings.API_PREFIX, tags=["匿名化处理"], dependencies=[Depends(require_auth)])
app.include_router(entity_types.router, prefix=settings.API_PREFIX, tags=["文本识别类型管理"], dependencies=[Depends(require_auth)])
app.include_router(vision_pipeline.router, prefix=settings.API_PREFIX, tags=["图像识别Pipeline管理"], dependencies=[Depends(require_auth)])
app.include_router(model_config.router, prefix=settings.API_PREFIX, tags=["推理模型配置"], dependencies=[Depends(require_auth)])
app.include_router(ner_backend.router, prefix=settings.API_PREFIX, tags=["文本NER后端"], dependencies=[Depends(require_auth)])
app.include_router(presets.router, prefix=settings.API_PREFIX, tags=["识别配置预设"], dependencies=[Depends(require_auth)])
app.include_router(jobs.router, prefix=settings.API_PREFIX, tags=["批量任务"], dependencies=[Depends(require_auth)])
app.include_router(safety_api.router, prefix=settings.API_PREFIX, tags=["数据安全"], dependencies=[Depends(require_auth)])

logger.info("presets API: GET/POST %s/presets (若前端仍 404，请重启本进程以加载最新路由)", settings.API_PREFIX)

# Prometheus metrics endpoint
from app.core.metrics import metrics_endpoint
app.add_route("/metrics", metrics_endpoint, methods=["GET"])


@app.get("/", tags=["根路径"])
async def root():
    """API 根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs" if settings.DEBUG else None,
    }


@app.get("/health", response_model=HealthResponse, tags=["健康检查"])
async def health_check():
    """健康检查接口"""
    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
    )


@app.get("/health/services", tags=["健康检查"])
async def services_health():
    """
    各模型服务的真实健康状态
    前端轮询此接口来显示服务状态
    """
    import asyncio
    import time
    from datetime import datetime, timezone

    services = {}

    # 在线程池中并行检查所有服务（避免阻塞事件循环）
    loop = asyncio.get_event_loop()
    t0 = time.perf_counter()
    ocr_url = f"{settings.OCR_BASE_URL}/health"
    ocr_timeout = float(settings.OCR_HEALTH_PROBE_TIMEOUT)
    ocr_result, has_result, has_image_result = await asyncio.gather(
        loop.run_in_executor(
            None,
            lambda: check_sync(ocr_url, "PaddleOCR-VL-1.5", ocr_timeout),
        ),
        loop.run_in_executor(None, check_has_ner),
        loop.run_in_executor(None, check_sync, f"{settings.HAS_IMAGE_BASE_URL}/health", "HaS Image YOLO"),
    )
    probe_ms = round((time.perf_counter() - t0) * 1000, 1)

    gpu_mem = await loop.run_in_executor(None, _query_gpu_memory)

    services["paddle_ocr"] = {"name": ocr_result[0], "status": "online" if ocr_result[1] else "offline"}
    services["has_ner"] = {"name": has_result[0], "status": "online" if has_result[1] else "offline"}
    services["has_image"] = {"name": has_image_result[0], "status": "online" if has_image_result[1] else "offline"}
    all_online = all(s["status"] == "online" for s in services.values())

    return {
        "all_online": all_online,
        "services": services,
        "probe_ms": probe_ms,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "gpu_memory": gpu_mem,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
