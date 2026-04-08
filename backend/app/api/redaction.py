"""
匿名化处理 API 路由
处理文档匿名化、对比等操作

Thin routing layer — business logic lives in
app.services.redaction_orchestrator.
"""
import logging

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Header, HTTPException
from typing import Optional

from app.core.idempotency import check_idempotency, save_idempotency
from app.core.audit import audit_log

from app.models.schemas import (
    RedactionRequest,
    RedactionResult,
    CompareData,
    VisionResult,
    APIResponse,
    PreviewEntityMapRequest,
    PreviewEntityMapResponse,
    PreviewImageRequest,
    PreviewImageResponse,
    EntityTypeListResponse,
    ReplacementModeListResponse,
    RedactionVersionsResponse,
    VisionDetectRequest,
    RedactionReport,
)

import app.services.redaction_orchestrator as _orch

router = APIRouter()


@router.post("/redaction/execute", response_model=RedactionResult)
async def execute_redaction(
    request: RedactionRequest,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    执行文档匿名化

    根据提供的实体列表和配置，对文档进行匿名化处理:
    - 文本类文档: 替换敏感文本
    - 图片类文档: 添加黑色遮罩
    """
    cached = check_idempotency(x_idempotency_key)
    if cached is not None:
        logger.warning("[execute_redaction] IDEMPOTENCY HIT key=%r file_id=%s", x_idempotency_key, request.file_id)
        return cached

    logger.info("[execute_redaction] START file_id=%s", request.file_id)

    try:
        response = await _orch.execute_redaction(request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    audit_log("redact", "file", request.file_id, detail={"mode": request.config.replacement_mode})
    save_idempotency(x_idempotency_key, response)
    return response


@router.post("/redaction/preview-map", response_model=PreviewEntityMapResponse)
async def preview_entity_map(body: PreviewEntityMapRequest):
    """根据当前勾选实体与替换模式，返回与 execute 一致的 entity_map（不写文件）。"""
    return _orch.preview_entity_map(body.entities, body.config)


@router.post("/redaction/{file_id}/preview-image", response_model=PreviewImageResponse)
async def preview_image_redaction(
    file_id: str,
    body: PreviewImageRequest,
    page: int = 1,
):
    try:
        return await _orch.preview_image(
            file_id=file_id,
            bounding_boxes=body.bounding_boxes,
            page=page,
            config=body.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/redaction/{file_id}/compare", response_model=CompareData)
async def get_comparison(file_id: str):
    """
    获取匿名化前后对比数据

    返回原始内容和匿名化后内容，用于前端展示对比视图
    """
    try:
        return await _orch.get_comparison(file_id)
    except ValueError as exc:
        detail = str(exc)
        if "尚未匿名化" in detail:
            raise HTTPException(status_code=400, detail=detail)
        raise HTTPException(status_code=404, detail=detail)


@router.get("/redaction/{file_id}/versions", response_model=RedactionVersionsResponse)
async def get_redaction_versions(file_id: str):
    """获取文件的匿名化版本历史"""
    try:
        return _orch.get_versions(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/redaction/{file_id}/vision", response_model=VisionResult)
async def detect_sensitive_regions(
    file_id: str,
    page: int = 1,
    request: Optional[VisionDetectRequest] = None,
):
    """
    对图片/扫描件进行视觉识别

    并行：OCR + HaS（文字）与 HaS Image（8081 YOLO，21 类隐私区域），合并去重。
    """
    try:
        return await _orch.detect_vision(
            file_id=file_id,
            page=page,
            selected_ocr_has_types=request.selected_ocr_has_types if request else None,
            selected_has_image_types=request.selected_has_image_types if request else None,
            has_request=request is not None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/redaction/entity-types", response_model=EntityTypeListResponse)
async def get_entity_types():
    """获取支持的实体类型列表"""
    return {"entity_types": _orch.get_entity_types_list()}


@router.get("/redaction/replacement-modes", response_model=ReplacementModeListResponse)
async def get_replacement_modes():
    """获取支持的替换模式列表"""
    return {"replacement_modes": _orch.get_replacement_modes_list()}


@router.get("/redaction/{file_id}/report", response_model=RedactionReport)
async def get_redaction_report(file_id: str):
    """获取匿名化质量报告"""
    try:
        return _orch.get_report(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
