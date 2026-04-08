"""
图像识别 Pipeline 配置 API — 路由层（thin wrapper）
1. OCR + HaS：文字类敏感信息
2. HaS Image：端侧 YOLO 分割（8081 微服务），21 类隐私区域
"""

from typing import List
from fastapi import APIRouter, HTTPException

from app.services import pipeline_service
from app.services.pipeline_service import (
    # Re-export models so existing imports keep working
    PipelineMode,
    PipelineTypeConfig,
    PipelineConfig,
    # Re-export data / helpers consumed by other modules
    PRESET_PIPELINES,
    PRESET_OCR_HAS_TYPES,
    PRESET_HAS_IMAGE_TYPES,
    merge_pipeline_disk_snapshot,
    pipelines_db,
    get_pipeline_types_for_mode,
)

router = APIRouter()


@router.get("/vision-pipelines", response_model=List[PipelineConfig])
async def get_pipelines(enabled_only: bool = False):
    """获取所有 Pipeline 配置"""
    return pipeline_service.list_pipelines(enabled_only)


@router.get("/vision-pipelines/{mode}", response_model=PipelineConfig)
async def get_pipeline(mode: str):
    """获取指定 Pipeline 配置"""
    result = pipeline_service.get_pipeline(mode)
    if result is None:
        raise HTTPException(status_code=404, detail="Pipeline 不存在")
    return result


@router.post("/vision-pipelines/{mode}/toggle")
async def toggle_pipeline(mode: str):
    """切换 Pipeline 启用状态"""
    enabled = pipeline_service.toggle_pipeline(mode)
    if enabled is None:
        raise HTTPException(status_code=404, detail="Pipeline 不存在")
    return {"enabled": enabled}


@router.get("/vision-pipelines/{mode}/types", response_model=List[PipelineTypeConfig])
async def get_pipeline_types(mode: str, enabled_only: bool = True):
    """获取指定 Pipeline 的类型配置"""
    result = pipeline_service.get_pipeline_types(mode, enabled_only)
    if result is None:
        raise HTTPException(status_code=404, detail="Pipeline 不存在")
    return result


@router.post("/vision-pipelines/{mode}/types", response_model=PipelineTypeConfig)
async def add_pipeline_type(mode: str, request: PipelineTypeConfig):
    """添加 Pipeline 类型"""
    created, error = pipeline_service.add_pipeline_type(mode, request)
    if created is None:
        code = 404 if error == "Pipeline 不存在" else 400
        raise HTTPException(status_code=code, detail=error)
    return created


@router.put("/vision-pipelines/{mode}/types/{type_id}", response_model=PipelineTypeConfig)
async def update_pipeline_type(mode: str, type_id: str, request: PipelineTypeConfig):
    """更新 Pipeline 类型"""
    updated, error = pipeline_service.update_pipeline_type(mode, type_id, request)
    if updated is None:
        code = 404
        raise HTTPException(status_code=code, detail=error)
    return updated


@router.post("/vision-pipelines/{mode}/types/{type_id}/toggle")
async def toggle_pipeline_type(mode: str, type_id: str):
    """切换 Pipeline 类型启用状态"""
    enabled, error = pipeline_service.toggle_pipeline_type(mode, type_id)
    if enabled is None:
        code = 404
        raise HTTPException(status_code=code, detail=error)
    return {"enabled": enabled}


@router.delete("/vision-pipelines/{mode}/types/{type_id}")
async def delete_pipeline_type(mode: str, type_id: str):
    """删除 Pipeline 类型"""
    success, error = pipeline_service.delete_pipeline_type(mode, type_id)
    if not success:
        code = 404 if error == "Pipeline 不存在" else 400
        raise HTTPException(status_code=code, detail=error)
    return {"message": "删除成功"}


@router.post("/vision-pipelines/reset")
async def reset_pipelines():
    """重置所有 Pipeline 配置为默认"""
    pipeline_service.reset_pipelines()
    return {"message": "已重置为默认配置"}
