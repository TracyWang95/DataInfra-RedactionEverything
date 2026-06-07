"""
Redaction configuration, request/response, preview, compare,
report, and version-history models.
"""
from typing import Literal

from pydantic import BaseModel, Field

from .common import ReplacementMode
from .entity_schemas import BoundingBox, Entity

__all__ = [
    "RedactionConfig",
    "RedactionRequest",
    "RedactionResult",
    "CompareData",
    "PreviewEntityMapRequest",
    "PreviewEntityMapResponse",
    "PreviewImageRequest",
    "PreviewImageResponse",
    "NERRequest",
    "VisionDetectRequest",
    "RedactionReport",
    "RedactionVersionsResponse",
]


class RedactionConfig(BaseModel):
    """Redaction configuration."""
    replacement_mode: ReplacementMode = Field(default=ReplacementMode.SMART)
    entity_types: list[str] = Field(
        default=["PERSON", "PHONE", "ID_CARD"]
    )
    custom_entity_types: list[str] = Field(
        default_factory=list, description="启用的自定义实体类型ID列表"
    )
    custom_replacements: dict[str, str] = Field(default_factory=dict)
    # Block-level image redaction is independent from text replacement_mode.
    image_redaction_method: Literal["mosaic", "blur", "fill"] | None = Field(
        default="mosaic",
        description="图片类：马赛克、高斯模糊、纯色填充；未传时图片默认按 mosaic/75 处理",
    )
    image_redaction_strength: int = Field(
        default=75,
        ge=1,
        le=100,
        description="Relative strength for image redaction.",
    )
    image_fill_color: str = Field(
        default="#000000",
        description="Fill color for fill mode (#RRGGBB).",
    )


class RedactionRequest(BaseModel):
    """Redaction request."""
    file_id: str = Field(..., description="文件ID")
    entities: list[Entity] = Field(default_factory=list, description="Entities to redact")
    bounding_boxes: list[BoundingBox] = Field(default_factory=list, description="Image regions to redact")
    config: RedactionConfig = Field(default_factory=RedactionConfig)


class PreviewEntityMapRequest(BaseModel):
    """仅预览替换映射（不落盘）"""
    entities: list[Entity] = Field(default_factory=list)
    config: RedactionConfig = Field(default_factory=RedactionConfig)


class PreviewEntityMapResponse(BaseModel):
    entity_map: dict[str, str] = Field(default_factory=dict, description="与 execute 一致的原文→替换表")


class PreviewImageRequest(BaseModel):
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    config: RedactionConfig = Field(default_factory=RedactionConfig)


class PreviewImageResponse(BaseModel):
    file_id: str
    page: int
    image_base64: str


class NERRequest(BaseModel):
    """NER识别请求"""
    entity_types: list[str] = Field(
        default=["PERSON", "PHONE", "ID_CARD", "ORG", "CASE_NUMBER"],
        description="要识别的内置实体类型"
    )
    custom_entity_type_ids: list[str] = Field(
        default_factory=list,
        description="要识别的自定义实体类型ID列表"
    )


class RedactionResult(BaseModel):
    """Redaction result."""
    file_id: str
    output_file_id: str
    redacted_count: int
    entity_map: dict[str, str] = Field(default_factory=dict, description="Entity replacement map")
    download_url: str
    output_path: str | None = Field(default=None, exclude=True)


class CompareData(BaseModel):
    """对比数据"""
    file_id: str
    original_content: str
    redacted_content: str
    changes: list[dict] = Field(default_factory=list)


class VisionDetectRequest(BaseModel):
    """Vision detection request."""
    selected_ocr_has_types: list[str] | None = None
    selected_visual_feature_types: list[str] | None = None


class RedactionReport(BaseModel):
    """Redaction quality report."""
    file_id: str
    filename: str
    total_entities: int
    redacted_entities: int
    entity_type_distribution: dict[str, int] = Field(default_factory=dict, description="Entity counts by type")
    confidence_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="置信度分布：high(>0.8), medium(0.5-0.8), low(<0.5)"
    )
    source_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Detection source distribution: ocr_has, visual_features, manual.",
    )
    coverage_rate: float = Field(default=0.0, description="匿名化覆盖率（已匿名化/总识别）")
    redaction_mode: str = ""
    created_at: str = ""


class RedactionVersionsResponse(BaseModel):
    """Redaction version-history response."""
    file_id: str
    versions: list[dict] = Field(default_factory=list)
    total: int = 0

