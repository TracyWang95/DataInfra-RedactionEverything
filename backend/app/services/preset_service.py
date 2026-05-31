"""
识别配置预设（Preset） — 业务逻辑层
供单文件处理 / 批量向导 / 识别项配置页共用同一套「识别类型 + 替换模式」组合。
"""

from __future__ import annotations

import os as _os
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.core.config import settings
from app.core.has_image_categories import HAS_IMAGE_MODEL_SLUGS
from app.core.persistence import load_json, save_json
from app.core.tenant_config import tenant_store_path
from app.models.schemas import (
    PresetCreate,
    PresetImportItem,
    PresetImportRequest,
    PresetOut,
    PresetsListResponse,
    PresetUpdate,
)

_BUILTIN_PRESETS_PATH = _os.path.join(
    _os.path.dirname(__file__), "..", "..", "config", "industry_presets.json"
)
_PRESET_ENTITY_TYPES_PATH = _os.path.join(
    _os.path.dirname(__file__), "..", "..", "config", "preset_entity_types.json"
)
_PRESET_PIPELINE_TYPES_PATH = _os.path.join(
    _os.path.dirname(__file__), "..", "..", "config", "preset_pipeline_types.json"
)

# ── 内部工具 ─────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _preset_store_path(owner_id: str | None = None) -> str:
    return tenant_store_path(owner_id, settings.PRESET_STORE_PATH, "presets.json")


def _load_store(owner_id: str | None = None) -> list[dict[str, Any]]:
    raw = load_json(_preset_store_path(owner_id), default=None)
    if raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, dict) and "presets" in raw:
        presets = raw["presets"]
        return list(presets) if isinstance(presets, list) else []
    return []


def _save_store(presets: list[dict[str, Any]], owner_id: str | None = None) -> None:
    save_json(_preset_store_path(owner_id), presets)


def _enabled_entity_type_ids() -> set[str]:
    raw = load_json(_PRESET_ENTITY_TYPES_PATH, default={})
    if not isinstance(raw, dict):
        return set()
    return {
        str(type_id)
        for type_id, item in raw.items()
        if isinstance(item, dict) and item.get("enabled") is not False
    }


def _enabled_pipeline_type_ids(group: str, owner_id: str | None = None) -> set[str]:
    if group == "vlm":
        try:
            from app.services.pipeline_service import get_pipeline_types_for_mode

            return {
                item.id
                for item in get_pipeline_types_for_mode(
                    "vlm",
                    enabled_only=True,
                    owner_id=owner_id,
                )
            }
        except Exception:
            return set()
    raw = load_json(_PRESET_PIPELINE_TYPES_PATH, default={})
    items = raw.get(group, []) if isinstance(raw, dict) else []
    if not isinstance(items, list):
        return set()
    return {
        str(item["id"])
        for item in items
        if isinstance(item, dict) and item.get("id") and item.get("enabled") is not False
    }


def _validate_builtin_preset_contract(preset: dict[str, Any]) -> None:
    preset_id = str(preset.get("id") or "<missing-id>")
    selected = set(preset.get("selectedEntityTypeIds") or [])
    ocr_types = set(preset.get("ocrHasTypes") or [])
    image_types = set(preset.get("hasImageTypes") or [])
    vlm_types = set(preset.get("vlmTypes") or [])

    invalid_entity_types = selected - _enabled_entity_type_ids()
    invalid_ocr_types = ocr_types - _enabled_pipeline_type_ids("ocr_has")
    invalid_image_types = image_types - _enabled_pipeline_type_ids("has_image")
    invalid_vlm_types = vlm_types - _enabled_pipeline_type_ids("vlm")
    non_model_image_types = image_types - set(HAS_IMAGE_MODEL_SLUGS)

    errors: list[str] = []
    if invalid_entity_types:
        errors.append(f"unknown or disabled entity types: {sorted(invalid_entity_types)}")
    if invalid_ocr_types:
        errors.append(f"unknown or disabled OCR/HaS types: {sorted(invalid_ocr_types)}")
    if invalid_image_types:
        errors.append(f"unknown or disabled HaS Image types: {sorted(invalid_image_types)}")
    if invalid_vlm_types:
        errors.append(f"unknown or disabled VLM types: {sorted(invalid_vlm_types)}")
    if non_model_image_types:
        errors.append(f"non-model HaS Image types: {sorted(non_model_image_types)}")
    if errors:
        raise ValueError(f"Invalid builtin preset {preset_id}: {'; '.join(errors)}")


def _load_builtin_presets() -> list[dict[str, Any]]:
    raw = load_json(_BUILTIN_PRESETS_PATH, default=[])
    if isinstance(raw, dict):
        raw = raw.get("presets", [])
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
            continue
        _validate_builtin_preset_contract(item)
        rows.append({**item, "readonly": True})
    return rows


def _builtin_ids() -> set[str]:
    return {str(p["id"]) for p in _load_builtin_presets() if p.get("id")}


def is_builtin(preset_id: str) -> bool:
    return preset_id in _builtin_ids()


def _merge_with_builtin_presets(user_presets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    builtins = _load_builtin_presets()
    builtin_ids = {str(p["id"]) for p in builtins if p.get("id")}
    merged = list(builtins)
    for preset in user_presets:
        if not isinstance(preset, dict) or not preset.get("id"):
            continue
        if str(preset["id"]) in builtin_ids:
            continue
        merged.append({**preset, "readonly": False})
    return merged


def _to_out(p: dict[str, Any]) -> PresetOut:
    return PresetOut(
        id=p["id"],
        name=p["name"],
        kind=p.get("kind") or "full",
        selectedEntityTypeIds=p.get("selectedEntityTypeIds") or [],
        ocrHasTypes=p.get("ocrHasTypes") or [],
        hasImageTypes=p.get("hasImageTypes") or [],
        vlmTypes=p.get("vlmTypes") or [],
        dataDomains=p.get("dataDomains") or [],
        genericTargets=p.get("genericTargets") or [],
        linkageGroups=p.get("linkageGroups") or [],
        replacementMode=p.get("replacementMode") or "structured",
        created_at=p.get("created_at") or _now_iso(),
        updated_at=p.get("updated_at") or _now_iso(),
        readonly=bool(p.get("readonly")),
    )


# ── 业务方法 ──────────────────────────────────────────────

def _to_out_or_none(p: dict[str, Any]) -> PresetOut | None:
    try:
        return _to_out(p)
    except (KeyError, TypeError, ValueError, ValidationError):
        return None


def _import_item_to_row(preset: PresetImportItem) -> dict[str, Any]:
    ts = _now_iso()
    created_at = preset.created_at or ts
    return {
        "id": preset.id,
        "name": preset.name.strip(),
        "kind": preset.kind,
        "selectedEntityTypeIds": preset.selectedEntityTypeIds,
        "ocrHasTypes": preset.ocrHasTypes,
        "hasImageTypes": preset.hasImageTypes,
        "vlmTypes": preset.vlmTypes,
        "dataDomains": preset.dataDomains,
        "genericTargets": preset.genericTargets,
        "linkageGroups": preset.linkageGroups,
        "replacementMode": preset.replacementMode,
        "created_at": created_at,
        "updated_at": preset.updated_at or created_at,
    }


def list_presets(
    page: int = 1,
    page_size: int = 0,
    owner_id: str | None = None,
) -> PresetsListResponse:
    presets = _merge_with_builtin_presets(_load_store(owner_id))
    all_out = [out for p in presets if (out := _to_out_or_none(p)) is not None]
    total = len(all_out)
    if page_size <= 0:
        return PresetsListResponse(presets=all_out, total=total, page=1, page_size=total)
    start = (page - 1) * page_size
    page_items = all_out[start : start + page_size]
    return PresetsListResponse(
        presets=page_items,
        total=total,
        page=page,
        page_size=page_size,
    )


def create(payload: PresetCreate, owner_id: str | None = None) -> PresetOut:
    presets = _load_store(owner_id)
    pid = str(uuid.uuid4())
    ts = _now_iso()
    row = {
        "id": pid,
        "name": payload.name.strip(),
        "kind": payload.kind,
        "selectedEntityTypeIds": payload.selectedEntityTypeIds,
        "ocrHasTypes": payload.ocrHasTypes,
        "hasImageTypes": payload.hasImageTypes,
        "vlmTypes": payload.vlmTypes,
        "dataDomains": payload.dataDomains,
        "genericTargets": payload.genericTargets,
        "linkageGroups": payload.linkageGroups,
        "replacementMode": payload.replacementMode,
        "created_at": ts,
        "updated_at": ts,
    }
    presets.append(row)
    _save_store(presets, owner_id)
    return _to_out(row)


def update(
    preset_id: str,
    patch: PresetUpdate,
    owner_id: str | None = None,
) -> PresetOut | None:
    """Returns updated PresetOut, or None if not found."""
    if is_builtin(preset_id):
        return None
    presets = _load_store(owner_id)
    for i, p in enumerate(presets):
        if p.get("id") != preset_id:
            continue
        if patch.name is not None:
            p["name"] = patch.name.strip()
        if patch.kind is not None:
            p["kind"] = patch.kind
        if patch.selectedEntityTypeIds is not None:
            p["selectedEntityTypeIds"] = patch.selectedEntityTypeIds
        if patch.ocrHasTypes is not None:
            p["ocrHasTypes"] = patch.ocrHasTypes
        if patch.hasImageTypes is not None:
            p["hasImageTypes"] = patch.hasImageTypes
        if patch.vlmTypes is not None:
            p["vlmTypes"] = patch.vlmTypes
        if patch.dataDomains is not None:
            p["dataDomains"] = patch.dataDomains
        if patch.genericTargets is not None:
            p["genericTargets"] = patch.genericTargets
        if patch.linkageGroups is not None:
            p["linkageGroups"] = patch.linkageGroups
        if patch.replacementMode is not None:
            p["replacementMode"] = patch.replacementMode
        p["updated_at"] = _now_iso()
        presets[i] = p
        _save_store(presets, owner_id)
        return _to_out(p)
    return None


def delete(preset_id: str, owner_id: str | None = None) -> bool:
    """Returns True if deleted, False if not found."""
    if is_builtin(preset_id):
        return False
    presets = _load_store(owner_id)
    nxt = [p for p in presets if p.get("id") != preset_id]
    if len(nxt) == len(presets):
        return False
    _save_store(nxt, owner_id)
    return True


def export_all(owner_id: str | None = None) -> dict:
    data = _merge_with_builtin_presets(_load_store(owner_id))
    return {"presets": data, "exported_at": datetime.now(UTC).isoformat(), "version": "1.0"}


def import_presets(request: PresetImportRequest, owner_id: str | None = None) -> int:
    """Returns count of imported presets."""
    builtin_ids = _builtin_ids()
    incoming = [
        _import_item_to_row(p)
        for p in request.presets
        if p.id not in builtin_ids
    ]
    if request.merge:
        existing = _load_store(owner_id)
        existing_ids = {p.get("id") for p in existing if isinstance(p, dict)}
        imported_count = 0
        for p in incoming:
            if p.get("id") not in existing_ids:
                existing.append(p)
                existing_ids.add(p.get("id"))
                imported_count += 1
        _save_store(existing, owner_id)
        return imported_count
    else:
        _save_store(incoming, owner_id)
    return len(incoming)
