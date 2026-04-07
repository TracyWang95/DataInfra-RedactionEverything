# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
实体类型管理API — 路由层（thin wrapper）
基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》国家标准设计
"""

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import ToggleResponse, MessageResponse
from app.services.entity_type_service import (
    EntityTypeConfig,
    EntityTypesResponse,
    CreateEntityTypeRequest,
    UpdateEntityTypeRequest,
    RegexTestRequest,
    RegexTestResult,
)
from app.services import entity_type_service


router = APIRouter()


@router.post("/custom-types/regex-test", response_model=RegexTestResult)
async def test_regex(request: RegexTestRequest):
    """测试正则表达式匹配效果"""
    return entity_type_service.test_regex(request.pattern, request.test_text)


@router.get("/custom-types", response_model=EntityTypesResponse)
async def get_entity_types(
    enabled_only: bool = Query(False, description="是否只返回启用的类型"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(0, ge=0, le=10000, description="每页条数，0=全量返回"),
):
    """获取所有实体类型配置（page_size=0 返回全部）"""
    return entity_type_service.list_types(enabled_only, page, page_size)


@router.get("/custom-types/{type_id}", response_model=EntityTypeConfig)
async def get_entity_type(type_id: str):
    """获取单个实体类型配置"""
    result = entity_type_service.get_type(type_id)
    if result is None:
        raise HTTPException(status_code=404, detail="实体类型不存在")
    return result


@router.post("/custom-types", response_model=EntityTypeConfig)
async def create_entity_type(request: CreateEntityTypeRequest):
    """创建新的实体类型"""
    return entity_type_service.create_type(request)


@router.put("/custom-types/{type_id}", response_model=EntityTypeConfig)
async def update_entity_type(type_id: str, request: UpdateEntityTypeRequest):
    """更新实体类型配置"""
    result = entity_type_service.update_type(type_id, request)
    if result is None:
        raise HTTPException(status_code=404, detail="实体类型不存在")
    return result


@router.delete("/custom-types/{type_id}", response_model=MessageResponse)
async def delete_entity_type(type_id: str):
    """删除实体类型（预置类型只能禁用，不能删除）"""
    success, error = entity_type_service.delete_type(type_id)
    if not success:
        code = 404 if error == "实体类型不存在" else 400
        raise HTTPException(status_code=code, detail=error)
    return {"message": "删除成功"}


@router.post("/custom-types/{type_id}/toggle", response_model=ToggleResponse)
async def toggle_entity_type(type_id: str):
    """切换实体类型的启用状态"""
    enabled = entity_type_service.toggle_type(type_id)
    if enabled is None:
        raise HTTPException(status_code=404, detail="实体类型不存在")
    return {"enabled": enabled}


@router.post("/custom-types/reset", response_model=MessageResponse)
async def reset_entity_types():
    """重置为预置配置"""
    entity_type_service.reset_types()
    return {"message": "已重置为默认配置"}
