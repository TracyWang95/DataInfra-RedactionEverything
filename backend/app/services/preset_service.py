"""Recognition preset service."""

from __future__ import annotations

import os as _os
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.core.config import settings
from app.core.persistence import load_json, save_json
from app.core.tenant_config import store_lock, tenant_store_path
from app.models.schemas import (
    PresetCreate,
    PresetImportItem,
    PresetImportRequest,
    PresetOut,
    PresetsListResponse,
    PresetUpdate,
)

_BUILTIN_PRESETS_PATH = _os.path.join(
    _os.path.dirname(__file__),
    "..",
    "..",
    "config",
    "industry_presets.json",
)
_PRESET_ENTITY_TYPES_PATH = _os.path.join(
    _os.path.dirname(__file__),
    "..",
    "..",
    "config",
    "preset_entity_types.json",
)
_PRESET_PIPELINE_TYPES_PATH = _os.path.join(
    _os.path.dirname(__file__),
    "..",
    "..",
    "config",
    "preset_pipeline_types.json",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _preset_store_path(owner_id: str | None = None) -> str:
    return tenant_store_path(owner_id, settings.PRESET_STORE_PATH, "presets.json")


def _normalize_preset_row(preset: dict[str, Any]) -> dict[str, Any]:
    visual_feature_types = list(
        dict.fromkeys(str(item) for item in (preset.get("visualFeatureTypes") or []))
    )
    return {
        **preset,
        "visualFeatureTypes": visual_feature_types,
    }


def _load_store(owner_id: str | None = None) -> list[dict[str, Any]]:
    raw = load_json(_preset_store_path(owner_id), default=None)
    if raw is None:
        return []
    if isinstance(raw, list):
        return [_normalize_preset_row(item) for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict) and "presets" in raw:
        presets = raw["presets"]
        if isinstance(presets, list):
            return [_normalize_preset_row(item) for item in presets if isinstance(item, dict)]
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
    if group == "visual_features":
        try:
            from app.services.pipeline_service import get_pipeline_types_for_mode

            return {
                item.id
                for item in get_pipeline_types_for_mode(
                    "visual_features",
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
    visual_feature_types = set(preset.get("visualFeatureTypes") or [])

    invalid_entity_types = selected - _enabled_entity_type_ids()
    invalid_ocr_types = ocr_types - _enabled_pipeline_type_ids("ocr_has")
    invalid_visual_types = visual_feature_types - _enabled_pipeline_type_ids("visual_features")

    errors: list[str] = []
    if invalid_entity_types:
        errors.append(f"unknown or disabled entity types: {sorted(invalid_entity_types)}")
    if invalid_ocr_types:
        errors.append(f"unknown or disabled OCR/HaS types: {sorted(invalid_ocr_types)}")
    if invalid_visual_types:
        errors.append(f"unknown or disabled visual feature types: {sorted(invalid_visual_types)}")
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
        item = _normalize_preset_row(item)
        _validate_builtin_preset_contract(item)
        rows.append({**item, "readonly": True})
    return rows


def _builtin_ids() -> set[str]:
    return {str(preset["id"]) for preset in _load_builtin_presets() if preset.get("id")}


def is_builtin(preset_id: str) -> bool:
    return preset_id in _builtin_ids()


def _merge_with_builtin_presets(user_presets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    builtins = _load_builtin_presets()
    builtin_ids = {str(preset["id"]) for preset in builtins if preset.get("id")}
    merged = list(builtins)
    for preset in user_presets:
        if not isinstance(preset, dict) or not preset.get("id"):
            continue
        if str(preset["id"]) in builtin_ids:
            continue
        merged.append({**_normalize_preset_row(preset), "readonly": False})
    return merged


def _to_out(preset: dict[str, Any]) -> PresetOut:
    return PresetOut(
        id=preset["id"],
        name=preset["name"],
        kind=preset.get("kind") or "full",
        selectedEntityTypeIds=preset.get("selectedEntityTypeIds") or [],
        ocrHasTypes=preset.get("ocrHasTypes") or [],
        visualFeatureTypes=preset.get("visualFeatureTypes") or [],
        dataDomains=preset.get("dataDomains") or [],
        genericTargets=preset.get("genericTargets") or [],
        linkageGroups=preset.get("linkageGroups") or [],
        replacementMode=preset.get("replacementMode") or "structured",
        created_at=preset.get("created_at") or _now_iso(),
        updated_at=preset.get("updated_at") or _now_iso(),
        readonly=bool(preset.get("readonly")),
    )


def _to_out_or_none(preset: dict[str, Any]) -> PresetOut | None:
    try:
        return _to_out(preset)
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
        "visualFeatureTypes": list(dict.fromkeys(preset.visualFeatureTypes)),
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
    all_out = [out for preset in presets if (out := _to_out_or_none(preset)) is not None]
    total = len(all_out)
    if page_size <= 0:
        return PresetsListResponse(presets=all_out, total=total, page=1, page_size=total)
    start = (page - 1) * page_size
    return PresetsListResponse(
        presets=all_out[start : start + page_size],
        total=total,
        page=page,
        page_size=page_size,
    )


def create(payload: PresetCreate, owner_id: str | None = None) -> PresetOut:
    with store_lock(_preset_store_path(owner_id)):
        presets = _load_store(owner_id)
        ts = _now_iso()
        row = {
            "id": str(uuid.uuid4()),
            "name": payload.name.strip(),
            "kind": payload.kind,
            "selectedEntityTypeIds": payload.selectedEntityTypeIds,
            "ocrHasTypes": payload.ocrHasTypes,
            "visualFeatureTypes": list(dict.fromkeys(payload.visualFeatureTypes)),
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
    """Return updated preset, or None when not found or readonly."""

    if is_builtin(preset_id):
        return None
    with store_lock(_preset_store_path(owner_id)):
        presets = _load_store(owner_id)
        for index, preset in enumerate(presets):
            if preset.get("id") != preset_id:
                continue
            if patch.name is not None:
                preset["name"] = patch.name.strip()
            if patch.kind is not None:
                preset["kind"] = patch.kind
            if patch.selectedEntityTypeIds is not None:
                preset["selectedEntityTypeIds"] = patch.selectedEntityTypeIds
            if patch.ocrHasTypes is not None:
                preset["ocrHasTypes"] = patch.ocrHasTypes
            if patch.visualFeatureTypes is not None:
                preset["visualFeatureTypes"] = list(dict.fromkeys(patch.visualFeatureTypes))
            if patch.dataDomains is not None:
                preset["dataDomains"] = patch.dataDomains
            if patch.genericTargets is not None:
                preset["genericTargets"] = patch.genericTargets
            if patch.linkageGroups is not None:
                preset["linkageGroups"] = patch.linkageGroups
            if patch.replacementMode is not None:
                preset["replacementMode"] = patch.replacementMode
            preset["updated_at"] = _now_iso()
            presets[index] = preset
            _save_store(presets, owner_id)
            return _to_out(preset)
    return None


def delete(preset_id: str, owner_id: str | None = None) -> bool:
    """Return True when a user-owned preset was deleted."""

    if is_builtin(preset_id):
        return False
    with store_lock(_preset_store_path(owner_id)):
        presets = _load_store(owner_id)
        next_presets = [preset for preset in presets if preset.get("id") != preset_id]
        if len(next_presets) == len(presets):
            return False
        _save_store(next_presets, owner_id)
    return True


def export_all(owner_id: str | None = None) -> dict[str, Any]:
    data = _merge_with_builtin_presets(_load_store(owner_id))
    return {
        "presets": data,
        "exported_at": datetime.now(UTC).isoformat(),
        "version": "2.0",
    }


def import_presets(request: PresetImportRequest, owner_id: str | None = None) -> int:
    """Return count of imported presets."""

    builtin_ids = _builtin_ids()
    incoming = [
        _import_item_to_row(preset)
        for preset in request.presets
        if preset.id not in builtin_ids
    ]
    if request.merge:
        with store_lock(_preset_store_path(owner_id)):
            existing = _load_store(owner_id)
            existing_ids = {preset.get("id") for preset in existing if isinstance(preset, dict)}
            imported_count = 0
            for preset in incoming:
                if preset.get("id") in existing_ids:
                    continue
                existing.append(preset)
                existing_ids.add(preset.get("id"))
                imported_count += 1
            _save_store(existing, owner_id)
        return imported_count

    with store_lock(_preset_store_path(owner_id)):
        _save_store(incoming, owner_id)
    return len(incoming)
