# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
推理模型配置 API — 路由层（thin wrapper）
（视觉：HaS Image 8081 微服务；与文本 NER 分离）
"""

from typing import Optional
from fastapi import APIRouter, HTTPException

from app.models.schemas import ModelConfig, ModelConfigList
from app.services import model_config_service
from app.services.model_config_service import (
    # Re-export constants consumed by other modules
    DEFAULT_CONFIGS,
    VISION_BUILTIN_IDS,
    # Re-export functions consumed by other modules
    load_configs,
    save_configs,
)

router = APIRouter(prefix="/model-config", tags=["model-config"])


@router.get("", response_model=ModelConfigList)
async def get_model_configs():
    """获取所有模型配置"""
    return model_config_service.get_configs()


@router.get("/active", response_model=Optional[ModelConfig])
async def get_active_config():
    """获取当前激活的模型配置"""
    return model_config_service.get_active()


@router.post("/active/{config_id}")
async def set_active_config(config_id: str):
    """设置激活的模型配置"""
    success, msg = model_config_service.set_active(config_id)
    if not success:
        code = 404 if msg == "配置不存在" else 400
        raise HTTPException(status_code=code, detail=msg)
    return {"success": True, "active_id": config_id}


@router.post("", response_model=ModelConfig)
async def create_model_config(config: ModelConfig):
    """创建新的模型配置"""
    success, error = model_config_service.create_config(config)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return config


@router.put("/{config_id}", response_model=ModelConfig)
async def update_model_config(config_id: str, config: ModelConfig):
    """更新模型配置"""
    updated, error = model_config_service.update_config(config_id, config)
    if updated is None:
        raise HTTPException(status_code=404, detail=error)
    return updated


@router.delete("/{config_id}")
async def delete_model_config(config_id: str):
    """删除模型配置"""
    success, error = model_config_service.delete_config(config_id)
    if not success:
        code = 404 if error == "配置不存在" else 400
        raise HTTPException(status_code=code, detail=error)
    return {"success": True}


@router.post("/reset")
async def reset_model_configs():
    """重置为默认配置"""
    model_config_service.reset_configs()
    return {"success": True}


@router.post("/test/paddle-ocr")
async def test_paddle_ocr_service():
    """与推理后端列表中 PaddleOCR-VL 条目的「测试」同源。"""
    return await model_config_service.test_paddle_ocr()


@router.post("/test/{config_id}")
async def test_model_config(config_id: str):
    """测试模型配置连通性"""
    result, error = await model_config_service.test_config(config_id)
    if result is None:
        raise HTTPException(status_code=404, detail=error)
    return result
