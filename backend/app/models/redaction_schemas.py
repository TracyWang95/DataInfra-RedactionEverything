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
        default_factory=list, description="鍚敤鐨勮嚜瀹氫箟瀹炰綋绫诲瀷ID鍒楄〃"
    )
    custom_replacements: dict[str, str] = Field(default_factory=dict)
    # Block-level image redaction is independent from text replacement_mode.
    image_redaction_method: Literal["mosaic", "blur", "fill"] | None = Field(
        default="mosaic",
        description="鍥剧墖绫伙細椹禌鍏嬨€侀珮鏂ā绯娿€佺函鑹插～鍏咃紱鏈紶鏃跺浘鐗囬粯璁ゆ寜 mosaic/75 澶勭悊",
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
    """浠呴瑙堟浛鎹㈡槧灏勶紙涓嶈惤鐩橈級"""
    entities: list[Entity] = Field(default_factory=list)
    config: RedactionConfig = Field(default_factory=RedactionConfig)


class PreviewEntityMapResponse(BaseModel):
    entity_map: dict[str, str] = Field(default_factory=dict, description="涓?execute 涓€鑷寸殑鍘熸枃鈫掓浛鎹㈣〃")


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
        description="瑕佽瘑鍒殑鍐呯疆瀹炰綋绫诲瀷"
    )
    custom_entity_type_ids: list[str] = Field(
        default_factory=list,
        description="瑕佽瘑鍒殑鑷畾涔夊疄浣撶被鍨婭D鍒楄〃"
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
        description="缃俊搴﹀垎甯冿細high(>0.8), medium(0.5-0.8), low(<0.5)"
    )
    source_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Detection source distribution: ocr_has, visual_features, manual.",
    )
    coverage_rate: float = Field(default=0.0, description="鍖垮悕鍖栬鐩栫巼锛堝凡鍖垮悕鍖?鎬昏瘑鍒級")
    redaction_mode: str = ""
    created_at: str = ""


class RedactionVersionsResponse(BaseModel):
    """Redaction version-history response."""
    file_id: str
    versions: list[dict] = Field(default_factory=list)
    total: int = 0

