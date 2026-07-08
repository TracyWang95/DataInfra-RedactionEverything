"""Recognition pipeline configuration.

The application exposes two runtime pipelines:

- ``ocr_has``: PaddleOCR-VL extraction plus HaS Text semantic
  recognition.
- ``visual_features``: LocateAnything grounding for fixed visual presets and
  user-defined visual labels.
"""

from __future__ import annotations

import os as _os
from enum import Enum

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.persistence import load_json, save_json
from app.core.tenant_config import tenant_store_path
from app.core.visual_feature_categories import normalize_visual_slug


class PipelineMode(str, Enum):
    OCR_HAS = "ocr_has"
    VISUAL_FEATURES = "visual_features"


class VisualFeatureChecklistItem(BaseModel):
    """One visual feature prompt row with positive/negative guidance."""

    rule: str = Field(..., description="Checklist item")
    positive_prompt: str | None = Field(default=None, description="Positive prompt guidance")
    negative_prompt: str | None = Field(default=None, description="Negative prompt guidance")


class VisualFeatureFewShotSample(BaseModel):
    """Few-shot visual feature sample stored as a data URL."""

    type: str = Field(default="positive", description="positive or negative")
    image: str = Field(..., description="Image data URL")
    label: str | None = Field(default=None, description="Sample label or note")
    filename: str | None = Field(default=None, description="Original filename")


class PipelineTypeConfig(BaseModel):
    """Type configuration under a recognition pipeline."""

    id: str = Field(..., description="Stable id")
    name: str = Field(..., description="Display name")
    data_domain: str = Field(default="custom_extension", description="L1 data domain")
    generic_target: str | None = Field(default=None, description="L2 generic target")
    entity_type_ids: list[str] = Field(default_factory=list, description="L3 entity ids")
    linkage_groups: list[str] = Field(default_factory=list, description="Coreference groups")
    coref_enabled: bool = Field(default=False, description="Whether coreference is enabled")
    default_enabled: bool = Field(default=False, description="Whether selected by default")
    description: str | None = Field(None, description="Description or prompt hint")
    examples: list[str] = Field(default_factory=list, description="Example text")
    color: str = Field(default="#6B7280", description="Frontend display color")
    enabled: bool = Field(default=True, description="Whether this type is enabled")
    order: int = Field(default=100, description="Sort order")

    rules: list[str] = Field(default_factory=list, description="Visual feature prompt rules")
    checklist: list[VisualFeatureChecklistItem] = Field(
        default_factory=list,
        description="Visual feature prompt rows",
    )
    negative_prompt_enabled: bool = Field(
        default=False,
        description="Enable negative visual feature prompt",
    )
    negative_prompt: str | None = Field(default=None, description="Negative prompt text")
    few_shot_enabled: bool = Field(default=False, description="Enable few-shot samples")
    few_shot_samples: list[VisualFeatureFewShotSample] = Field(
        default_factory=list,
        description="Few-shot visual feature samples",
    )


class PipelineConfig(BaseModel):
    """Recognition pipeline configuration."""

    mode: PipelineMode = Field(..., description="Pipeline mode")
    name: str = Field(..., description="Display name")
    description: str = Field(..., description="Description")
    enabled: bool = Field(default=True, description="Whether this pipeline is enabled")
    types: list[PipelineTypeConfig] = Field(default_factory=list, description="Type configs")


_PIPELINE_JSON_PATH = _os.path.join(
    _os.path.dirname(__file__),
    "..",
    "..",
    "config",
    "preset_pipeline_types.json",
)
_raw_pipeline = load_json(_PIPELINE_JSON_PATH, default={})

PRESET_OCR_HAS_TYPES: list[PipelineTypeConfig] = [
    PipelineTypeConfig(**item) for item in _raw_pipeline.get("ocr_has", [])
]
PRESET_VISUAL_FEATURE_TYPES: list[PipelineTypeConfig] = [
    PipelineTypeConfig(**item) for item in _raw_pipeline.get("visual_features", [])
]

PRESET_PIPELINES: dict[str, PipelineConfig] = {
    "ocr_has": PipelineConfig(
        mode=PipelineMode.OCR_HAS,
        name="文本识别（PaddleOCR-VL + HaS Text）",
        description="PaddleOCR-VL 1.6 提取文本、表格和版面信息，HaS Text 负责语义实体识别。",
        enabled=True,
        types=PRESET_OCR_HAS_TYPES,
    ),
    "visual_features": PipelineConfig(
        mode=PipelineMode.VISUAL_FEATURES,
        name="视觉特征（LocateAnything）",
        description="LocateAnything 统一定位固定预设和用户自定义视觉特征。",
        enabled=True,
        types=PRESET_VISUAL_FEATURE_TYPES,
    ),
}

PIPELINE_MIGRATIONS_KEY = "_migrations"
VISUAL_FEATURES_PRESET_MIGRATION = "visual_features_preset_v1"
# Document visual-PII features selected by default (seal, signature, ID docs,
# bank card, biometrics, plates, codes, badges, medical, receipt/waybill). Pure
# scene objects (whiteboard, screens, sticky note, key, paper) stay off-by-default
# but remain available for manual selection. Kept in sync with
# preset_pipeline_types.json (default_enabled).
VISUAL_FEATURES_DEFAULT_IDS = {
    # Owner decision: only signature + official seal are auto-checked by default.
    # Every other visual type stays available for manual selection / checklist config,
    # and keeping the default to 2 categories also keeps LocateAnything fast
    # (one prompt per selected category).
    "official_seal", "signature",
}


def _validate_pipeline_type_for_mode(_mode: str, _type_config: PipelineTypeConfig) -> str:
    return ""


def _canonical_pipeline_mode(mode: str) -> str:
    return str(mode)




def _canonicalize_pipeline_type_for_mode(
    mode: str,
    type_config: PipelineTypeConfig,
) -> PipelineTypeConfig:
    if _canonical_pipeline_mode(mode) != "visual_features":
        return type_config
    slug = normalize_visual_slug(type_config.id)
    if not slug.startswith("custom_"):
        slug = f"custom_visual_features_{slug}" if slug else "custom_visual_features_target"
    return type_config.model_copy(update={"id": slug})


def merge_pipeline_disk_snapshot(raw: dict | None) -> dict[str, PipelineConfig]:
    """Merge a persisted pipeline snapshot with current built-in defaults."""

    visual_features_migrated = False
    if isinstance(raw, dict):
        migrations = raw.get(PIPELINE_MIGRATIONS_KEY)
        visual_features_migrated = (
            isinstance(migrations, dict)
            and migrations.get(VISUAL_FEATURES_PRESET_MIGRATION) is True
        )
        raw = {
            key: value
            for key, value in raw.items()
            if key in PRESET_PIPELINES
        }
    else:
        raw = None

    if not raw:
        return {key: value.model_copy(deep=True) for key, value in PRESET_PIPELINES.items()}

    pipelines: dict[str, PipelineConfig] = {
        key: value.model_copy(deep=True) for key, value in PRESET_PIPELINES.items()
    }

    def reconcile_types(key: str, base: PipelineConfig, loaded: PipelineConfig) -> list[PipelineTypeConfig]:
        loaded_by_id = {item.id: item for item in loaded.types}
        base_ids = {item.id for item in base.types}
        reconciled: list[PipelineTypeConfig] = []

        for base_type in base.types:
            previous = loaded_by_id.get(base_type.id)
            if previous is None:
                reconciled.append(base_type)
                continue
            enabled = previous.enabled
            if (
                key == "visual_features"
                and not visual_features_migrated
                and base_type.id in VISUAL_FEATURES_DEFAULT_IDS
            ):
                enabled = base_type.enabled
            reconciled.append(base_type.model_copy(update={"enabled": enabled}))

        for previous in loaded.types:
            if previous.id in base_ids:
                continue
            if key in PRESET_PIPELINES and not previous.id.startswith("custom_"):
                continue
            reconciled.append(previous)
        return reconciled

    for key, value in raw.items():
        try:
            loaded = PipelineConfig(**value)
        except Exception:
            continue
        base = pipelines[key]
        pipelines[key] = base.model_copy(
            update={
                "enabled": loaded.enabled,
                "types": reconcile_types(key, base, loaded) if loaded.types else base.types,
            }
        )
    return pipelines


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
                VISUAL_FEATURES_PRESET_MIGRATION: True,
            },
        },
    )


pipelines_db: dict[str, PipelineConfig] = _load_pipelines()
_persist_pipelines()


def _pipelines_for_owner(owner_id: str | None = None) -> dict[str, PipelineConfig]:
    return pipelines_db if owner_id is None else _load_pipelines(owner_id)


def _custom_semantic_ocr_has_types(owner_id: str | None) -> list[PipelineTypeConfig]:
    """User-added semantic custom items (识别项设置 文本) surfaced into the OCR+HaS
    catalog so they are checkable in the Playground and reach HaS as open-vocab
    tags. Only user customs (id 'custom_*'), only non-regex (regex items run in the
    text-chain fallback step, not as HaS tags). Default-off so nothing auto-runs.
    """
    try:
        from app.services import entity_type_service as _ets
    except Exception:
        return []
    out: list[PipelineTypeConfig] = []
    for et in _ets.list_types(owner_id=owner_id).custom_types:
        if not str(getattr(et, "id", "") or "").startswith("custom_"):
            continue
        if getattr(et, "regex_pattern", None):
            continue  # regex items run in the text-chain fallback step, not as HaS tags
        if not getattr(et, "enabled", True):
            continue
        out.append(
            PipelineTypeConfig(
                id=et.id,
                name=et.name,
                description=getattr(et, "description", None),
                data_domain=getattr(et, "data_domain", "custom_extension") or "custom_extension",
                generic_target=getattr(et, "generic_target", None),
                linkage_groups=list(getattr(et, "linkage_groups", []) or []),
                default_enabled=False,
                enabled=True,
                order=9000,
            )
        )
    return out


def get_pipeline_types_for_mode(
    mode: str,
    *,
    enabled_only: bool = True,
    owner_id: str | None = None,
) -> list[PipelineTypeConfig]:
    """Return pipeline type configs for a mode."""

    db = _pipelines_for_owner(owner_id)
    pipeline = db.get(_canonical_pipeline_mode(mode))
    if pipeline is None:
        return []
    types = pipeline.types
    if enabled_only:
        types = [item for item in types if item.enabled]
    result = list(types)
    if _canonical_pipeline_mode(mode) == "ocr_has":
        existing = {item.id for item in result}
        result.extend(t for t in _custom_semantic_ocr_has_types(owner_id) if t.id not in existing)
    return result


def _visible_pipelines(db: dict[str, PipelineConfig]) -> list[PipelineConfig]:
    return [db[key] for key in ("ocr_has", "visual_features") if key in db]


def _preset_ids_for_mode(mode: str) -> set[str]:
    preset = PRESET_PIPELINES.get(mode)
    return {item.id for item in (preset.types if preset else [])}


def list_pipelines(
    enabled_only: bool = False,
    owner_id: str | None = None,
) -> list[PipelineConfig]:
    pipelines = _visible_pipelines(_pipelines_for_owner(owner_id))
    if enabled_only:
        pipelines = [pipeline for pipeline in pipelines if pipeline.enabled]
    return pipelines


def get_pipeline(mode: str, owner_id: str | None = None) -> PipelineConfig | None:
    db = _pipelines_for_owner(owner_id)
    return db.get(_canonical_pipeline_mode(mode))


def toggle_pipeline(mode: str, owner_id: str | None = None) -> bool | None:
    """Return new enabled state, or None if the pipeline is missing."""

    global pipelines_db
    db = _pipelines_for_owner(owner_id)
    mode = _canonical_pipeline_mode(mode)
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
    """Return sorted types list, or None if the pipeline is missing."""

    db = _pipelines_for_owner(owner_id)
    pipeline = db.get(_canonical_pipeline_mode(mode))
    if pipeline is None:
        return None
    types = pipeline.types
    if enabled_only:
        types = [item for item in types if item.enabled]
    result = sorted(types, key=lambda item: item.order)
    if _canonical_pipeline_mode(mode) == "ocr_has":
        existing = {item.id for item in result}
        result = result + [t for t in _custom_semantic_ocr_has_types(owner_id) if t.id not in existing]
    return result


def add_pipeline_type(
    mode: str,
    type_config: PipelineTypeConfig,
    owner_id: str | None = None,
) -> tuple[PipelineTypeConfig | None, str]:
    """Return ``(created_type, error_message)``."""

    global pipelines_db
    db = _pipelines_for_owner(owner_id)
    mode = _canonical_pipeline_mode(mode)
    if mode not in db:
        return None, "Pipeline does not exist"
    validation_error = _validate_pipeline_type_for_mode(mode, type_config)
    if validation_error:
        return None, validation_error
    type_config = _canonicalize_pipeline_type_for_mode(mode, type_config)
    if type_config.id in [item.id for item in db[mode].types]:
        return None, "Type ID already exists"
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
    """Return ``(updated_type, error_message)``."""

    global pipelines_db
    db = _pipelines_for_owner(owner_id)
    mode = _canonical_pipeline_mode(mode)
    if mode not in db:
        return None, "Pipeline does not exist"
    validation_error = _validate_pipeline_type_for_mode(mode, type_config)
    if validation_error:
        return None, validation_error
    pipeline = db[mode]
    next_config = _canonicalize_pipeline_type_for_mode(mode, type_config)
    for index, current in enumerate(pipeline.types):
        if current.id != type_id:
            continue
        pipeline.types[index] = next_config.model_copy(update={"id": type_id})
        if owner_id is None:
            pipelines_db = db
        _persist_pipelines(db, owner_id)
        return pipeline.types[index], ""
    return None, "Type does not exist"


def toggle_pipeline_type(
    mode: str,
    type_id: str,
    owner_id: str | None = None,
) -> tuple[bool | None, str]:
    """Return ``(new_enabled_state, error_message)``."""

    global pipelines_db
    db = _pipelines_for_owner(owner_id)
    mode = _canonical_pipeline_mode(mode)
    if mode not in db:
        return None, "Pipeline does not exist"
    for item in db[mode].types:
        if item.id != type_id:
            continue
        item.enabled = not item.enabled
        if owner_id is None:
            pipelines_db = db
        _persist_pipelines(db, owner_id)
        return item.enabled, ""
    return None, "Type does not exist"


def delete_pipeline_type(
    mode: str,
    type_id: str,
    owner_id: str | None = None,
) -> tuple[bool, str]:
    """Return ``(success, error_message)``."""

    global pipelines_db
    db = _pipelines_for_owner(owner_id)
    mode = _canonical_pipeline_mode(mode)
    if mode not in db:
        return False, "Pipeline does not exist"
    preset_ids = _preset_ids_for_mode(mode)
    if type_id in preset_ids:
        return False, "Preset type cannot be deleted; disable it instead"
    if not any(item.id == type_id for item in db[mode].types):
        return False, "Type does not exist"
    db[mode].types = [item for item in db[mode].types if item.id != type_id]
    if owner_id is None:
        pipelines_db = db
    _persist_pipelines(db, owner_id)
    return True, ""


def reset_pipelines(owner_id: str | None = None) -> None:
    global pipelines_db
    db = {key: value.model_copy(deep=True) for key, value in PRESET_PIPELINES.items()}
    if owner_id is None:
        pipelines_db = db
    _persist_pipelines(db, owner_id)
