"""
Model (LLM provider) configuration schemas.
"""
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Literal

__all__ = [
    "ModelConfig",
    "ModelConfigList",
]


class ModelConfig(BaseModel):
    """模型配置"""
    model_config = ConfigDict(protected_namespaces=())

    id: str = Field(..., description="配置ID")
    name: str = Field(..., description="配置名称")
    provider: Literal["local", "zhipu", "openai", "custom"] = Field(..., description="提供商类型")
    enabled: bool = Field(default=True, description="是否启用")

    # API 配置
    base_url: Optional[str] = Field(None, description="API 基础 URL（本地/自定义）")
    api_key: Optional[str] = Field(None, description="API Key（云端服务）")
    model_name: str = Field(..., description="模型名称")

    # 生成参数
    temperature: float = Field(default=0.8, ge=0, le=2)
    top_p: float = Field(default=0.6, ge=0, le=1)
    max_tokens: int = Field(default=4096, ge=1, le=32768)

    enable_thinking: bool = Field(default=False, description="保留字段")

    # 备注
    description: Optional[str] = Field(None, description="配置说明")


class ModelConfigList(BaseModel):
    """模型配置列表"""
    configs: list[ModelConfig]
    active_id: Optional[str] = Field(None, description="当前激活的配置ID")
