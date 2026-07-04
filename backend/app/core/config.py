"""
应用配置管理
支持从环境变量和 .env 文件加载配置
"""
import json
import logging
import os
import secrets
import socket
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse, urlunparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
_LOCAL_MODEL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_WSL_URL_CACHE_TTL_SEC = 30.0
_WSL_URL_CACHE: dict[tuple[str, int], tuple[float, str | None]] = {}


def _resolve_local_path(raw: str, *, base_dir: Path = BACKEND_DIR) -> str:
    """Resolve relative repo-local paths against the backend root, not the process CWD."""
    value = str(raw or "").strip()
    if not value:
        return ""
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    if expanded.is_absolute():
        return str(expanded.resolve())
    return str((base_dir / expanded).resolve())


def _hide_file_windows(path: str) -> None:
    """Best-effort: set the 'hidden' attribute on Windows via kernel32."""
    try:
        import ctypes
        # FILE_ATTRIBUTE_HIDDEN = 0x2
        ctypes.windll.kernel32.SetFileAttributesW(path, 0x2)  # type: ignore[union-attr]
    except Exception:
        pass


def _tcp_connects(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wsl_host_candidates() -> list[str]:
    candidates: list[str] = []
    explicit = os.environ.get("WSL_MODEL_HOST", "").strip()
    if explicit:
        candidates.append(explicit)
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["wsl.exe", "-e", "bash", "-lc", "hostname -I"],
                capture_output=True,
                encoding="utf-8",
                errors="ignore",
                text=True,
                timeout=2.0,
                check=False,
            )
            for token in (result.stdout or "").split():
                parts = token.split(".")
                if len(parts) == 4 and all(part.isdigit() for part in parts):
                    candidates.append(token)
        except Exception:
            logging.getLogger(__name__).debug("Unable to resolve WSL host", exc_info=True)
    seen: set[str] = set()
    return [item for item in candidates if item and not (item in seen or seen.add(item))]


def _url_with_host(base_url: str, host: str) -> str:
    parsed = urlparse(base_url)
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme or "http", netloc, parsed.path.rstrip("/"), "", "", ""))


def _resolve_wsl_localhost_url(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    parsed = urlparse(base)
    host = (parsed.hostname or "").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if host not in _LOCAL_MODEL_HOSTS:
        return base
    if _tcp_connects(parsed.hostname or host, port):
        return base

    cache_key = (base, port)
    now = time.monotonic()
    cached = _WSL_URL_CACHE.get(cache_key)
    if cached and now - cached[0] <= _WSL_URL_CACHE_TTL_SEC:
        return cached[1] or base

    for candidate in _wsl_host_candidates():
        if _tcp_connects(candidate, port):
            resolved = _url_with_host(base, candidate)
            _WSL_URL_CACHE[cache_key] = (now, resolved)
            logging.getLogger(__name__).info("Resolved local model service %s through WSL host %s", base, candidate)
            return resolved

    _WSL_URL_CACHE[cache_key] = (now, None)
    return base


def _load_or_create_jwt_secret(data_dir: str) -> str:
    """Load or generate a JWT secret.

    Resolution order:
    1. ``LEGAL_REDACTION_JWT_SECRET`` environment variable (highest priority)
    2. Persisted file in *data_dir* (``jwt_secret.json``)
    3. Generate a new secret, persist it, and return it.

    On Windows the file is marked *hidden* as a best-effort protection
    (``os.chmod 0o600`` has no effect on NTFS).
    """
    logger = logging.getLogger(__name__)

    # --- 1. Environment variable -------------------------------------------------
    env_secret = os.environ.get("LEGAL_REDACTION_JWT_SECRET", "").strip()
    if env_secret:
        logger.debug("JWT secret loaded from LEGAL_REDACTION_JWT_SECRET env var")
        return env_secret

    # --- 2. Existing file --------------------------------------------------------
    secret_path = os.path.join(data_dir, "jwt_secret.json")
    if os.path.exists(secret_path):
        try:
            with open(secret_path) as f:
                secret = json.load(f).get("secret", "")
            if secret:
                return secret
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.warning("JWT secret file corrupted, regenerating: %s", e)

    # --- 3. Generate & persist ---------------------------------------------------
    secret = secrets.token_urlsafe(32)
    os.makedirs(data_dir, exist_ok=True)
    try:
        with open(secret_path, "w") as f:
            json.dump({"secret": secret}, f)
    except OSError as e:
        logger.error("Failed to persist JWT secret: %s", e)

    # Platform-specific file protection
    if os.name == "nt":
        _hide_file_windows(secret_path)
        logger.warning(
            "Windows: JWT secret file '%s' is hidden but NOT permission-protected "
            "(NTFS does not honour POSIX chmod). Consider setting the "
            "LEGAL_REDACTION_JWT_SECRET environment variable instead.",
            secret_path,
        )
    else:
        try:
            os.chmod(secret_path, 0o600)
        except OSError:
            pass

    return secret


class Settings(BaseSettings):
    """应用配置"""

    # 应用基础配置
    APP_NAME: str = "DataShield 匿名化数据基础设施"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # API 配置
    API_PREFIX: str = "/api/v1"

    # CORS 配置
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # 文件上传配置
    UPLOAD_DIR: str = "./uploads"
    OUTPUT_DIR: str = "./outputs"
    DATA_DIR: str = "./data"
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    ALLOWED_EXTENSIONS: list[str] = [
        # Documents
        ".doc",
        ".docx",
        ".txt",
        ".rtf",
        ".md",
        ".html",
        ".htm",
        # PDF
        ".pdf",
        # Images
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".gif",
        ".webp",
        ".tif",
        ".tiff",
    ]

    # LocateAnything visual feature service
    VISUAL_FEATURES_BASE_URL: str = "http://127.0.0.1:8090"
    VISUAL_FEATURES_MODEL_NAME: str = "LocateAnything-3B"
    VISUAL_FEATURES_TIMEOUT: float = 240.0
    VISUAL_FEATURES_CONF: float = 0.25
    VISUAL_FEATURES_COORD_MODE: int = 1000
    VISUAL_FEATURES_MAX_IMAGE_SIDE: int = 1408
    VISUAL_FEATURES_SIGNATURE_MAX_IMAGE_SIDE: int = 1280
    VISUAL_FEATURES_CONCURRENCY: int = 1
    LOCATE_ANYTHING_MAX_NEW_TOKENS: int = 8192
    LOCATE_ANYTHING_MAX_IMAGE_SIDE: int = 1408
    LOCATE_ANYTHING_SIGNATURE_MAX_IMAGE_SIDE: int = 1280
    LOCATE_ANYTHING_SIGNATURE_TILE_MAX_IMAGE_SIDE: int = 1280

    # 本地持久化（空串 = 跟随 DATA_DIR 自动派生，见 model_validator）
    FILE_STORE_PATH: str = ""
    JOB_DB_PATH: str = ""
    PIPELINE_STORE_PATH: str = ""
    PRESET_STORE_PATH: str = ""
    ENTITY_TYPES_STORE_PATH: str = ""
    MODEL_CONFIG_PATH: str = ""

    # PaddleOCR-VL 微服务配置（独立进程，端口8082）
    OCR_BASE_URL: str = "http://127.0.0.1:8082"
    # VL 推理常 >120s（大图 CPU/显卡繁忙时）；可用环境变量 OCR_TIMEOUT 覆盖
    OCR_TIMEOUT: float = 360.0
    # PaddleOCR-VL generation budget. Long scanned contract pages can exceed
    # 512 tokens; keep this configurable so accuracy and latency can be tuned
    # per GPU.
    OCR_MAX_NEW_TOKENS: int = 2048
    # 主后端探测 OCR /health 的超时（秒）；首次加载模型较慢，过短会被显示「离线」
    OCR_HEALTH_PROBE_TIMEOUT: float = 5.0
    BATCH_RECOGNITION_PAGE_TIMEOUT: float = 180.0
    # Per-file page-level concurrency for vision recognition. This is not batch
    # item concurrency; JOB_CONCURRENCY controls how many job items the worker
    # consumes at once. The runtime caps this value to the current file's page
    # count, and the validator below clamps operator overrides to 1..8. Lower
    # this to 1 when GPU memory is already above the saturation ratio or model
    # services are cold.
    BATCH_RECOGNITION_PAGE_CONCURRENCY: int = 2
    # Page concurrency for the multi-page visual-features merge pass. Default 1
    # keeps the historical serial behaviour (safe on a single GPU); deployments
    # with one LocateAnything instance per card can raise to 2.
    BATCH_VISUAL_MERGE_PAGE_CONCURRENCY: int = 1
    # GPU memory used/total ratio at/above which vision page concurrency is
    # forced down to 1. Raise on multi-service cards whose *static* residency is
    # already high (e.g. dual-GPU prod ~80% at idle) so healthy load is not
    # misread as saturation.
    GPU_SATURATION_RATIO: float = 0.90
    # Single-GPU safety: OCR/HaS and LocateAnything run SEQUENTIALLY. On one GPU,
    # running both heavy VLMs at once causes ~5-10x slowdown from contention
    # (measured: 54s parallel vs ~10s serial on one file).
    SERIALIZE_SHARED_GPU_MODELS: bool = True
    VISION_DUAL_PIPELINE_PARALLEL: bool = False
    # PaddleOCR-VL toggle. Dropped from the default deployment: when false the
    # backend never calls the VL /ocr endpoint and routes all OCR through
    # PP-StructureV3 (the current, faster, more precise path).
    OCR_VL_ENABLED: bool = False
    # PP-StructureV3 is the document OCR/layout path now that PaddleOCR-VL is
    # dropped. Keep enabled.
    OCR_STRUCTURE_ENABLED: bool = True
    OCR_STRUCTURE_MIN_VL_BOXES: int = 12
    # PP-StructureV3 is the primary (and only) document OCR path. The VL fusion
    # supplement below stays off unless VL is re-enabled.
    OCR_STRUCTURE_PRIMARY: bool = True
    OCR_STRUCTURE_PRIMARY_MIN_BOXES: int = 8
    OCR_MAX_IMAGE_SIDE: int = 2048
    # When PP-StructureV3 already returns enough text boxes, use it directly by
    # default. Enable this only when tighter PaddleOCR-VL text fusion is worth
    # the extra GPU pass on the current hardware.
    OCR_STRUCTURE_PRIMARY_SUPPLEMENT_VL: bool = False
    # Use PP-StructureV3 as a short-field precision supplement for OCR/HaS
    # semantic detection. Disabled by default to keep the OCR path VL-only.
    OCR_STRUCTURE_TEXT_PRECISION_ENABLED: bool = False
    OCR_TEXT_BLOCK_CACHE_TTL_SEC: float = 300.0
    OCR_TEXT_BLOCK_CACHE_MAX_ITEMS: int = 128
    OCR_REQUIRE_VL_FOR_VISUAL_REGIONS: bool = False
    # For born-digital PDFs, use the native text layer as OCR coordinates and
    # still let HaS Text decide semantics. Scanned PDFs automatically fall back
    # to the image OCR path when the text layer is too sparse.
    PDF_TEXT_LAYER_VISION_ENABLED: bool = True
    PDF_TEXT_LAYER_MIN_CHARS: int = 80
    # True: OCR 服务离线时直接报错而非尝试 CPU 回退（防止超慢推理阻塞队列）
    OCR_REQUIRE_GPU: bool = False

    # 文本 NER：HaS Text（默认 vLLM 8080/v1，OpenAI 兼容；llama.cpp 仅保留为旧调试入口）
    HAS_LLAMACPP_BASE_URL: str = "http://127.0.0.1:8080/v1"
    HAS_MODEL_PATH: str = "./models/has/HaS_Text_0209_0.6B_Q4_K_M.gguf"
    HAS_TEXT_RUNTIME: str = ""
    HAS_TEXT_VLLM_BASE_URL: str = "http://127.0.0.1:8080/v1"
    HAS_TEXT_MODEL_NAME: str = ""
    HAS_TIMEOUT: float = 120.0
    HAS_NER_CONTEXT_TOKENS: int = 8192
    HAS_NER_MAX_TOKENS: int = 8192
    HAS_NER_MAX_TYPES_PER_REQUEST: int = 12
    HAS_NER_CUSTOM_MAX_TYPES_PER_REQUEST: int = 16
    HAS_NER_TYPE_BATCH_TARGET_TOKENS: int = 900
    HAS_NER_SINGLE_PASS_MAX_TYPES: int = 96
    HAS_NER_SINGLE_PASS_MAX_TEXT_CHARS: int = 1600
    HAS_NER_MAX_PARALLEL_REQUESTS: int = 4
    # 全进程 HaS NER 并发闸门（shared_gpu_inference_slot 的信号量大小）。
    # 1 = 历史串行行为（单卡小显存部署安全默认）；vLLM 多实例部署可放开
    # （双卡 5090 生产 = 6：双实例 × 每实例 ~3，受 KV cache 预算约束）。
    HAS_NER_GLOBAL_MAX_INFLIGHT: int = 1

    # --- 批量异步导出（万级文件：分卷落盘，见 services/export_service.py） ---
    EXPORT_VOLUME_MAX_BYTES: int = 2 * 1024**3   # 每卷 zip ≤2GB
    EXPORT_VOLUME_MAX_FILES: int = 1000          # 每卷 ≤1000 文件
    EXPORT_TTL_HOURS: float = 72.0               # 导出产物保留时长
    EXPORT_SYNC_MAX_FILES: int = 200             # 超过则旧同步 zip 端点拒绝并引导异步
    EXPORT_SYNC_MAX_BYTES: int = 500 * 1024**2
    EXPORT_TABLE_ROWS_PER_FILE: int = 50_000     # 明细/表格类导出每卷行数（Excel 体验线）
    STRUCTURED_MAX_EXPORT_ROWS: int = 5_000_000  # 库表导出硬护栏：超限报错，绝不静默截断
    STRUCTURED_MAX_FILE_SIZE: int = 200 * 1024**2  # /structured/files 上传上限
    HAS_NER_BUILTIN_GUIDANCE_ENABLED: bool = False
    HAS_NER_CACHE_TTL_SEC: float = 300.0
    HAS_NER_CACHE_MAX_ITEMS: int = 256
    # Structured table profiling uses HaS only as an enrichment layer. Keep it
    # short so a cold or busy text model cannot block table review and delivery.
    STRUCTURED_HAS_TIMEOUT: float = 6.0
    # Keep HaS Text OCR requests bounded. Scanned PDFs can produce coarse page
    # aggregates; HaS still decides semantics, but the backend should not send
    # unbounded OCR text into a cold local NER queue.
    HAS_VISION_MAX_TEXT_CHARS: int = 32_000
    HAS_VISION_MAX_BLOCK_CHARS: int = 8_000
    # Conservative default keeps existing recall; raise only to skip low-signal
    # OCR pages before sending them to HaS Text.
    HAS_VISION_MIN_TEXT_CHARS_FOR_NER: int = 1

    # 兼容旧环境变量 HAS_BASE_URL
    HAS_BASE_URL: str | None = None

    # 认证配置（JWT_SECRET_KEY 若未通过环境变量指定，则自动持久化到 data 目录）
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 hours
    LOCAL_PASSWORD_HASH: str = ""  # PBKDF2 hash, set via setup endpoint
    AUTH_ENABLED: bool = os.environ.get("AUTH_ENABLED", "true").lower() == "true"

    # 企业目录（LDAP/AD）登录。默认关闭：登录行为与纯本地账号完全一致。
    # 开启后 /auth/login 先走目录认证（本地 super_admin 保留 break-glass 本地
    # 通道）；两种模式与组→角色映射见 app/core/ldap_auth.py。
    LDAP_ENABLED: bool = False
    LDAP_SERVER_URL: str = ""  # 生产要求 ldaps://（见 LDAP_TLS_REQUIRED）
    LDAP_BIND_DN_TEMPLATE: str = ""  # 直接绑定模式，如 "uid={username},ou=people,dc=corp,dc=com"
    LDAP_SEARCH_BASE: str = ""  # 设置后启用 搜索+绑定 模式（优先于直接绑定）
    LDAP_SERVICE_BIND_DN: str = ""
    LDAP_SERVICE_BIND_PASSWORD: str = ""
    LDAP_USER_FILTER: str = "(sAMAccountName={username})"
    LDAP_GROUP_ROLE_MAP: str = ""  # JSON 对象文本：{"组DN": "角色"}，声明顺序优先
    LDAP_DEFAULT_ROLE: str = "user"
    LDAP_TIMEOUT_SECONDS: float = 5.0
    LDAP_TLS_REQUIRED: bool = True
    LDAP_CA_CERT_FILE: str = ""
    LDAP_ROLE_SYNC: bool = True  # 每次登录按目录组重算并落库角色

    @field_validator("LDAP_TIMEOUT_SECONDS")
    @classmethod
    def _validate_ldap_timeout_seconds(cls, v: float) -> float:
        return max(1.0, min(30.0, v))

    # 不 import app.core.auth（避免循环依赖），直接对照角色字面量集合。
    @field_validator("LDAP_DEFAULT_ROLE")
    @classmethod
    def _validate_ldap_default_role(cls, v: str) -> str:
        value = str(v or "user").strip().lower()
        if value not in {"super_admin", "user", "reviewer", "operator", "viewer"}:
            raise ValueError("LDAP_DEFAULT_ROLE must be one of: super_admin, reviewer, user, operator, viewer.")
        return value

    # 数据保留策略（天）。0 = 关闭（默认，行为不变）；>0 时后台每 6 小时清理
    # 超龄上传文件及其成品（走 delete_file 全量清除 + 审计留痕）。
    DATA_RETENTION_DAYS: int = 0

    # 批量任务并发配置
    JOB_CONCURRENCY: int = 3  # Number of concurrent job items to process

    # 离线 License（Ed25519 签名校验，见 app/core/license.py）。默认关闭 =
    # 现有部署行为完全不变；开启后 License 缺失/过期/无效时，变更类 /api 请求
    # 由 LicenseEnforcementMiddleware 拒绝（403），席位数在创建用户时受限。
    LICENSE_ENFORCEMENT_ENABLED: bool = False
    LICENSE_FILE_PATH: str = ""  # 空 = DATA_DIR/license.json（license.py 内解析）
    LICENSE_RECHECK_INTERVAL_HOURS: float = 24.0
    LICENSE_EXPIRY_WARN_DAYS: int = 30
    LICENSE_GRACE_DAYS: int = 14

    @field_validator("LICENSE_RECHECK_INTERVAL_HOURS")
    @classmethod
    def _validate_license_recheck_interval_hours(cls, v: float) -> float:
        return max(1.0, min(168.0, v))

    @field_validator("LICENSE_EXPIRY_WARN_DAYS")
    @classmethod
    def _validate_license_expiry_warn_days(cls, v: int) -> int:
        return max(1, min(120, v))

    @field_validator("LICENSE_GRACE_DAYS")
    @classmethod
    def _validate_license_grace_days(cls, v: int) -> int:
        return max(0, min(90, v))

    @field_validator("DATA_RETENTION_DAYS")
    @classmethod
    def _validate_data_retention_days(cls, v: int) -> int:
        return max(0, min(3650, v))

    @field_validator("JOB_CONCURRENCY")
    @classmethod
    def _validate_job_concurrency(cls, v: int) -> int:
        return max(1, min(16, v))

    @field_validator("BATCH_RECOGNITION_PAGE_CONCURRENCY")
    @classmethod
    def _validate_batch_page_concurrency(cls, v: int) -> int:
        return max(1, min(8, v))

    @field_validator("BATCH_VISUAL_MERGE_PAGE_CONCURRENCY")
    @classmethod
    def _validate_batch_visual_merge_page_concurrency(cls, v: int) -> int:
        return max(1, min(4, v))

    @field_validator("GPU_SATURATION_RATIO")
    @classmethod
    def _validate_gpu_saturation_ratio(cls, v: float) -> float:
        return max(0.5, min(0.99, v))

    @field_validator("OCR_MAX_NEW_TOKENS")
    @classmethod
    def _validate_ocr_max_new_tokens(cls, v: int) -> int:
        return max(128, min(8192, v))

    @field_validator("OCR_MAX_IMAGE_SIDE")
    @classmethod
    def _validate_ocr_max_image_side(cls, v: int) -> int:
        return max(640, min(4096, v))

    @field_validator("LOCATE_ANYTHING_MAX_IMAGE_SIDE")
    @classmethod
    def _validate_locate_anything_max_image_side(cls, v: int) -> int:
        return max(640, min(4096, v))

    @field_validator("PDF_TEXT_LAYER_MIN_CHARS")
    @classmethod
    def _validate_pdf_text_layer_min_chars(cls, v: int) -> int:
        return max(0, min(10_000, v))

    @field_validator("OCR_TEXT_BLOCK_CACHE_TTL_SEC")
    @classmethod
    def _validate_ocr_text_block_cache_ttl_sec(cls, v: float) -> float:
        return max(0.0, min(3600.0, v))

    @field_validator("OCR_TEXT_BLOCK_CACHE_MAX_ITEMS")
    @classmethod
    def _validate_ocr_text_block_cache_max_items(cls, v: int) -> int:
        return max(0, min(4096, v))

    @field_validator("HAS_NER_CACHE_TTL_SEC")
    @classmethod
    def _validate_has_ner_cache_ttl_sec(cls, v: float) -> float:
        return max(0.0, min(3600.0, v))

    @field_validator("HAS_NER_MAX_TOKENS")
    @classmethod
    def _validate_has_ner_max_tokens(cls, v: int) -> int:
        return max(128, min(32768, v))

    @field_validator("HAS_NER_CONTEXT_TOKENS")
    @classmethod
    def _validate_has_ner_context_tokens(cls, v: int) -> int:
        return max(512, min(262_144, v))

    @field_validator("HAS_NER_MAX_TYPES_PER_REQUEST")
    @classmethod
    def _validate_has_ner_max_types_per_request(cls, v: int) -> int:
        return max(1, min(96, v))

    @field_validator("HAS_NER_SINGLE_PASS_MAX_TYPES")
    @classmethod
    def _validate_has_ner_single_pass_max_types(cls, v: int) -> int:
        return max(1, min(128, v))

    @field_validator("HAS_NER_SINGLE_PASS_MAX_TEXT_CHARS")
    @classmethod
    def _validate_has_ner_single_pass_max_text_chars(cls, v: int) -> int:
        return max(128, min(16384, v))

    @field_validator("HAS_NER_MAX_PARALLEL_REQUESTS")
    @classmethod
    def _validate_has_ner_max_parallel_requests(cls, v: int) -> int:
        return max(1, min(8, v))

    @field_validator("HAS_NER_GLOBAL_MAX_INFLIGHT")
    @classmethod
    def _validate_has_ner_global_max_inflight(cls, v: int) -> int:
        return max(1, min(12, v))

    @field_validator("HAS_NER_CUSTOM_MAX_TYPES_PER_REQUEST")
    @classmethod
    def _validate_has_ner_custom_max_types_per_request(cls, v: int) -> int:
        return max(1, min(16, v))

    @field_validator("HAS_NER_TYPE_BATCH_TARGET_TOKENS")
    @classmethod
    def _validate_has_ner_type_batch_target_tokens(cls, v: int) -> int:
        return max(128, min(8192, v))

    @field_validator("HAS_NER_CACHE_MAX_ITEMS")
    @classmethod
    def _validate_has_ner_cache_max_items(cls, v: int) -> int:
        return max(0, min(4096, v))

    @field_validator("HAS_VISION_MAX_TEXT_CHARS")
    @classmethod
    def _validate_has_vision_max_text_chars(cls, v: int) -> int:
        return max(1_000, min(1_000_000, v))

    @field_validator("HAS_VISION_MAX_BLOCK_CHARS")
    @classmethod
    def _validate_has_vision_max_block_chars(cls, v: int) -> int:
        return max(0, min(100_000, v))

    @field_validator("HAS_VISION_MIN_TEXT_CHARS_FOR_NER")
    @classmethod
    def _validate_has_vision_min_text_chars_for_ner(cls, v: int) -> int:
        return max(1, min(10_000, v))

    # 后台工作循环 / 清理
    WORKER_LOOP_INTERVAL_SEC: float = 2.0
    ORPHAN_CLEANUP_AGE_SEC: int = 3600

    REDACTION_PDF_JPEG_QUALITY: int = 88
    PDF_PAGE_IMAGE_CACHE_PAGES: int = 32
    PDF_PAGE_TEXT_BLOCK_CACHE_PAGES: int = 64

    @field_validator("REDACTION_PDF_JPEG_QUALITY")
    @classmethod
    def _validate_redaction_pdf_jpeg_quality(cls, v: int) -> int:
        return max(60, min(95, v))

    @field_validator("PDF_PAGE_IMAGE_CACHE_PAGES")
    @classmethod
    def _validate_pdf_page_image_cache_pages(cls, v: int) -> int:
        return max(0, min(256, v))

    @field_validator("PDF_PAGE_TEXT_BLOCK_CACHE_PAGES")
    @classmethod
    def _validate_pdf_page_text_block_cache_pages(cls, v: int) -> int:
        return max(0, min(512, v))

    # 匿名化配置
    DEFAULT_REPLACEMENT_MODE: Literal["smart", "mask", "custom"] = "smart"

    # 病毒扫描（需 ClamAV daemon 在 CLAMD_HOST:CLAMD_PORT 监听）
    VIRUS_SCAN_ENABLED: bool = False

    # 可信代理 IP / CIDR（只有 request.client.host 匹配时才信任 X-Forwarded-For）。
    # 默认只信 loopback 与 172.16.0.0/12（docker compose 网桥网段，保证容器内
    # nginx 反代链路可用）；不再默认信任 10.0.0.0/8 与 192.168.0.0/16，防止同
    # 内网直连客户端伪造 X-Forwarded-For 绕过按 IP 的登录限速。反向代理部署在
    # 10.x / 192.168.x 网段时需通过环境变量显式配置 TRUSTED_PROXIES。
    TRUSTED_PROXIES: list[str] = [
        "127.0.0.1",
        "::1",
        "172.16.0.0/12",
    ]

    # 结构化数据库连接主机白名单（SSRF 防护）。None = 不限制（默认，保持
    # 本地工具连接用户自有数据库的正当功能）；设置后，非 sqlite 连接的 host
    # 必须命中列表中的精确主机名或 IP / CIDR 网段，否则拒绝建立连接。
    STRUCTURED_DB_HOST_ALLOWLIST: list[str] | None = None

    # 结构化日志（默认生产 JSON，DEBUG 文本）
    LOG_JSON: bool = True

    @field_validator("DEBUG", mode="before")
    @classmethod
    def _coerce_debug_bool(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"debug", "dev", "development"}:
                return True
        return value

    @model_validator(mode="after")
    def _derive_paths_and_secrets(self) -> "Settings":
        """Derive repo-local paths after environment overrides are parsed."""
        self.DATA_DIR = _resolve_local_path(self.DATA_DIR)
        self.UPLOAD_DIR = _resolve_local_path(self.UPLOAD_DIR)
        self.OUTPUT_DIR = _resolve_local_path(self.OUTPUT_DIR)
        self.HAS_MODEL_PATH = _resolve_local_path(self.HAS_MODEL_PATH)

        d = self.DATA_DIR
        if not self.FILE_STORE_PATH:
            self.FILE_STORE_PATH = os.path.join(d, "file_store.json")
        else:
            self.FILE_STORE_PATH = _resolve_local_path(self.FILE_STORE_PATH)
        if not self.JOB_DB_PATH:
            self.JOB_DB_PATH = os.path.join(d, "jobs.sqlite3")
        else:
            self.JOB_DB_PATH = _resolve_local_path(self.JOB_DB_PATH)
        if not self.PIPELINE_STORE_PATH:
            self.PIPELINE_STORE_PATH = os.path.join(d, "pipelines.json")
        else:
            self.PIPELINE_STORE_PATH = _resolve_local_path(self.PIPELINE_STORE_PATH)
        if not self.PRESET_STORE_PATH:
            self.PRESET_STORE_PATH = os.path.join(d, "presets.json")
        else:
            self.PRESET_STORE_PATH = _resolve_local_path(self.PRESET_STORE_PATH)
        if not self.ENTITY_TYPES_STORE_PATH:
            self.ENTITY_TYPES_STORE_PATH = os.path.join(d, "entity_types.json")
        else:
            self.ENTITY_TYPES_STORE_PATH = _resolve_local_path(self.ENTITY_TYPES_STORE_PATH)
        if not self.MODEL_CONFIG_PATH:
            self.MODEL_CONFIG_PATH = os.path.join(d, "model_config.json")
        else:
            self.MODEL_CONFIG_PATH = _resolve_local_path(self.MODEL_CONFIG_PATH)
        # JWT 密钥：优先环境变量，否则从 data 目录加载或首次生成并持久化
        if not self.JWT_SECRET_KEY:
            env_key = os.environ.get("JWT_SECRET_KEY", "") or os.environ.get("LEGAL_REDACTION_JWT_SECRET", "")
            if env_key:
                self.JWT_SECRET_KEY = env_key
            else:
                self.JWT_SECRET_KEY = _load_or_create_jwt_secret(d)
        return self

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()


settings = get_settings()


def get_has_chat_base_url() -> str:
    """Return the OpenAI-compatible base URL used by HaS Text."""
    s = get_settings()
    if s.HAS_TEXT_RUNTIME.strip().lower() == "vllm":
        return _resolve_wsl_localhost_url(s.HAS_TEXT_VLLM_BASE_URL)
    if s.HAS_BASE_URL:
        return _resolve_wsl_localhost_url(s.HAS_BASE_URL)
    if s.HAS_LLAMACPP_BASE_URL:
        return _resolve_wsl_localhost_url(s.HAS_LLAMACPP_BASE_URL)
    from app.core.ner_runtime import load_ner_runtime
    rt = load_ner_runtime()
    if rt is not None:
        return _resolve_wsl_localhost_url(rt.llamacpp_base_url)
    return _resolve_wsl_localhost_url("http://127.0.0.1:8080/v1")


def get_has_health_check_url() -> str:
    """Return the HaS Text health check URL."""
    return f"{get_has_chat_base_url()}/models"


def get_has_display_name() -> str:
    """Return the display name used by /health/services."""
    import os
    custom = (os.environ.get("HAS_NER_DISPLAY_NAME") or "").strip()
    if custom:
        return custom
    s = get_settings()
    if s.HAS_TEXT_MODEL_NAME:
        return s.HAS_TEXT_MODEL_NAME
    return "HaS-Text-0209-Q4"
