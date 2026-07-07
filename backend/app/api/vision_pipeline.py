"""Vision pipeline configuration API."""






from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import require_auth
from app.services import pipeline_service
from app.services.pipeline_service import (
    PipelineConfig,
    # Re-export models so existing imports keep working
    PipelineTypeConfig,
)

router = APIRouter()


@router.get("/vision-pipelines", response_model=list[PipelineConfig])
async def get_pipelines(enabled_only: bool = False, owner_id: str = Depends(require_auth)):
    """获取所有 Pipeline 配置"""
    return pipeline_service.list_pipelines(enabled_only, owner_id=owner_id)


@router.get("/vision-pipelines/{mode}", response_model=PipelineConfig)
async def get_pipeline(mode: str, owner_id: str = Depends(require_auth)):
    """获取指定 Pipeline 配置"""
    result = pipeline_service.get_pipeline(mode, owner_id=owner_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return result


@router.post("/vision-pipelines/{mode}/toggle")
async def toggle_pipeline(mode: str, owner_id: str = Depends(require_auth)):
    """Toggle a pipeline."""
    enabled = pipeline_service.toggle_pipeline(mode, owner_id=owner_id)
    if enabled is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return {"enabled": enabled}


@router.get("/vision-pipelines/{mode}/types", response_model=list[PipelineTypeConfig])
async def get_pipeline_types(
    mode: str,
    enabled_only: bool = True,
    owner_id: str = Depends(require_auth),
):
    """Return pipeline type configs."""
    result = pipeline_service.get_pipeline_types(mode, enabled_only, owner_id=owner_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return result


@router.post("/vision-pipelines/{mode}/types", response_model=PipelineTypeConfig)
async def add_pipeline_type(
    mode: str,
    request: PipelineTypeConfig,
    owner_id: str = Depends(require_auth),
):
    """添加 Pipeline 类型"""
    created, error = pipeline_service.add_pipeline_type(mode, request, owner_id=owner_id)
    if created is None:
        code = 404 if error == "Pipeline not found" else 400
        raise HTTPException(status_code=code, detail=error)
    return created


@router.put("/vision-pipelines/{mode}/types/{type_id}", response_model=PipelineTypeConfig)
async def update_pipeline_type(
    mode: str,
    type_id: str,
    request: PipelineTypeConfig,
    owner_id: str = Depends(require_auth),
):
    """更新 Pipeline 类型"""
    updated, error = pipeline_service.update_pipeline_type(mode, type_id, request, owner_id=owner_id)
    if updated is None:
        code = 404
        raise HTTPException(status_code=code, detail=error)
    return updated


@router.post("/vision-pipelines/{mode}/types/{type_id}/toggle")
async def toggle_pipeline_type(
    mode: str,
    type_id: str,
    owner_id: str = Depends(require_auth),
):
    """Toggle a pipeline type."""
    enabled, error = pipeline_service.toggle_pipeline_type(mode, type_id, owner_id=owner_id)
    if enabled is None:
        code = 404
        raise HTTPException(status_code=code, detail=error)
    return {"enabled": enabled}


@router.delete("/vision-pipelines/{mode}/types/{type_id}")
async def delete_pipeline_type(mode: str, type_id: str, owner_id: str = Depends(require_auth)):
    """删除 Pipeline 类型"""
    success, error = pipeline_service.delete_pipeline_type(mode, type_id, owner_id=owner_id)
    if not success:
        code = 404 if error == "Pipeline not found" else 400
        raise HTTPException(status_code=code, detail=error)
    return {"message": "删除成功"}


@router.post("/vision-pipelines/reset")
async def reset_pipelines(owner_id: str = Depends(require_auth)):
    """Reset all pipelines to defaults."""
    pipeline_service.reset_pipelines(owner_id=owner_id)
    return {"message": "已重置为默认配置"}

