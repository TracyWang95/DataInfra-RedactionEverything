"""
Entity and bounding-box models, custom entity type definitions,
and entity-type list responses.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime

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


# ============ 自定义实体类型 ============

class CustomEntityType(BaseModel):
    """自定义实体类型定义"""
    id: str = Field(..., description="类型唯一ID")
    name: str = Field(..., description="类型名称，如'涉案金额'")
    description: str = Field(default="", description="语义描述，用于AI理解")
    examples: list[str] = Field(default_factory=list, description="示例文本，帮助AI识别")
    color: str = Field(default="#6B7280", description="显示颜色")
    replacement_template: str = Field(default="[{name}]", description="替换模板")
    enabled: bool = Field(default=True, description="是否启用")
    created_at: datetime = Field(default_factory=datetime.now)


class CustomEntityTypeCreate(BaseModel):
    """创建自定义实体类型请求"""
    name: str = Field(..., description="类型名称")
    description: str = Field(..., description="语义描述，用于AI理解匹配")
    examples: list[str] = Field(default_factory=list, description="示例文本")
    color: str = Field(default="#6B7280", description="显示颜色")
    replacement_template: str = Field(default="[{name}]", description="替换模板")


class CustomEntityTypeUpdate(BaseModel):
    """更新自定义实体类型请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    examples: Optional[list[str]] = None
    color: Optional[str] = None
    replacement_template: Optional[str] = None
    enabled: Optional[bool] = None


# ============ 请求模型 ============

class Entity(BaseModel):
    """识别到的实体"""
    id: str = Field(..., description="实体唯一ID")
    text: str = Field(..., description="原始文本")
    type: str = Field(..., description="实体类型（内置类型或自定义类型ID）")
    start: int = Field(..., description="起始位置")
    end: int = Field(..., description="结束位置")
    page: int = Field(default=1, description="所在页码")
    confidence: float = Field(default=1.0, description="置信度")
    source: Optional[Literal["regex", "llm", "manual", "has"]] = Field(
        default=None, description="实体来源"
    )
    coref_id: Optional[str] = Field(None, description="指代消解ID")
    replacement: Optional[str] = Field(None, description="替换文本")
    selected: bool = Field(default=True, description="是否选中进行匿名化")
    custom_type_id: Optional[str] = Field(None, description="自定义类型ID（如果是自定义类型）")


class BoundingBox(BaseModel):
    """图片中的敏感区域边界框"""
    id: str = Field(..., description="区域唯一ID")
    x: float = Field(..., description="左上角 X 坐标")
    y: float = Field(..., description="左上角 Y 坐标")
    width: float = Field(..., description="宽度")
    height: float = Field(..., description="高度")
    page: int = Field(default=1, description="所在页码")
    type: str = Field(..., description="实体类型")
    text: Optional[str] = Field(None, description="识别到的文本")
    selected: bool = Field(default=True, description="是否选中进行匿名化")
    source: Optional[Literal["ocr_has", "has_image", "manual"]] = Field(
        default=None, description="来源: ocr_has=OCR+HaS, has_image=HaS Image YOLO, manual=手动"
    )


# ============ 实体类型 / 匿名化端点响应 ============

class EntityTypeItem(BaseModel):
    """单个实体类型展示项"""
    value: str
    label: str
    color: str


class EntityTypeListResponse(BaseModel):
    """实体类型列表响应"""
    entity_types: list[EntityTypeItem]


class ReplacementModeItem(BaseModel):
    """单个替换模式展示项"""
    value: str
    label: str
    description: str


class ReplacementModeListResponse(BaseModel):
    """替换模式列表响应"""
    replacement_modes: list[ReplacementModeItem]
