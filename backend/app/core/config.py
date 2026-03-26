"""
应用配置管理
支持从环境变量和 .env 文件加载配置
"""
import os
from pydantic_settings import BaseSettings
from typing import Optional, Literal
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""
    
    # 应用基础配置
    APP_NAME: str = "DataShield 智能数据脱敏平台"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    
    # API 配置
    API_PREFIX: str = "/api/v1"
    
    # CORS 配置
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    
    # 文件上传配置
    UPLOAD_DIR: str = "./uploads"
    OUTPUT_DIR: str = "./outputs"
    DATA_DIR: str = "./data"
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    ALLOWED_EXTENSIONS: list[str] = [".doc", ".docx", ".pdf", ".jpg", ".jpeg", ".png"]
    
    # HaS Image YOLO 微服务（独立进程，端口 8081，与 PaddleOCR 8082 同级）
    HAS_IMAGE_BASE_URL: str = "http://127.0.0.1:8081"
    HAS_IMAGE_TIMEOUT: float = 120.0
    HAS_IMAGE_CONF: float = 0.25

    # 本地持久化
    FILE_STORE_PATH: str = os.path.join(DATA_DIR, "file_store.json")
    PIPELINE_STORE_PATH: str = os.path.join(DATA_DIR, "pipelines.json")
    PRESET_STORE_PATH: str = os.path.join(DATA_DIR, "presets.json")

    # PaddleOCR-VL 微服务配置（独立进程，端口8082）
    OCR_BASE_URL: str = "http://127.0.0.1:8082"
    # VL 推理常 >120s（大图/CPU/显卡繁忙时）；可用环境变量 OCR_TIMEOUT 覆盖
    OCR_TIMEOUT: float = 360.0
    # 主后端探测 OCR /health 的超时（秒）；首启加载模型较慢，过短会误显示「离线」
    OCR_HEALTH_PROBE_TIMEOUT: float = 45.0
    
    # 文本 NER：二选一
    # - llamacpp: HaS Text 0209 Q4_K_M（llama-server，默认 8080/v1，OpenAI 兼容，可不传 model）
    # - ollama:    本地 Ollama（默认 11434/v1），必须在 HAS_OLLAMA_MODEL 指定模型名，如 qwen3:8b
    HAS_NER_BACKEND: Literal["llamacpp", "ollama"] = "llamacpp"
    HAS_LLAMACPP_BASE_URL: str = "http://127.0.0.1:8080/v1"
    HAS_OLLAMA_BASE_URL: str = "http://127.0.0.1:11434/v1"
    HAS_OLLAMA_MODEL: str = "qwen3:8b"
    HAS_MODEL_PATH: str = "./models/has/HaS_Text_0209_0.6B_Q4_K_M.gguf"  # 仅文档/脚本引用；实际路径见 HAS_NER_GGUF / start_has.ps1
    HAS_TIMEOUT: float = 120.0

    # 兼容旧环境变量 HAS_BASE_URL：若设置则覆盖当前 backend 对应 URL（见 get_has_chat_base_url）
    HAS_BASE_URL: Optional[str] = None
    
    # 脱敏配置
    DEFAULT_REPLACEMENT_MODE: Literal["smart", "mask", "custom"] = "smart"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()


def is_ner_ollama() -> bool:
    """是否按 Ollama 协议调 NER。优先 data/ner_backend.json（前端设置），否则读环境变量。"""
    from app.core.ner_runtime import load_ner_runtime
    rt = load_ner_runtime()
    if rt is not None:
        return rt.backend == "ollama"
    s = get_settings()
    if s.HAS_NER_BACKEND == "ollama":
        return True
    if s.HAS_BASE_URL and "11434" in s.HAS_BASE_URL:
        return True
    return False


def get_has_chat_base_url() -> str:
    """NER 使用的 OpenAI 兼容 API 根路径（…/v1）。"""
    from app.core.ner_runtime import load_ner_runtime
    rt = load_ner_runtime()
    if rt is not None:
        if rt.backend == "ollama":
            return rt.ollama_base_url.rstrip("/")
        return rt.llamacpp_base_url.rstrip("/")
    s = get_settings()
    # 无 ner_backend.json 时：Ollama 模式优先 HAS_OLLAMA_BASE_URL，避免遗留 HAS_BASE_URL 指向 8080 与协议不一致
    if s.HAS_NER_BACKEND == "ollama":
        return s.HAS_OLLAMA_BASE_URL.rstrip("/")
    if s.HAS_BASE_URL:
        return s.HAS_BASE_URL.rstrip("/")
    return s.HAS_LLAMACPP_BASE_URL.rstrip("/")


def get_has_health_check_url() -> str:
    """健康检查 URL（llama.cpp 用 /v1/models；Ollama 用 /api/tags）。"""
    chat = get_has_chat_base_url()
    if is_ner_ollama():
        root = chat.replace("/v1", "").rstrip("/") or "http://127.0.0.1:11434"
        return f"{root}/api/tags"
    return f"{chat}/models"


def get_ollama_model() -> str:
    from app.core.ner_runtime import load_ner_runtime
    rt = load_ner_runtime()
    if rt is not None:
        return rt.ollama_model
    return get_settings().HAS_OLLAMA_MODEL


def get_has_display_name() -> str:
    """侧栏 /health/services 中文本 NER 展示名（与 HaS_Text_0209 GGUF 一致）。"""
    if is_ner_ollama():
        return get_ollama_model()
    import os

    custom = (os.environ.get("HAS_NER_DISPLAY_NAME") or "").strip()
    if custom:
        return custom
    return "HaS-Text-0209-Q4"
