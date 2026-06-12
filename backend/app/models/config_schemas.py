"""Model runtime configuration schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ModelConfig",
    "ModelConfigList",
    "ModelConfigPreset",
    "ModelConfigPresetList",
    "ModelTaskType",
]

ModelTaskType = Literal["text_ner", "ocr", "visual_feature"]


class ModelConfig(BaseModel):
    """Runtime endpoint used by one model task slot."""

    model_config = ConfigDict(protected_namespaces=())

    id: str = Field(..., description="Stable config id")
    name: str = Field(..., description="Display name")
    provider: Literal["local", "openai", "custom"] = Field(..., description="Provider type")
    task_type: ModelTaskType = Field(default="visual_feature", description="Task slot")
    enabled: bool = Field(default=True, description="Whether this config can be selected")

    base_url: str | None = Field(None, description="HTTP API base URL")
    api_key: str | None = Field(None, description="Optional API key")
    model_name: str = Field(..., description="Model identifier")

    temperature: float = Field(default=0.8, ge=0, le=2)
    top_p: float = Field(default=0.6, ge=0, le=1)
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    enable_thinking: bool = Field(default=False, description="Provider thinking switch")

    description: str | None = Field(None, description="Operator notes")


class ModelConfigList(BaseModel):
    """Runtime endpoint list and the active model per task slot."""

    configs: list[ModelConfig]
    active_id: str | None = Field(None, description="Legacy active visual feature config id")
    active_by_task: dict[str, str] = Field(default_factory=dict, description="Active config id by task")
    preset_id: str | None = Field(default=None, description="Last applied preset id")


class ModelConfigPreset(BaseModel):
    """Predefined model selection preset."""

    id: str
    name: str
    description: str
    active_by_task: dict[str, str]
    recommended_chips: list[str] = Field(default_factory=list)


class ModelConfigPresetList(BaseModel):
    """Available predefined model selection presets."""

    presets: list[ModelConfigPreset]
