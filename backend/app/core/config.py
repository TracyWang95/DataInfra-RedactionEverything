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
    
    # GLM API 配置（仅本地 llama-server）
    GLM_LOCAL_BASE_URL: str = "http://localhost:8081"  # 本地 llama-server 端口
    GLM_LOCAL_MODEL: str = "glm"  # llama-server 的 model 名称
    
    # GLM 生成参数（视觉识别）
    GLM_TEMPERATURE: float = 0.8
    GLM_TOP_P: float = 0.6
    GLM_TOP_K: int = 2
    GLM_REPEAT_PENALTY: float = 1.1
    # RTX 4090：默认 16K，如需更快可降到 4096/8192
    GLM_MAX_TOKENS: int = 4096

    # 本地持久化
    FILE_STORE_PATH: str = os.path.join(DATA_DIR, "file_store.json")
    PIPELINE_STORE_PATH: str = os.path.join(DATA_DIR, "pipelines.json")

    # PaddleOCR-VL 微服务配置（独立进程，端口8082）
    OCR_BASE_URL: str = "http://127.0.0.1:8082"
    OCR_TIMEOUT: float = 120.0  # OCR推理超时
    
    # HaS 本地模型配置（主力文本NER引擎）
    HAS_BASE_URL: str = "http://127.0.0.1:11434/v1"  # Ollama 的 OpenAI 兼容接口，注意这里通常不需要再拼接 chat/completions 时的多余 v1，或者根据代理环境变化
    HAS_MODEL_NAME: str = "qwen3:8b"            # 用户指定的 Ollama 模型
    HAS_MODEL_PATH: str = "./models/has/has_4.0_0.6B.gguf"  
    HAS_TIMEOUT: float = 120.0  # 超时时间
    
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
