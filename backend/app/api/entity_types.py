"""
实体类型管理API — 路由层（thin wrapper）
基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》国家标准设计
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import require_auth
from app.models.schemas import MessageResponse, ToggleResponse
from app.services import entity_type_service
from app.services.entity_type_service import (
    CreateEntityTypeRequest,
    EntityTypeConfig,
    EntityTypesResponse,
    RegexTestRequest,
    RegexTestResult,
    TextTaxonomyResponse,
    UpdateEntityTypeRequest,
)

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
    owner_id: str = Depends(require_auth),
):
    """获取所有实体类型配置（page_size=0 返回全部）"""
    return entity_type_service.list_types(enabled_only, page, page_size, owner_id=owner_id)


@router.get("/custom-types/taxonomy", response_model=TextTaxonomyResponse)
async def get_text_taxonomy():
    """获取文本自定义识别项的 L1/L2 元数据分类树。"""
    return entity_type_service.get_text_taxonomy()


@router.get("/custom-types/{type_id}", response_model=EntityTypeConfig)
async def get_entity_type(type_id: str, owner_id: str = Depends(require_auth)):
    """获取单个实体类型配置"""
    result = entity_type_service.get_type(type_id, owner_id=owner_id)
    if result is None:
        raise HTTPException(status_code=404, detail="实体类型不存在")
    return result


@router.post("/custom-types", response_model=EntityTypeConfig)
async def create_entity_type(request: CreateEntityTypeRequest, owner_id: str = Depends(require_auth)):
    """创建新的实体类型"""
    return entity_type_service.create_type(request, owner_id=owner_id)


@router.put("/custom-types/{type_id}", response_model=EntityTypeConfig)
async def update_entity_type(
    type_id: str,
    request: UpdateEntityTypeRequest,
    owner_id: str = Depends(require_auth),
):
    """更新实体类型配置"""
    try:
        result = entity_type_service.update_type(type_id, request, owner_id=owner_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="实体类型不存在")
    return result


@router.delete("/custom-types/{type_id}", response_model=MessageResponse)
async def delete_entity_type(type_id: str, owner_id: str = Depends(require_auth)):
    """删除实体类型（预置类型只能禁用，不能删除）"""
    success, error = entity_type_service.delete_type(type_id, owner_id=owner_id)
    if not success:
        code = 404 if error == "实体类型不存在" else 400
        raise HTTPException(status_code=code, detail=error)
    return {"message": "删除成功"}


@router.post("/custom-types/{type_id}/toggle", response_model=ToggleResponse)
async def toggle_entity_type(type_id: str, owner_id: str = Depends(require_auth)):
    """切换实体类型的启用状态"""
    enabled = entity_type_service.toggle_type(type_id, owner_id=owner_id)
    if enabled is None:
        raise HTTPException(status_code=404, detail="实体类型不存在")
    return {"enabled": enabled}


@router.post("/custom-types/reset", response_model=MessageResponse)
async def reset_entity_types(owner_id: str = Depends(require_auth)):
    """重置为预置配置"""
    entity_type_service.reset_types(owner_id=owner_id)
    return {"message": "已重置为默认配置"}
