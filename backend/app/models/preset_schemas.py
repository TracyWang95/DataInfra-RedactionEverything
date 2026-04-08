"""
Preset (batch-wizard configuration template) schemas.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

__all__ = [
    "PresetKind",
    "PresetPayload",
    "PresetCreate",
    "PresetUpdate",
    "PresetOut",
    "PresetsListResponse",
    "PresetImportRequest",
]

PresetKind = Literal["text", "vision", "full"]


class PresetPayload(BaseModel):
    """与前端 BatchWizardPersistedConfig 对齐的字段"""

    name: str = Field(..., min_length=1, max_length=200)
    kind: PresetKind = Field(
        default="full",
        description="text=仅文本链；vision=仅视觉链；full=文本+图像（兼容旧数据）",
    )
    selectedEntityTypeIds: List[str] = Field(default_factory=list)
    ocrHasTypes: List[str] = Field(default_factory=list)
    hasImageTypes: List[str] = Field(default_factory=list)
    replacementMode: Literal["structured", "smart", "mask"] = "structured"


class PresetCreate(PresetPayload):
    pass


class PresetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: PresetKind | None = None
    selectedEntityTypeIds: List[str] | None = None
    ocrHasTypes: List[str] | None = None
    hasImageTypes: List[str] | None = None
    replacementMode: Literal["structured", "smart", "mask"] | None = None


class PresetOut(PresetPayload):
    id: str
    created_at: str
    updated_at: str


class PresetsListResponse(BaseModel):
    presets: List[PresetOut]
    total: int
    page: int = 1
    page_size: int = 50


class PresetImportRequest(BaseModel):
    presets: list
    merge: bool = False  # True=merge with existing, False=replace all
