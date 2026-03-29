"""
识别配置预设（Preset）API
供 Playground / 批量向导 / 识别项配置页 共用同一套「识别类型 + 替换模式」组合。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.persistence import load_json, save_json

router = APIRouter()


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


PresetKind = Literal["text", "vision", "full"]


class PresetPayload(BaseModel):
    """与前端 BatchWizardPersistedConfig 对齐的字段"""

    name: str = Field(..., min_length=1, max_length=200)
    kind: PresetKind = Field(
        default="full",
        description="text=仅文本链；vision=仅视觉链；full=文本+图像（兼容旧数据）",
    )
    selectedEntityTypeIds: List[str] = Field(default_factory=list)
    ocrHasTypes: List[str] = Field(default_factory=list)
    hasImageTypes: List[str] = Field(default_factory=list)
    replacementMode: Literal["structured", "smart", "mask"] = "structured"


class PresetCreate(PresetPayload):
    pass


class PresetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: PresetKind | None = None
    selectedEntityTypeIds: List[str] | None = None
    ocrHasTypes: List[str] | None = None
    hasImageTypes: List[str] | None = None
    replacementMode: Literal["structured", "smart", "mask"] | None = None


class PresetOut(PresetPayload):
    id: str
    created_at: str
    updated_at: str


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


class PresetsListResponse(BaseModel):
    presets: List[PresetOut]
    total: int
    page: int = 1
    page_size: int = 50


class PresetImportRequest(BaseModel):
    presets: list
    merge: bool = False  # True=merge with existing, False=replace all


@router.get("/presets/export")
async def export_presets():
    """导出所有预设配置为 JSON"""
    data = _load_store()
    return {"presets": data, "exported_at": datetime.now(timezone.utc).isoformat(), "version": "1.0"}


@router.post("/presets/import")
async def import_presets(request: PresetImportRequest):
    """导入预设配置"""
    if request.merge:
        existing = _load_store()
        existing_ids = {p.get("id") for p in existing if isinstance(p, dict)}
        for p in request.presets:
            if isinstance(p, dict) and p.get("id") not in existing_ids:
                existing.append(p)
        _save_store(existing)
    else:
        _save_store(request.presets)

    return {"message": "导入成功", "count": len(request.presets)}


@router.get("/presets", response_model=PresetsListResponse)
async def list_presets(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=100, description="每页条数"),
):
    presets = _load_store()
    all_out = [_to_out(p) for p in presets]
    total = len(all_out)
    start = (page - 1) * page_size
    page_items = all_out[start : start + page_size]
    return PresetsListResponse(
        presets=page_items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/presets", response_model=PresetOut, status_code=201)
async def create_preset(body: PresetCreate):
    presets = _load_store()
    pid = str(uuid.uuid4())
    ts = _now_iso()
    row = {
        "id": pid,
        "name": body.name.strip(),
        "kind": body.kind,
        "selectedEntityTypeIds": body.selectedEntityTypeIds,
        "ocrHasTypes": body.ocrHasTypes,
        "hasImageTypes": body.hasImageTypes,
        "replacementMode": body.replacementMode,
        "created_at": ts,
        "updated_at": ts,
    }
    presets.append(row)
    _save_store(presets)
    return _to_out(row)


@router.put("/presets/{preset_id}", response_model=PresetOut)
async def update_preset(preset_id: str, body: PresetUpdate):
    presets = _load_store()
    for i, p in enumerate(presets):
        if p.get("id") != preset_id:
            continue
        if body.name is not None:
            p["name"] = body.name.strip()
        if body.kind is not None:
            p["kind"] = body.kind
        if body.selectedEntityTypeIds is not None:
            p["selectedEntityTypeIds"] = body.selectedEntityTypeIds
        if body.ocrHasTypes is not None:
            p["ocrHasTypes"] = body.ocrHasTypes
        if body.hasImageTypes is not None:
            p["hasImageTypes"] = body.hasImageTypes
        if body.replacementMode is not None:
            p["replacementMode"] = body.replacementMode
        p["updated_at"] = _now_iso()
        presets[i] = p
        _save_store(presets)
        return _to_out(p)
    raise HTTPException(status_code=404, detail="预设不存在")


@router.delete("/presets/{preset_id}")
async def delete_preset(preset_id: str):
    presets = _load_store()
    nxt = [p for p in presets if p.get("id") != preset_id]
    if len(nxt) == len(presets):
        raise HTTPException(status_code=404, detail="预设不存在")
    _save_store(nxt)
    return {"ok": True}
