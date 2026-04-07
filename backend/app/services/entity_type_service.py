"""
实体类型管理 — 业务逻辑层
基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》国家标准设计
"""

from __future__ import annotations

import os as _os
import re
import uuid
from typing import Dict, List, Optional

from pydantic import BaseModel, Field
from enum import Enum

from app.core.persistence import load_json, save_json
from app.core.config import settings


# ── 数据模型 ──────────────────────────────────────────────

class IdentifierCategory(str, Enum):
    """标识符类别 - 基于 GB/T 37964-2019 第3.6-3.9节"""
    DIRECT = "direct"
    QUASI = "quasi"
    SENSITIVE = "sensitive"
    OTHER = "other"


class EntityTypeConfig(BaseModel):
    """实体类型配置 — 遵循 GB/T 37964-2019 标识符分类体系"""
    id: str = Field(..., description="唯一ID")
    name: str = Field(..., description="显示名称")
    category: IdentifierCategory = Field(
        default=IdentifierCategory.QUASI,
        description="标识符类别（GB/T 37964-2019）：direct=直接标识符, quasi=准标识符, sensitive=敏感属性",
    )
    description: Optional[str] = Field(None, description="语义描述，用于指导LLM识别")
    examples: List[str] = Field(default_factory=list, description="示例文本")
    color: str = Field(default="#6B7280", description="前端显示颜色")
    regex_pattern: Optional[str] = Field(None, description="正则表达式（优先使用）")
    use_llm: bool = Field(default=True, description="是否使用LLM识别（无正则时必须为True）")
    enabled: bool = Field(default=True, description="是否启用")
    order: int = Field(default=100, description="排序权重")
    tag_template: Optional[str] = Field(None, description="结构化标签模板，如 <组织[{index}].企业.完整名称>")
    risk_level: int = Field(default=2, description="重标识风险等级 1-5，参考 GB/T 37964-2019 第4.3节")


class EntityTypesResponse(BaseModel):
    """实体类型列表响应"""
    custom_types: List[EntityTypeConfig]
    total: int
    page: int = 1
    page_size: int = 50


class CreateEntityTypeRequest(BaseModel):
    """创建实体类型请求"""
    name: str
    description: Optional[str] = None
    examples: List[str] = []
    color: str = "#6B7280"
    regex_pattern: Optional[str] = None
    use_llm: bool = True
    tag_template: Optional[str] = None


class UpdateEntityTypeRequest(BaseModel):
    """更新实体类型请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    examples: Optional[List[str]] = None
    color: Optional[str] = None
    regex_pattern: Optional[str] = None
    use_llm: Optional[bool] = None
    enabled: Optional[bool] = None
    order: Optional[int] = None
    tag_template: Optional[str] = None


class RegexTestRequest(BaseModel):
    pattern: str = Field(..., description="正则表达式")
    test_text: str = Field(..., description="测试文本")


class RegexTestResult(BaseModel):
    valid: bool = Field(..., description="正则表达式是否有效")
    matches: list[dict] = Field(default_factory=list, description="匹配结果列表")
    error: str = Field(default="", description="错误信息")


# ── 预置类型 ──────────────────────────────────────────────

_PRESET_JSON_PATH = _os.path.join(
    _os.path.dirname(__file__), "..", "..", "config", "preset_entity_types.json"
)
_raw_presets = load_json(_PRESET_JSON_PATH, default={})
PRESET_ENTITY_TYPES: Dict[str, EntityTypeConfig] = {
    k: EntityTypeConfig(**v) for k, v in _raw_presets.items()
}


# ── 持久化 ────────────────────────────────────────────────

def _load_entity_types() -> Dict[str, EntityTypeConfig]:
    """Load entity types from disk, merging with presets."""
    raw = load_json(settings.ENTITY_TYPES_STORE_PATH, default=None)
    if raw is None or not isinstance(raw, dict):
        return {k: v.model_copy() if hasattr(v, "model_copy") else v for k, v in PRESET_ENTITY_TYPES.items()}
    merged: Dict[str, EntityTypeConfig] = {}
    for key, preset in PRESET_ENTITY_TYPES.items():
        if key in raw:
            try:
                merged[key] = EntityTypeConfig(**raw[key]) if isinstance(raw[key], dict) else preset
            except Exception:
                merged[key] = preset
        else:
            merged[key] = preset
    for key, val in raw.items():
        if key not in merged:
            try:
                merged[key] = EntityTypeConfig(**val) if isinstance(val, dict) else val
            except Exception:
                pass
    return merged


def _persist_entity_types() -> None:
    save_json(settings.ENTITY_TYPES_STORE_PATH, entity_types_db)


# 内存存储（启动时从磁盘恢复）
entity_types_db: Dict[str, EntityTypeConfig] = _load_entity_types()
_persist_entity_types()


# ── 公共查询 ──────────────────────────────────────────────

def get_enabled_types() -> List[EntityTypeConfig]:
    """获取所有启用的实体类型"""
    return [t for t in entity_types_db.values() if t.enabled]


def get_regex_types() -> List[EntityTypeConfig]:
    """获取使用正则识别的类型"""
    return [t for t in entity_types_db.values() if t.enabled and t.regex_pattern]


def get_llm_types() -> List[EntityTypeConfig]:
    """获取使用LLM识别的类型"""
    return [t for t in entity_types_db.values() if t.enabled and t.use_llm]


# ── 业务方法 ──────────────────────────────────────────────

def list_types(enabled_only: bool = False, page: int = 1, page_size: int = 0) -> EntityTypesResponse:
    types = list(entity_types_db.values())
    if enabled_only:
        types = [t for t in types if t.enabled]
    types.sort(key=lambda x: x.order)
    total = len(types)
    if page_size <= 0:
        return EntityTypesResponse(custom_types=types, total=total, page=1, page_size=total)
    start = (page - 1) * page_size
    page_items = types[start : start + page_size]
    return EntityTypesResponse(custom_types=page_items, total=total, page=page, page_size=page_size)


def get_type(type_id: str) -> EntityTypeConfig | None:
    return entity_types_db.get(type_id)


def create_type(request: CreateEntityTypeRequest) -> EntityTypeConfig:
    type_id = f"custom_{uuid.uuid4().hex[:8]}"
    new_type = EntityTypeConfig(
        id=type_id,
        name=request.name,
        description=request.description,
        examples=request.examples,
        color=request.color,
        regex_pattern=request.regex_pattern,
        use_llm=request.use_llm,
        tag_template=request.tag_template,
        enabled=True,
        order=200,
    )
    entity_types_db[type_id] = new_type
    _persist_entity_types()
    return new_type


def update_type(type_id: str, request: UpdateEntityTypeRequest) -> EntityTypeConfig | None:
    if type_id not in entity_types_db:
        return None
    existing = entity_types_db[type_id]
    update_data = request.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(existing, key, value)
    entity_types_db[type_id] = existing
    _persist_entity_types()
    return existing


def delete_type(type_id: str) -> tuple[bool, str]:
    """
    Returns (success, error_message).
    success=True  -> deleted OK
    success=False -> error_message explains why
    """
    if type_id not in entity_types_db:
        return False, "实体类型不存在"
    if type_id in PRESET_ENTITY_TYPES:
        return False, "预置类型不能删除，只能禁用"
    del entity_types_db[type_id]
    _persist_entity_types()
    return True, ""


def toggle_type(type_id: str) -> bool | None:
    """Returns new enabled state, or None if not found."""
    if type_id not in entity_types_db:
        return None
    entity_types_db[type_id].enabled = not entity_types_db[type_id].enabled
    _persist_entity_types()
    return entity_types_db[type_id].enabled


def reset_types() -> None:
    global entity_types_db
    entity_types_db = PRESET_ENTITY_TYPES.copy()
    _persist_entity_types()


def test_regex(pattern: str, test_text: str) -> RegexTestResult:
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return RegexTestResult(valid=False, matches=[], error=f"正则语法错误: {str(e)}")
    matches = []
    for m in compiled.finditer(test_text):
        matches.append({
            "text": m.group(),
            "start": m.start(),
            "end": m.end(),
            "groups": list(m.groups()),
        })
    return RegexTestResult(valid=True, matches=matches)


# ---------------------------------------------------------------------------
# Public accessor — use this instead of importing entity_types_db directly,
# so other layers don't couple to the module-level mutable dict.
# ---------------------------------------------------------------------------

def get_entity_types_db() -> Dict[str, EntityTypeConfig]:
    """Return the in-memory entity-types dictionary."""
    return entity_types_db
