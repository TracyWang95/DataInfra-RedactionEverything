"""
Entity, bounding-box, custom type, and option-list schemas.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "Entity",
    "BoundingBox",
    "CustomEntityType",
    "CustomEntityTypeCreate",
    "CustomEntityTypeUpdate",
    "EntityTypeItem",
    "EntityTypeListResponse",
    "ReplacementModeItem",
    "ReplacementModeListResponse",
]


class CustomEntityType(BaseModel):
    """Custom text entity type."""

    id: str = Field(..., description="Stable type id")
    name: str = Field(..., description="Display name")
    description: str = Field(default="", description="Semantic description")
    examples: list[str] = Field(default_factory=list, description="Example text snippets")
    color: str = Field(default="#6B7280", description="Display color")
    replacement_template: str = Field(default="[{name}]", description="Replacement template")
    enabled: bool = Field(default=True, description="Whether this type is enabled")
    created_at: datetime = Field(default_factory=datetime.now)


class CustomEntityTypeCreate(BaseModel):
    """Request body for creating a custom text entity type."""

    name: str = Field(..., description="Display name")
    description: str = Field(..., description="Semantic description")
    examples: list[str] = Field(default_factory=list, description="Example text snippets")
    color: str = Field(default="#6B7280", description="Display color")
    replacement_template: str = Field(default="[{name}]", description="Replacement template")


class CustomEntityTypeUpdate(BaseModel):
    """Request body for updating a custom text entity type."""

    name: str | None = None
    description: str | None = None
    examples: list[str] | None = None
    color: str | None = None
    replacement_template: str | None = None
    enabled: bool | None = None


class Entity(BaseModel):
    """Recognized text entity."""

    id: str = Field(..., description="Entity id")
    text: str = Field(..., description="Original text")
    type: str = Field(..., description="Entity type id")
    start: int = Field(..., description="Start offset")
    end: int = Field(..., description="End offset")
    page: int = Field(default=1, description="Page number")
    confidence: float = Field(default=1.0, description="Recognition confidence")
    source: Literal["regex", "llm", "manual", "has"] | None = Field(
        default=None,
        description="Text entity source",
    )
    coref_id: str | None = Field(None, description="Coreference group id")
    replacement: str | None = Field(None, description="Replacement text")
    selected: bool = Field(default=True, description="Whether selected for redaction")
    custom_type_id: str | None = Field(None, description="Custom type id")


_LEGACY_BOX_SOURCE_MAP = {
    "has_image": "visual_features",
    "vlm": "visual_features",
}
_LEGACY_BOX_EVIDENCE_SOURCE_MAP = {
    "has_image_model": "visual_feature_model",
    "vlm_model": "visual_feature_model",
}


class BoundingBox(BaseModel):
    """Recognized image or document region."""

    id: str = Field(..., description="Region id")
    x: float = Field(..., description="Normalized left coordinate")
    y: float = Field(..., description="Normalized top coordinate")
    width: float = Field(..., description="Normalized width")
    height: float = Field(..., description="Normalized height")
    page: int = Field(default=1, description="Page number")
    type: str = Field(..., description="Region type id")
    text: str | None = Field(None, description="Recognized text or label")
    selected: bool = Field(default=True, description="Whether selected for redaction")
    confidence: float = Field(default=1.0, description="Detection confidence")
    source: Literal["ocr_has", "visual_features", "manual"] | None = Field(
        default=None,
        description="Detection source",
    )
    source_detail: str | None = Field(default=None, description="Detailed detector source")
    evidence_source: Literal[
        "ocr_has",
        "visual_feature_model",
        "local_fallback",
        "manual",
    ] | None = Field(default=None, description="Detector evidence source")
    warnings: list[str] = Field(default_factory=list, description="Region quality warnings")

    # Jobs processed by retired pipelines persisted boxes with legacy source
    # tags (YOLO "has_image", PaddleOCR-VL "vlm"). Those boxes round-trip back
    # through preview/redaction requests, so normalize them instead of 422-ing.
    @field_validator("source", mode="before")
    @classmethod
    def _normalize_legacy_source(cls, value: object) -> object:
        if isinstance(value, str):
            return _LEGACY_BOX_SOURCE_MAP.get(value, value)
        return value

    @field_validator("evidence_source", mode="before")
    @classmethod
    def _normalize_legacy_evidence_source(cls, value: object) -> object:
        if isinstance(value, str):
            return _LEGACY_BOX_EVIDENCE_SOURCE_MAP.get(value, value)
        return value


class EntityTypeItem(BaseModel):
    """Entity type option item."""

    value: str
    label: str
    color: str


class EntityTypeListResponse(BaseModel):
    """Entity type option response."""

    entity_types: list[EntityTypeItem]


class ReplacementModeItem(BaseModel):
    """Replacement mode option item."""

    value: str
    label: str
    description: str


class ReplacementModeListResponse(BaseModel):
    """Replacement mode option response."""

    replacement_modes: list[ReplacementModeItem]
