"""
法律文件脱敏平台 - FastAPI 应用入口
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

import httpx

from app.core.auth import require_auth
from app.core.config import settings, get_has_display_name, get_has_chat_base_url, get_has_health_check_url
from app.core.errors import AppError, app_error_handler, http_exception_handler, validation_exception_handler
from app.api import auth as auth_api
from app.api import files, redaction, entity_types, vision_pipeline, model_config, ner_backend, presets, jobs
from app.models.schemas import HealthResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _job_worker_task

    # === Startup ===

    # 1. Clean up orphan files
    import time
    from app.api.files import file_store

    known_paths = set()
    for info in file_store.values():
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
                if age > 3600:
                    try:
                        os.remove(fpath)
                        removed += 1
                    except OSError:
                        pass

    if removed:
        logger.info("Cleaned up %d orphan files", removed)

    # 2. Check external services
    from app.services.ocr_service import ocr_service
    if ocr_service.is_available():
        logger.info("OCR service online (%s)", ocr_service.get_model_name())
    else:
        logger.info("OCR service offline (expected at %s)", ocr_service.base_url)

    # 3. Start job worker
    from app.api.jobs import get_job_store
    from app.services.job_runner import worker_loop_forever

    _job_worker_task = asyncio.create_task(worker_loop_forever(get_job_store(), interval_sec=2.0))

    yield

    # === Shutdown ===
    if _job_worker_task and not _job_worker_task.done():
        _job_worker_task.cancel()
        try:
            await _job_worker_task
        except asyncio.CancelledError:
            pass


# 创建 FastAPI 应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="智能数据脱敏平台，支持 Word/PDF/图片等多格式文档的敏感信息自动识别与脱敏处理，基于 GB/T 37964-2019 国家标准",
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

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(MaxBodySizeMiddleware)

# Rate-limit: 120 requests/minute per IP
from app.core.rate_limit import RateLimitMiddleware  # noqa: E402
app.add_middleware(RateLimitMiddleware, max_requests=120, window_seconds=60)

# 确保上传和输出目录存在
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

# 注意：不再挂载 /uploads 和 /outputs 为 StaticFiles，
# 因为 StaticFiles 会绕过 require_auth 认证中间件。
# 所有文件访问统一通过 /api/v1/files/{file_id}/download 端点（已有认证保护）。

# 注册路由
app.include_router(auth_api.router, prefix=settings.API_PREFIX)
app.include_router(files.router, prefix=settings.API_PREFIX, tags=["文件管理"], dependencies=[Depends(require_auth)])
app.include_router(redaction.router, prefix=settings.API_PREFIX, tags=["脱敏处理"], dependencies=[Depends(require_auth)])
app.include_router(entity_types.router, prefix=settings.API_PREFIX, tags=["文本识别类型管理"], dependencies=[Depends(require_auth)])
app.include_router(vision_pipeline.router, prefix=settings.API_PREFIX, tags=["图像识别Pipeline管理"], dependencies=[Depends(require_auth)])
app.include_router(model_config.router, prefix=settings.API_PREFIX, tags=["推理模型配置"], dependencies=[Depends(require_auth)])
app.include_router(ner_backend.router, prefix=settings.API_PREFIX, tags=["文本NER后端"], dependencies=[Depends(require_auth)])
app.include_router(presets.router, prefix=settings.API_PREFIX, tags=["识别配置预设"], dependencies=[Depends(require_auth)])
app.include_router(jobs.router, prefix=settings.API_PREFIX, tags=["批量任务"], dependencies=[Depends(require_auth)])

logger.info("presets API: GET/POST %s/presets (若前端仍 404，请重启本进程以加载最新路由)", settings.API_PREFIX)

_job_worker_task: asyncio.Task | None = None


def check_sync(url: str, default_name: str, timeout: float = 3.0) -> tuple:
    """同步检查 HTTP 服务（供 /health/services 在线程池中调用）。"""
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                name = default_name
                if "model" in data:
                    name = data["model"]
                elif "data" in data and isinstance(data["data"], list) and data["data"]:
                    name = data["data"][0].get("id", default_name)
                elif "models" in data and isinstance(data["models"], list) and data["models"]:
                    name = data["models"][0].get("name", default_name)
                # 显式带 ready 字段时以布尔为准（OCR / HaS Image）；缺省则视为就绪
                ready = bool(data["ready"]) if "ready" in data else True
                if data.get("status") == "unavailable":
                    ready = False
                return name, ready
    except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError):
        pass
    return default_name, False


def _nvsmi_install_dirs_windows() -> list[str]:
    """NVIDIA NVSMI 目录（nvidia-smi.exe 与 nvml.dll 常同目录；多盘符/多安装位）。"""
    import os

    out: list[str] = []
    seen: set[str] = set()
    if os.name != "nt":
        return out
    for key in ("LEGAL_REDACTION_NVSMI_PATH", "NVIDIA_NVSMI_PATH"):
        p = os.environ.get(key, "").strip().strip('"')
        if p and os.path.isdir(p) and p not in seen:
            seen.add(p)
            out.append(p)
    roots: list[str] = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"),
    ]
    for letter in ("D", "E", "F"):
        roots.append(f"{letter}:\\Program Files")
    for root in roots:
        p = os.path.join(root, "NVIDIA Corporation", "NVSMI")
        if p not in seen and os.path.isdir(p):
            seen.add(p)
            out.append(p)
    pd = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "NVIDIA Corporation", "NVSMI")
    if pd not in seen and os.path.isdir(pd):
        seen.add(pd)
        out.append(pd)
    return out


def _nvidia_smi_executable_candidates() -> list[str]:
    """
    可执行文件路径候选。
    Windows 下 IDE/服务启动的 Python 往往没有用户终端里的 PATH，故 **优先** 固定 NVSMI 路径。
    """
    import os
    import shutil

    out: list[str] = []
    seen: set[str] = set()
    if os.name == "nt":
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        for extra in (
            os.path.join(sysroot, "System32", "nvidia-smi.exe"),
            os.path.join(sysroot, "nvidia-smi.exe"),
        ):
            if extra not in seen and os.path.isfile(extra):
                seen.add(extra)
                out.append(extra)
        for d in _nvsmi_install_dirs_windows():
            p = os.path.join(d, "nvidia-smi.exe")
            if p not in seen and os.path.isfile(p):
                seen.add(p)
                out.append(p)
    for name in ("nvidia-smi", "nvidia-smi.exe"):
        w = shutil.which(name)
        if w and w not in seen and os.path.isfile(w):
            seen.add(w)
            out.append(w)
    return out


def _parse_nvidia_smi_memory_csv(stdout: str) -> dict | None:
    if not stdout or not stdout.strip():
        return None
    line = stdout.strip().splitlines()[0].lstrip("\ufeff")
    parts = [x.strip() for x in line.split(",")]
    if len(parts) < 2:
        return None
    try:
        used_mb = int(float(parts[0]))
        total_mb = int(float(parts[1]))
        return {"used_mb": used_mb, "total_mb": total_mb}
    except (ValueError, TypeError):
        return None


def _parse_nvidia_smi_loose(stdout: str) -> dict | None:
    """兼容非英文环境或表格输出：匹配「数字 MiB / 数字 MiB」。"""
    import re

    if not stdout:
        return None
    m = re.search(r"(\d+)\s*MiB\s*/\s*(\d+)\s*MiB", stdout, re.IGNORECASE)
    if not m:
        return None
    try:
        return {"used_mb": int(m.group(1)), "total_mb": int(m.group(2))}
    except (ValueError, TypeError):
        return None


def _run_one_nvidia_smi(
    exe: str,
    *,
    use_no_window: bool,
    cwd: str | None = None,
    loose_fallback: bool = False,
) -> dict | None:
    """单次运行 nvidia-smi；cwd 设为 exe 所在目录可加载同目录 nvml.dll（Windows 常见问题）。"""
    import os
    import subprocess

    args = [exe, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"]
    timeout = 12.0
    workdir = cwd
    if workdir is None and os.name == "nt":
        workdir = os.path.dirname(os.path.abspath(exe)) or None

    base_kw: dict = {
        "capture_output": True,
        "timeout": timeout,
        "encoding": "utf-8",
        "errors": "replace",
        "stdin": subprocess.DEVNULL,
    }
    if workdir and os.path.isdir(workdir):
        base_kw["cwd"] = workdir
    if os.name == "nt" and use_no_window:
        base_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def _parse(out: str) -> dict | None:
        p = _parse_nvidia_smi_memory_csv(out)
        if p:
            return p
        if loose_fallback:
            return _parse_nvidia_smi_loose(out)
        return None

    try:
        r = subprocess.run(args, **base_kw)
        out = (r.stdout or "").strip()
        if not out and (r.stderr or "").strip():
            out = (r.stderr or "").strip()
        parsed = _parse(out)
        if parsed and r.returncode == 0:
            return parsed
        if parsed and out:
            return parsed
        # 无 CSV 时再试整表输出（部分驱动/语言包下 query 失败）
        if loose_fallback and not parsed:
            kw2: dict = {
                "capture_output": True,
                "timeout": timeout,
                "encoding": "utf-8",
                "errors": "replace",
                "stdin": subprocess.DEVNULL,
            }
            if workdir and os.path.isdir(workdir):
                kw2["cwd"] = workdir
            if os.name == "nt" and use_no_window:
                kw2["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            r2 = subprocess.run([exe], **kw2)
            out2 = ((r2.stdout or "") + "\n" + (r2.stderr or "")).strip()
            parsed2 = _parse_nvidia_smi_loose(out2)
            if parsed2:
                return parsed2
    except (subprocess.SubprocessError, OSError, ValueError, TypeError):
        pass
    return None


def _query_gpu_memory_nvidia_smi() -> dict | None:
    """
    本机 NVIDIA 显存占用（MiB）。无 nvidia-smi 或非 NVIDIA 环境返回 None。
    """
    import os

    for exe in _nvidia_smi_executable_candidates():
        for m in (
            _run_one_nvidia_smi(exe, use_no_window=True, loose_fallback=False),
            _run_one_nvidia_smi(exe, use_no_window=False, loose_fallback=False),
            _run_one_nvidia_smi(exe, use_no_window=False, loose_fallback=True),
        ):
            if m:
                return m
    return None


_nvml_initialized = False
_nvml_dll_prepared = False


def _ensure_nvml_dll_windows() -> None:
    """Python 3.8+ Windows：nvml.dll 在 NVSMI 目录时须 add_dll_directory，否则 pynvml 初始化失败。"""
    global _nvml_dll_prepared
    import os
    import sys

    if _nvml_dll_prepared or os.name != "nt":
        return
    _nvml_dll_prepared = True
    path_prefix = []
    for d in _nvsmi_install_dirs_windows():
        nvml = os.path.join(d, "nvml.dll")
        if os.path.isfile(nvml):
            try:
                if sys.version_info >= (3, 8):
                    os.add_dll_directory(d)
            except (OSError, AttributeError):
                pass
            path_prefix.append(d)
    if path_prefix:
        os.environ["PATH"] = os.pathsep.join(path_prefix) + os.pathsep + os.environ.get("PATH", "")


def _query_gpu_memory_pynvml() -> dict | None:
    """NVML（与 nvidia-smi 同源）；Windows 上先注入 NVSMI 目录再 nvmlInit。"""
    global _nvml_initialized
    import os

    try:
        import pynvml
    except ImportError:
        return None
    if os.name == "nt":
        _ensure_nvml_dll_windows()
    try:
        if not _nvml_initialized:
            pynvml.nvmlInit()
            _nvml_initialized = True
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        mib = 1024 * 1024
        return {"used_mb": int(mem.used // mib), "total_mb": max(1, int(mem.total // mib))}
    except Exception:  # broad catch: pynvml.NVMLError cannot be referenced if pynvml import fails
        return None


def _query_gpu_memory_paddle() -> dict | None:
    """
    无 nvidia-smi 时，用 Paddle CUDA API 读显存（主进程若已 import paddle 且为 GPU 版）。
    used 为当前进程在 GPU 上已分配量；total 为卡总显存。单位 MiB。
    """
    try:
        import paddle

        if not paddle.is_compiled_with_cuda() or paddle.device.cuda.device_count() < 1:
            return None
        paddle.device.set_device("gpu:0")
        used = int(paddle.device.cuda.memory_allocated("gpu:0"))
        prop = paddle.device.cuda.get_device_properties(0)
        total = int(prop.total_memory)
        mib = 1024 * 1024
        return {"used_mb": used // mib, "total_mb": max(1, total // mib)}
    except Exception:  # broad catch: paddle internal errors are not part of public API
        return None


def _query_gpu_memory() -> dict | None:
    # Windows：NVML 常比子进程更稳；Linux 上 nvidia-smi 更常见
    if os.name == "nt":
        order = (
            _query_gpu_memory_pynvml,
            _query_gpu_memory_nvidia_smi,
            _query_gpu_memory_paddle,
        )
    else:
        order = (
            _query_gpu_memory_nvidia_smi,
            _query_gpu_memory_pynvml,
            _query_gpu_memory_paddle,
        )
    for fn in order:
        m = fn()
        if m:
            return m
    return None


def check_has_ner() -> tuple:
    """HaS：llama-server 部分构建无 GET /v1/models，需多路径探测；Ollama 仍用 /api/tags。"""
    from app.core.config import is_ner_ollama
    from app.core.llamacpp_probe import probe_llamacpp

    default_name = get_has_display_name()
    if is_ner_ollama():
        return check_sync(get_has_health_check_url(), default_name)
    ok, _name, _, _strict = probe_llamacpp(get_has_chat_base_url(), timeout=3.0)
    if ok:
        # 展示名固定为当前产品模型（HaS Text 0209），不暴露 llama /health 里的路径或旧 id
        return default_name, True
    return default_name, False




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
