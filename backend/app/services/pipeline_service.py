# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
图像识别 Pipeline 配置 — 业务逻辑层
1. OCR + HaS：文字类敏感信息
2. HaS Image：端侧 YOLO 分割（8081 微服务），21 类隐私区域
"""

from __future__ import annotations

import os as _os
from typing import Dict, List, Optional

from pydantic import BaseModel, Field
from enum import Enum

from app.core.config import settings
from app.core.persistence import load_json, save_json


# ── 数据模型 ──────────────────────────────────────────────

class PipelineMode(str, Enum):
    OCR_HAS = "ocr_has"
    HAS_IMAGE = "has_image"


class PipelineTypeConfig(BaseModel):
    """Pipeline 下的类型配置"""
    id: str = Field(..., description="唯一ID")
    name: str = Field(..., description="显示名称")
    description: Optional[str] = Field(None, description="语义描述/视觉提示")
    examples: List[str] = Field(default_factory=list, description="示例文本")
    color: str = Field(default="#6B7280", description="前端显示颜色")
    enabled: bool = Field(default=True, description="是否启用")
    order: int = Field(default=100, description="排序权重")


class PipelineConfig(BaseModel):
    """Pipeline 配置"""
    mode: PipelineMode = Field(..., description="Pipeline 模式")
    name: str = Field(..., description="显示名称")
    description: str = Field(..., description="描述")
    enabled: bool = Field(default=True, description="是否启用")
    types: List[PipelineTypeConfig] = Field(default_factory=list, description="该 Pipeline 下的类型配置")


# ── 预置 Pipeline 类型 ───────────────────────────────────

_PIPELINE_JSON_PATH = _os.path.join(
    _os.path.dirname(__file__), "..", "..", "config", "preset_pipeline_types.json"
)
_raw_pipeline = load_json(_PIPELINE_JSON_PATH, default={})
PRESET_OCR_HAS_TYPES: List[PipelineTypeConfig] = [
    PipelineTypeConfig(**item) for item in _raw_pipeline.get("ocr_has", [])
]
PRESET_HAS_IMAGE_TYPES: List[PipelineTypeConfig] = [
    PipelineTypeConfig(**item) for item in _raw_pipeline.get("has_image", [])
]

PRESET_PIPELINES: Dict[str, PipelineConfig] = {
    "ocr_has": PipelineConfig(
        mode=PipelineMode.OCR_HAS,
        name="OCR + HaS (本地)",
        description="使用 PaddleOCR-VL 提取文字 + HaS 本地模型识别敏感信息。适合文字多的场景：微信聊天记录、PDF扫描件、合同文档等。完全离线，速度快。",
        enabled=True,
        types=PRESET_OCR_HAS_TYPES,
    ),
    "has_image": PipelineConfig(
        mode=PipelineMode.HAS_IMAGE,
        name="HaS Image (端侧)",
        description="本地 YOLO11 实例分割（8081 微服务），21 类隐私区域检测，与 OCR+HaS 并行后去重合并。",
        enabled=True,
        types=PRESET_HAS_IMAGE_TYPES,
    ),
}


# ── 磁盘快照合并 ─────────────────────────────────────────

def merge_pipeline_disk_snapshot(raw: Optional[dict]) -> Dict[str, PipelineConfig]:
    """
    将磁盘/快照中的 pipeline JSON 合并到预置配置上（不写盘）。
    用于启动加载与单元测试。
    """
    if isinstance(raw, dict):
        raw = {k: v for k, v in raw.items() if k != "glm_vision"}
    else:
        raw = None
    if not raw:
        return {k: v.model_copy(deep=True) for k, v in PRESET_PIPELINES.items()}
    pipelines: Dict[str, PipelineConfig] = {k: v.model_copy(deep=True) for k, v in PRESET_PIPELINES.items()}
    for key, value in raw.items():
        if key == "glm_vision":
            continue
        try:
            if isinstance(value, dict) and value.get("mode") == "glm_vision":
                value = {**value, "mode": "has_image"}
            loaded = PipelineConfig(**value)
        except Exception:
            continue
        if key in pipelines:
            base = pipelines[key]
            pipelines[key] = base.model_copy(update={
                "enabled": loaded.enabled,
                "types": loaded.types,
            })
        else:
            pipelines[key] = loaded
    return pipelines


# ── 持久化 ────────────────────────────────────────────────

def _load_pipelines() -> Dict[str, PipelineConfig]:
    raw = load_json(settings.PIPELINE_STORE_PATH, default=None)
    return merge_pipeline_disk_snapshot(raw if isinstance(raw, dict) else None)


def _persist_pipelines() -> None:
    save_json(settings.PIPELINE_STORE_PATH, pipelines_db)


# 内存存储（启动时从磁盘恢复）
pipelines_db: Dict[str, PipelineConfig] = _load_pipelines()
_persist_pipelines()


# ── 公共查询 ──────────────────────────────────────────────

def get_pipeline_types_for_mode(mode: str) -> List[PipelineTypeConfig]:
    """获取指定模式下启用的类型配置"""
    if mode not in pipelines_db:
        return []
    return [t for t in pipelines_db[mode].types if t.enabled]


# ── 业务方法 ──────────────────────────────────────────────

def list_pipelines(enabled_only: bool = False) -> List[PipelineConfig]:
    pipelines = list(pipelines_db.values())
    if enabled_only:
        pipelines = [p for p in pipelines if p.enabled]
    return pipelines


def get_pipeline(mode: str) -> PipelineConfig | None:
    return pipelines_db.get(mode)


def toggle_pipeline(mode: str) -> bool | None:
    """Returns new enabled state, or None if not found."""
    if mode not in pipelines_db:
        return None
    pipelines_db[mode].enabled = not pipelines_db[mode].enabled
    _persist_pipelines()
    return pipelines_db[mode].enabled


def get_pipeline_types(mode: str, enabled_only: bool = True) -> List[PipelineTypeConfig] | None:
    """Returns sorted types list, or None if pipeline not found."""
    if mode not in pipelines_db:
        return None
    types = pipelines_db[mode].types
    if enabled_only:
        types = [t for t in types if t.enabled]
    return sorted(types, key=lambda t: t.order)


def add_pipeline_type(mode: str, type_config: PipelineTypeConfig) -> tuple[PipelineTypeConfig | None, str]:
    """Returns (created_type, error_message)."""
    if mode not in pipelines_db:
        return None, "Pipeline 不存在"
    existing_ids = [t.id for t in pipelines_db[mode].types]
    if type_config.id in existing_ids:
        return None, "类型 ID 已存在"
    pipelines_db[mode].types.append(type_config)
    _persist_pipelines()
    return type_config, ""


def update_pipeline_type(mode: str, type_id: str, type_config: PipelineTypeConfig) -> tuple[PipelineTypeConfig | None, str]:
    """Returns (updated_type, error_message)."""
    if mode not in pipelines_db:
        return None, "Pipeline 不存在"
    for i, t in enumerate(pipelines_db[mode].types):
        if t.id == type_id:
            pipelines_db[mode].types[i] = type_config
            _persist_pipelines()
            return type_config, ""
    return None, "类型不存在"


def toggle_pipeline_type(mode: str, type_id: str) -> tuple[bool | None, str]:
    """Returns (new_enabled_state, error_message). None means not found."""
    if mode not in pipelines_db:
        return None, "Pipeline 不存在"
    for t in pipelines_db[mode].types:
        if t.id == type_id:
            t.enabled = not t.enabled
            _persist_pipelines()
            return t.enabled, ""
    return None, "类型不存在"


def delete_pipeline_type(mode: str, type_id: str) -> tuple[bool, str]:
    """Returns (success, error_message)."""
    if mode not in pipelines_db:
        return False, "Pipeline 不存在"
    preset_ids = [t.id for t in PRESET_PIPELINES.get(mode, PipelineConfig(
        mode=PipelineMode.OCR_HAS, name="", description="", types=[]
    )).types]
    if type_id in preset_ids:
        return False, "预置类型不能删除，只能禁用"
    pipelines_db[mode].types = [t for t in pipelines_db[mode].types if t.id != type_id]
    _persist_pipelines()
    return True, ""


def reset_pipelines() -> None:
    global pipelines_db
    pipelines_db = {k: v.model_copy(deep=True) for k, v in PRESET_PIPELINES.items()}
    _persist_pipelines()
