"""
图像识别 Pipeline 配置 — 业务逻辑层
1. OCR + HaS：文字类敏感信息
2. HaS Image：端侧 YOLO 分割（8081 微服务），21 类隐私区域
"""

from __future__ import annotations

import os as _os
from enum import Enum

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.has_image_categories import (
    DEFAULT_EXCLUDED_HAS_IMAGE_SLUGS,
    is_has_image_model_slug,
    normalize_visual_slug,
)
from app.core.persistence import load_json, save_json
from app.core.tenant_config import tenant_store_path

# ── 数据模型 ──────────────────────────────────────────────

class PipelineMode(str, Enum):
    OCR_HAS = "ocr_has"
    HAS_IMAGE = "has_image"
    VLM = "vlm"


class VlmChecklistItem(BaseModel):
    """One VLM checklist row with positive/negative guidance."""
    rule: str = Field(..., description="Checklist item")
    positive_prompt: str | None = Field(default=None, description="Positive prompt guidance")
    negative_prompt: str | None = Field(default=None, description="Negative prompt guidance")


class VlmFewShotSample(BaseModel):
    """Few-shot image sample stored as a data URL."""
    type: str = Field(default="positive", description="positive or negative")
    image: str = Field(..., description="Image data URL")
    label: str | None = Field(default=None, description="Sample label or note")
    filename: str | None = Field(default=None, description="Original filename")


class PipelineTypeConfig(BaseModel):
    """Pipeline 下的类型配置"""
    id: str = Field(..., description="唯一ID")
    name: str = Field(..., description="显示名称")
    data_domain: str = Field(default="custom_extension", description="L1 data domain")
    generic_target: str | None = Field(default=None, description="L2 generic target for L3 types")
    entity_type_ids: list[str] = Field(default_factory=list, description="L3 entity types covered by a L2 generic target")
    linkage_groups: list[str] = Field(default_factory=list, description="Coreference/linkage capability groups")
    coref_enabled: bool = Field(default=False, description="Whether group-based coreference is enabled")
    default_enabled: bool = Field(default=False, description="Whether selected by the generic default")
    description: str | None = Field(None, description="语义描述/视觉提示")
    examples: list[str] = Field(default_factory=list, description="示例文本")
    color: str = Field(default="#6B7280", description="前端显示颜色")
    enabled: bool = Field(default=True, description="是否启用")
    order: int = Field(default=100, description="排序权重")


    rules: list[str] = Field(default_factory=list, description="VLM checklist rules")
    checklist: list[VlmChecklistItem] = Field(default_factory=list, description="VLM checklist rows")
    negative_prompt_enabled: bool = Field(default=False, description="Enable VLM negative checklist")
    negative_prompt: str | None = Field(default=None, description="VLM negative checklist text")
    few_shot_enabled: bool = Field(default=False, description="Enable VLM few-shot samples")
    few_shot_samples: list[VlmFewShotSample] = Field(default_factory=list, description="VLM few-shot samples")


class PipelineConfig(BaseModel):
    """Pipeline 配置"""
    mode: PipelineMode = Field(..., description="Pipeline 模式")
    name: str = Field(..., description="显示名称")
    description: str = Field(..., description="描述")
    enabled: bool = Field(default=True, description="是否启用")
    types: list[PipelineTypeConfig] = Field(default_factory=list, description="该 Pipeline 下的类型配置")


# ── 预置 Pipeline 类型 ───────────────────────────────────

_PIPELINE_JSON_PATH = _os.path.join(
    _os.path.dirname(__file__), "..", "..", "config", "preset_pipeline_types.json"
)
_raw_pipeline = load_json(_PIPELINE_JSON_PATH, default={})
PRESET_OCR_HAS_TYPES: list[PipelineTypeConfig] = [
    PipelineTypeConfig(**item) for item in _raw_pipeline.get("ocr_has", [])
]
PRESET_HAS_IMAGE_TYPES: list[PipelineTypeConfig] = [
    PipelineTypeConfig(**item) for item in _raw_pipeline.get("has_image", [])
]
PRESET_VLM_TYPES: list[PipelineTypeConfig] = [
    PipelineTypeConfig(**item) for item in _raw_pipeline.get("vlm", [])
]

PRESET_PIPELINES: dict[str, PipelineConfig] = {
    "ocr_has": PipelineConfig(
        mode=PipelineMode.OCR_HAS,
        name="文本识别（Structure + HaS Text）",
        description="使用 PP-StructureV3 提取精确文本行/表格单元，HaS Text 负责语义实体识别，再把实体回填到 OCR 坐标。图像路线不跑正则，避免扫描件金额、编号等误框；纯文本路线仍保留正则。",
        enabled=True,
        types=PRESET_OCR_HAS_TYPES,
    ),
    "has_image": PipelineConfig(
        mode=PipelineMode.HAS_IMAGE,
        name="视觉目标（HaS Image）",
        description="本地 YOLO11 实例分割（8081 微服务），负责公章、人脸、证件、银行卡、二维码、屏幕和面单等非文本视觉区域；纸质文档整页容器保留可选但不默认勾选。",
        enabled=True,
        types=PRESET_HAS_IMAGE_TYPES,
    ),
    "vlm": PipelineConfig(
        mode=PipelineMode.VLM,
        name="视觉语义（VLM）",
        description="OpenAI 兼容视觉语言模型，按自定义规则清单识别签字等 HaS Image / OCR 难覆盖的视觉语义目标。",
        enabled=True,
        types=PRESET_VLM_TYPES,
    ),
}

OCR_HAS_VISUAL_DEPRECATED_IDS = {
    "SEAL",
    "SIGNATURE",
    "FINGERPRINT",
    "PHOTO",
    "QR_CODE",
    "HANDWRITING",
    "WATERMARK",
}

PIPELINE_MIGRATIONS_KEY = "_migrations"
HAS_IMAGE_PAPER_DEFAULT_DISABLED_MIGRATION = "has_image_paper_default_disabled"


# ── 磁盘快照合并 ─────────────────────────────────────────

def _validate_pipeline_type_for_mode(mode: str, type_config: PipelineTypeConfig) -> str:
    if mode == "has_image" and not is_has_image_model_slug(type_config.id):
        return "HaS Image is fixed to the 21 model classes"
    return ""


def _canonicalize_pipeline_type_for_mode(
    mode: str,
    type_config: PipelineTypeConfig,
) -> PipelineTypeConfig:
    if mode != "has_image":
        return type_config
    return type_config.model_copy(update={"id": normalize_visual_slug(type_config.id)})


def merge_pipeline_disk_snapshot(raw: dict | None) -> dict[str, PipelineConfig]:
    """
    将磁盘/快照中的 pipeline JSON 合并到预置配置上（不写盘）。
    用于启动加载与单元测试。
    """
    has_paper_default_migration = False
    if isinstance(raw, dict):
        migrations = raw.get(PIPELINE_MIGRATIONS_KEY)
        has_paper_default_migration = (
            isinstance(migrations, dict)
            and migrations.get(HAS_IMAGE_PAPER_DEFAULT_DISABLED_MIGRATION) is True
        )
        raw = {
            k: v
            for k, v in raw.items()
            if k not in {"glm_vision", PIPELINE_MIGRATIONS_KEY}
        }
        ocr_has = raw.get("ocr_has")
        if isinstance(ocr_has, dict) and isinstance(ocr_has.get("types"), list):
            ocr_has = dict(ocr_has)
            ocr_has["types"] = [
                item for item in ocr_has["types"]
                if not (
                    isinstance(item, dict)
                    and str(item.get("id", "")) in OCR_HAS_VISUAL_DEPRECATED_IDS
                )
            ]
            raw["ocr_has"] = ocr_has
    else:
        raw = None
    if not raw:
        return {k: v.model_copy(deep=True) for k, v in PRESET_PIPELINES.items()}
    pipelines: dict[str, PipelineConfig] = {k: v.model_copy(deep=True) for k, v in PRESET_PIPELINES.items()}

    def reconcile_types(base: PipelineConfig, loaded: PipelineConfig) -> list[PipelineTypeConfig]:
        loaded_by_id = {item.id: item for item in loaded.types}
        base_ids = {item.id for item in base.types}
        reconciled: list[PipelineTypeConfig] = []
        for base_type in base.types:
            previous = loaded_by_id.get(base_type.id)
            if previous is not None:
                enabled = previous.enabled
                if (
                    key == "has_image"
                    and not has_paper_default_migration
                    and base_type.id in DEFAULT_EXCLUDED_HAS_IMAGE_SLUGS
                ):
                    enabled = base_type.enabled
                reconciled.append(base_type.model_copy(update={"enabled": enabled}))
            else:
                reconciled.append(base_type)
        for previous in loaded.types:
            if previous.id in base_ids or previous.id in OCR_HAS_VISUAL_DEPRECATED_IDS:
                continue
            if key == "has_image":
                continue
            if key in PRESET_PIPELINES and not previous.id.startswith("custom_"):
                continue
            reconciled.append(previous)
        return reconciled

    for key, value in raw.items():
        if key in {"glm_vision", PIPELINE_MIGRATIONS_KEY}:
            continue
        try:
            if isinstance(value, dict) and value.get("mode") == "glm_vision":
                value = {**value, "mode": "has_image"}
            loaded = PipelineConfig(**value)
        except Exception:
            continue
        if key in pipelines:
            base = pipelines[key]
            next_types = reconcile_types(base, loaded) if loaded.types else base.types
            pipelines[key] = base.model_copy(update={
                "enabled": loaded.enabled,
                "types": next_types,
            })
        else:
            pipelines[key] = loaded
    return pipelines


# ── 持久化 ────────────────────────────────────────────────

def _pipeline_store_path(owner_id: str | None = None) -> str:
    return tenant_store_path(owner_id, settings.PIPELINE_STORE_PATH, "pipelines.json")


def _load_pipelines(owner_id: str | None = None) -> dict[str, PipelineConfig]:
    raw = load_json(_pipeline_store_path(owner_id), default=None)
    return merge_pipeline_disk_snapshot(raw if isinstance(raw, dict) else None)


def _persist_pipelines(
    db: dict[str, PipelineConfig] | None = None,
    owner_id: str | None = None,
) -> None:
    save_json(
        _pipeline_store_path(owner_id),
        {
            **(db if db is not None else pipelines_db),
            PIPELINE_MIGRATIONS_KEY: {
                HAS_IMAGE_PAPER_DEFAULT_DISABLED_MIGRATION: True,
            },
        },
    )


# 内存存储（启动时从磁盘恢复）
pipelines_db: dict[str, PipelineConfig] = _load_pipelines()
_persist_pipelines()


# ── 公共查询 ──────────────────────────────────────────────

def _pipelines_for_owner(owner_id: str | None = None) -> dict[str, PipelineConfig]:
    return pipelines_db if owner_id is None else _load_pipelines(owner_id)


def get_pipeline_types_for_mode(
    mode: str,
    *,
    enabled_only: bool = True,
    owner_id: str | None = None,
) -> list[PipelineTypeConfig]:
    """获取指定模式下的类型配置。默认只返回启用项；显式选择校验可读取全部项。"""
    db = _pipelines_for_owner(owner_id)
    if mode not in db:
        return []
    types = db[mode].types
    if enabled_only:
        types = [t for t in types if t.enabled]
    return list(types)


# ── 业务方法 ──────────────────────────────────────────────

def list_pipelines(
    enabled_only: bool = False,
    owner_id: str | None = None,
) -> list[PipelineConfig]:
    pipelines = list(_pipelines_for_owner(owner_id).values())
    if enabled_only:
        pipelines = [p for p in pipelines if p.enabled]
    return pipelines


def get_pipeline(mode: str, owner_id: str | None = None) -> PipelineConfig | None:
    return _pipelines_for_owner(owner_id).get(mode)


def toggle_pipeline(mode: str, owner_id: str | None = None) -> bool | None:
    """Returns new enabled state, or None if not found."""
    global pipelines_db
    db = _pipelines_for_owner(owner_id)
    if mode not in db:
        return None
    db[mode].enabled = not db[mode].enabled
    if owner_id is None:
        pipelines_db = db
    _persist_pipelines(db, owner_id)
    return db[mode].enabled


def get_pipeline_types(
    mode: str,
    enabled_only: bool = True,
    owner_id: str | None = None,
) -> list[PipelineTypeConfig] | None:
    """Returns sorted types list, or None if pipeline not found."""
    db = _pipelines_for_owner(owner_id)
    if mode not in db:
        return None
    types = db[mode].types
    if enabled_only:
        types = [t for t in types if t.enabled]
    return sorted(types, key=lambda t: t.order)


def add_pipeline_type(
    mode: str,
    type_config: PipelineTypeConfig,
    owner_id: str | None = None,
) -> tuple[PipelineTypeConfig | None, str]:
    """Returns (created_type, error_message)."""
    global pipelines_db
    db = _pipelines_for_owner(owner_id)
    if mode not in db:
        return None, "Pipeline 不存在"
    validation_error = _validate_pipeline_type_for_mode(mode, type_config)
    if validation_error:
        return None, validation_error
    type_config = _canonicalize_pipeline_type_for_mode(mode, type_config)
    existing_ids = [t.id for t in db[mode].types]
    if type_config.id in existing_ids:
        return None, "类型 ID 已存在"
    db[mode].types.append(type_config)
    if owner_id is None:
        pipelines_db = db
    _persist_pipelines(db, owner_id)
    return type_config, ""


def update_pipeline_type(
    mode: str,
    type_id: str,
    type_config: PipelineTypeConfig,
    owner_id: str | None = None,
) -> tuple[PipelineTypeConfig | None, str]:
    """Returns (updated_type, error_message)."""
    global pipelines_db
    db = _pipelines_for_owner(owner_id)
    if mode not in db:
        return None, "Pipeline 不存在"
    validation_error = _validate_pipeline_type_for_mode(mode, type_config)
    if validation_error:
        return None, validation_error
    type_config = _canonicalize_pipeline_type_for_mode(mode, type_config)
    for i, t in enumerate(db[mode].types):
        if t.id == type_id:
            db[mode].types[i] = type_config
            if owner_id is None:
                pipelines_db = db
            _persist_pipelines(db, owner_id)
            return type_config, ""
    return None, "类型不存在"


def toggle_pipeline_type(
    mode: str,
    type_id: str,
    owner_id: str | None = None,
) -> tuple[bool | None, str]:
    """Returns (new_enabled_state, error_message). None means not found."""
    global pipelines_db
    db = _pipelines_for_owner(owner_id)
    if mode not in db:
        return None, "Pipeline 不存在"
    for t in db[mode].types:
        if t.id == type_id:
            t.enabled = not t.enabled
            if owner_id is None:
                pipelines_db = db
            _persist_pipelines(db, owner_id)
            return t.enabled, ""
    return None, "类型不存在"


def delete_pipeline_type(
    mode: str,
    type_id: str,
    owner_id: str | None = None,
) -> tuple[bool, str]:
    """Returns (success, error_message)."""
    global pipelines_db
    db = _pipelines_for_owner(owner_id)
    if mode not in db:
        return False, "Pipeline 不存在"
    preset_ids = [t.id for t in PRESET_PIPELINES.get(mode, PipelineConfig(
        mode=PipelineMode.OCR_HAS, name="", description="", types=[]
    )).types]
    if type_id in preset_ids:
        return False, "预置类型不能删除，只能禁用"
    db[mode].types = [t for t in db[mode].types if t.id != type_id]
    if owner_id is None:
        pipelines_db = db
    _persist_pipelines(db, owner_id)
    return True, ""


def reset_pipelines(owner_id: str | None = None) -> None:
    global pipelines_db
    db = {k: v.model_copy(deep=True) for k, v in PRESET_PIPELINES.items()}
    if owner_id is None:
        pipelines_db = db
    _persist_pipelines(db, owner_id)
