"""
应用配置管理
支持从环境变量和 .env 文件加载配置
"""
import json
import logging
import os
import secrets
from pathlib import Path
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Literal
from functools import lru_cache


BACKEND_DIR = Path(__file__).resolve().parents[2]


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
            with open(secret_path, "r") as f:
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
        # 文本类
        ".doc", ".docx", ".txt", ".rtf", ".md", ".html", ".htm",
        # PDF
        ".pdf",
        # 图像类
        ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff",
    ]

    # HaS Image YOLO 微服务（独立进程，端口 8081，与 PaddleOCR 8082 同级）
    HAS_IMAGE_BASE_URL: str = "http://127.0.0.1:8081"
    HAS_IMAGE_TIMEOUT: float = 120.0
    HAS_IMAGE_CONF: float = 0.25

    # 本地持久化（空串 = 跟随 DATA_DIR 自动派生，见 model_validator）
    FILE_STORE_PATH: str = ""
    JOB_DB_PATH: str = ""
    PIPELINE_STORE_PATH: str = ""
    PRESET_STORE_PATH: str = ""
    ENTITY_TYPES_STORE_PATH: str = ""
    MODEL_CONFIG_PATH: str = ""

    # PaddleOCR-VL 微服务配置（独立进程，端口8082）
    OCR_BASE_URL: str = "http://127.0.0.1:8082"
    # VL 推理常 >120s（大图/CPU/显卡繁忙时）；可用环境变量 OCR_TIMEOUT 覆盖
    OCR_TIMEOUT: float = 360.0
    # 主后端探测 OCR /health 的超时（秒）；首启加载模型较慢，过短会误显示「离线」
    OCR_HEALTH_PROBE_TIMEOUT: float = 45.0
    # True: OCR 服务离线时直接报错而非尝试 CPU 回退（防止超慢推理阻塞队列）
    OCR_REQUIRE_GPU: bool = False

    # 文本 NER：HaS Text 0209 Q4_K_M（llama-server，默认 8080/v1，OpenAI 兼容）
    HAS_LLAMACPP_BASE_URL: str = "http://127.0.0.1:8080/v1"
    HAS_MODEL_PATH: str = "./models/has/HaS_Text_0209_0.6B_Q4_K_M.gguf"
    HAS_TIMEOUT: float = 120.0

    # 兼容旧环境变量 HAS_BASE_URL
    HAS_BASE_URL: Optional[str] = None

    # 认证配置（JWT_SECRET_KEY 若未通过环境变量指定，则自动持久化到 data 目录）
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 hours
    LOCAL_PASSWORD_HASH: str = ""  # bcrypt hash, set via setup endpoint
    AUTH_ENABLED: bool = os.environ.get("AUTH_ENABLED", "false").lower() == "true"

    # 批量任务并发配置
    JOB_CONCURRENCY: int = 1  # Number of concurrent job items to process

    # 后台工作循环 / 清理
    WORKER_LOOP_INTERVAL_SEC: float = 2.0
    ORPHAN_CLEANUP_AGE_SEC: int = 3600

    # 匿名化配置
    DEFAULT_REPLACEMENT_MODE: Literal["smart", "mask", "custom"] = "smart"

    # 文件加密（默认关闭；启用后上传文件 AES-256-GCM 加密落盘）
    FILE_ENCRYPTION_ENABLED: bool = False

    # 病毒扫描（需 ClamAV daemon 在 CLAMD_HOST:CLAMD_PORT 监听）
    VIRUS_SCAN_ENABLED: bool = False

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
        """在所有字段（含环境变量覆盖）解析完毕后，派生依赖 DATA_DIR 的路径。"""
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
    )


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()


def get_has_chat_base_url() -> str:
    """NER 使用的 OpenAI 兼容 API 根路径（…/v1）。"""
    from app.core.ner_runtime import load_ner_runtime
    rt = load_ner_runtime()
    if rt is not None:
        return rt.llamacpp_base_url.rstrip("/")
    s = get_settings()
    if s.HAS_BASE_URL:
        return s.HAS_BASE_URL.rstrip("/")
    return s.HAS_LLAMACPP_BASE_URL.rstrip("/")


def get_has_health_check_url() -> str:
    """健康检查 URL（llama.cpp /v1/models）。"""
    return f"{get_has_chat_base_url()}/models"


def get_has_display_name() -> str:
    """侧栏 /health/services 中文本 NER 展示名。"""
    import os
    custom = (os.environ.get("HAS_NER_DISPLAY_NAME") or "").strip()
    if custom:
        return custom
    return "HaS-Text-0209-Q4"
