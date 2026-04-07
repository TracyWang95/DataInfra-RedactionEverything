# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
Redaction configuration, request/response, preview, compare,
report, and version-history models.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

from .common import ReplacementMode
from .entity_schemas import Entity, BoundingBox

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
    """匿名化配置"""
    replacement_mode: ReplacementMode = Field(default=ReplacementMode.SMART)
    entity_types: list[str] = Field(
        default=["PERSON", "PHONE", "ID_CARD"]
    )
    custom_entity_types: list[str] = Field(
        default_factory=list, description="启用的自定义实体类型ID列表"
    )
    custom_replacements: dict[str, str] = Field(default_factory=dict)
    # 图片 / 扫描件块级匿名化（与 HaS Image 文档一致：mosaic / blur / fill），与文本 replacement_mode 独立
    image_redaction_method: Optional[Literal["mosaic", "blur", "fill"]] = Field(
        default=None,
        description="图片类：马赛克、高斯模糊、纯色填充；未传时图片仍按 fill 处理",
    )
    image_redaction_strength: int = Field(
        default=25,
        ge=1,
        le=100,
        description="马赛克块尺寸 / 模糊半径的相对强度（1–100）",
    )
    image_fill_color: str = Field(
        default="#000000",
        description="fill 模式填充色（#RRGGBB）",
    )


class RedactionRequest(BaseModel):
    """匿名化请求"""
    file_id: str = Field(..., description="文件ID")
    entities: list[Entity] = Field(default_factory=list, description="要匿名化的实体列表")
    bounding_boxes: list[BoundingBox] = Field(default_factory=list, description="要匿名化的图片区域")
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
    """匿名化结果"""
    file_id: str
    output_file_id: str
    redacted_count: int
    entity_map: dict[str, str] = Field(default_factory=dict, description="实体映射表")
    download_url: str
    output_path: Optional[str] = Field(default=None, exclude=True)


class CompareData(BaseModel):
    """对比数据"""
    file_id: str
    original_content: str
    redacted_content: str
    changes: list[dict] = Field(default_factory=list)


class VisionDetectRequest(BaseModel):
    """视觉识别请求体"""
    selected_ocr_has_types: Optional[List[str]] = None
    selected_has_image_types: Optional[List[str]] = None


class RedactionReport(BaseModel):
    """匿名化质量报告"""
    file_id: str
    filename: str
    total_entities: int
    redacted_entities: int
    entity_type_distribution: dict[str, int] = Field(default_factory=dict, description="各类型实体数量")
    confidence_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="置信度分布：high(>0.8), medium(0.5-0.8), low(<0.5)"
    )
    source_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="来源分布：llm, regex, manual, has"
    )
    coverage_rate: float = Field(default=0.0, description="匿名化覆盖率（已匿名化/总识别）")
    redaction_mode: str = ""
    created_at: str = ""


class RedactionVersionsResponse(BaseModel):
    """匿名化版本历史响应"""
    file_id: str
    versions: list[dict] = Field(default_factory=list)
    total: int = 0
