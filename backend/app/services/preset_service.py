"""
识别配置预设（Preset） — 业务逻辑层
供 Playground / 批量向导 / 识别项配置页 共用同一套「识别类型 + 替换模式」组合。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.persistence import load_json, save_json
from app.models.schemas import (
    PresetCreate,
    PresetImportRequest,
    PresetOut,
    PresetUpdate,
    PresetsListResponse,
)


# ── 内部工具 ─────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_store() -> list[dict[str, Any]]:
    raw = load_json(settings.PRESET_STORE_PATH, default=None)
    if raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, dict) and "presets" in raw:
        return list(raw["presets"])
    return []


def _save_store(presets: list[dict[str, Any]]) -> None:
    save_json(settings.PRESET_STORE_PATH, presets)


def _to_out(p: dict[str, Any]) -> PresetOut:
    return PresetOut(
        id=p["id"],
        name=p["name"],
        kind=p.get("kind") or "full",
        selectedEntityTypeIds=p.get("selectedEntityTypeIds") or [],
        ocrHasTypes=p.get("ocrHasTypes") or [],
        hasImageTypes=p.get("hasImageTypes") or [],
        replacementMode=p.get("replacementMode") or "structured",
        created_at=p.get("created_at") or _now_iso(),
        updated_at=p.get("updated_at") or _now_iso(),
    )


# ── 业务方法 ──────────────────────────────────────────────

def list_presets(page: int = 1, page_size: int = 0) -> PresetsListResponse:
    presets = _load_store()
    all_out = [_to_out(p) for p in presets]
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


def create(payload: PresetCreate) -> PresetOut:
    presets = _load_store()
    pid = str(uuid.uuid4())
    ts = _now_iso()
    row = {
        "id": pid,
        "name": payload.name.strip(),
        "kind": payload.kind,
        "selectedEntityTypeIds": payload.selectedEntityTypeIds,
        "ocrHasTypes": payload.ocrHasTypes,
        "hasImageTypes": payload.hasImageTypes,
        "replacementMode": payload.replacementMode,
        "created_at": ts,
        "updated_at": ts,
    }
    presets.append(row)
    _save_store(presets)
    return _to_out(row)


def update(preset_id: str, patch: PresetUpdate) -> PresetOut | None:
    """Returns updated PresetOut, or None if not found."""
    presets = _load_store()
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
        if patch.replacementMode is not None:
            p["replacementMode"] = patch.replacementMode
        p["updated_at"] = _now_iso()
        presets[i] = p
        _save_store(presets)
        return _to_out(p)
    return None


def delete(preset_id: str) -> bool:
    """Returns True if deleted, False if not found."""
    presets = _load_store()
    nxt = [p for p in presets if p.get("id") != preset_id]
    if len(nxt) == len(presets):
        return False
    _save_store(nxt)
    return True


def export_all() -> dict:
    data = _load_store()
    return {"presets": data, "exported_at": datetime.now(timezone.utc).isoformat(), "version": "1.0"}


def import_presets(request: PresetImportRequest) -> int:
    """Returns count of imported presets."""
    if request.merge:
        existing = _load_store()
        existing_ids = {p.get("id") for p in existing if isinstance(p, dict)}
        for p in request.presets:
            if isinstance(p, dict) and p.get("id") not in existing_ids:
                existing.append(p)
        _save_store(existing)
    else:
        _save_store(request.presets)
    return len(request.presets)
