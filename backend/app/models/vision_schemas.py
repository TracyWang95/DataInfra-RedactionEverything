"""
Vision (image/scanned-PDF) detection result models.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .entity_schemas import BoundingBox

__all__ = [
    "VisionResult",
    "HybridNERRequest",
]


class VisionResult(BaseModel):
    """视觉识别结果"""
    file_id: str
    page: int
    bounding_boxes: list[BoundingBox]
    warnings: list[str] = Field(default_factory=list)
    pipeline_status: dict[str, dict] = Field(default_factory=dict)
    # 诊断字段：前端不读，仅供 curl/性能排查（各阶段耗时与视觉缓存命中状态）。
    # 有真实运维价值（历次 5090/NPU 性能与缓存排查依赖），保留，勿删。
    duration_ms: dict[str, Any] = Field(default_factory=dict)
    cache_status: dict[str, Any] = Field(default_factory=dict)
    result_image: str | None = None  # 带检测框的图片 base64


class HybridNERRequest(BaseModel):
    """混合识别请求（HaS 固定为 NER）"""
    model_config = ConfigDict(extra="ignore")

    entity_type_ids: list[str] | None = Field(
        default=None,
        description="要识别的实体类型ID列表；None 表示沿用默认启用项，[] 表示本次不识别文本项",
    )
