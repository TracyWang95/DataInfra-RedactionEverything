"""
识别配置预设（Preset）API — 路由层（thin wrapper）
供 Playground / 批量向导 / 识别项配置页 共用同一套「识别类型 + 替换模式」组合。
"""

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    PresetCreate,
    PresetImportRequest,
    PresetOut,
    PresetUpdate,
    PresetsListResponse,
)
from app.services import preset_service

router = APIRouter()


@router.get("/presets/export")
async def export_presets():
    """导出所有预设配置为 JSON"""
    return preset_service.export_all()


@router.post("/presets/import")
async def import_presets(request: PresetImportRequest):
    """导入预设配置"""
    count = preset_service.import_presets(request)
    return {"message": "导入成功", "count": count}


@router.get("/presets", response_model=PresetsListResponse)
async def list_presets(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(0, ge=0, le=10000, description="每页条数，0=全量返回"),
):
    return preset_service.list_presets(page, page_size)


@router.post("/presets", response_model=PresetOut, status_code=201)
async def create_preset(body: PresetCreate):
    return preset_service.create(body)


@router.put("/presets/{preset_id}", response_model=PresetOut)
async def update_preset(preset_id: str, body: PresetUpdate):
    result = preset_service.update(preset_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="预设不存在")
    return result


@router.delete("/presets/{preset_id}")
async def delete_preset(preset_id: str):
    if not preset_service.delete(preset_id):
        raise HTTPException(status_code=404, detail="预设不存在")
    return {"ok": True}
