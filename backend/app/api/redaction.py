"""
匿名化处理 API 路由
处理文档匿名化、对比等操作

Thin routing layer — business logic lives in
app.services.redaction_orchestrator.
"""
import logging

logger = logging.getLogger(__name__)


from fastapi import APIRouter, Depends, Header, HTTPException

import app.services.file_management_service as _fms
import app.services.redaction_orchestrator as _orch
from app.core.audit import audit_log
from app.core.auth import require_auth
from app.core.idempotency import check_idempotency, save_idempotency
from app.models.schemas import (
    CompareData,
    EntityTypeListResponse,
    PreviewEntityMapRequest,
    PreviewEntityMapResponse,
    PreviewImageRequest,
    PreviewImageResponse,
    RedactionReport,
    RedactionRequest,
    RedactionResult,
    RedactionVersionsResponse,
    ReplacementModeListResponse,
    VisionDetectRequest,
    VisionResult,
)

router = APIRouter()


@router.post("/redaction/execute", response_model=RedactionResult)
async def execute_redaction(
    request: RedactionRequest,
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
    owner_id: str = Depends(require_auth),
):
    """
    执行文档匿名化

    根据提供的实体列表和配置，对文档进行匿名化处理
    - 文本类文档: 替换敏感文本
    - 图片类文档: 对敏感区域执行马赛克、模糊或纯色遮罩
    """
    scoped_idempotency_key = f"{owner_id}:{x_idempotency_key}" if x_idempotency_key else None
    cached = check_idempotency(scoped_idempotency_key)
    if cached is not None:
        logger.warning("[execute_redaction] IDEMPOTENCY HIT key=%r file_id=%s", x_idempotency_key, request.file_id)
        return cached

    logger.info("[execute_redaction] START file_id=%s", request.file_id)

    try:
        _fms.assert_file_owner(request.file_id, owner_id)
        response = await _orch.execute_redaction(request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    audit_log("redact", "file", request.file_id, detail={"mode": request.config.replacement_mode})
    save_idempotency(scoped_idempotency_key, response)
    return response


@router.post("/redaction/preview-map", response_model=PreviewEntityMapResponse)
@router.post(
    "/redaction/preview-entity-map",
    response_model=PreviewEntityMapResponse,
    include_in_schema=False,
)
async def preview_entity_map(body: PreviewEntityMapRequest):
    """Preview entity replacement mapping without writing files."""
    return _orch.preview_entity_map(body.entities, body.config)


@router.post("/redaction/{file_id}/preview-image", response_model=PreviewImageResponse)
async def preview_image_redaction(
    file_id: str,
    body: PreviewImageRequest,
    page: int = 1,
    owner_id: str = Depends(require_auth),
):
    try:
        _fms.assert_file_owner(file_id, owner_id)
        return await _orch.preview_image(
            file_id=file_id,
            bounding_boxes=body.bounding_boxes,
            page=page,
            config=body.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/redaction/{file_id}/compare", response_model=CompareData)
async def get_comparison(file_id: str, owner_id: str = Depends(require_auth)):
    """
    获取匿名化前后对比数据

    返回原始内容和匿名化后内容，用于前端展示对比视图
    """
    try:
        _fms.assert_file_owner(file_id, owner_id)
        return await _orch.get_comparison(file_id)
    except ValueError as exc:
        detail = str(exc)
        if "has not been redacted" in detail:
            raise HTTPException(status_code=400, detail=detail)
        raise HTTPException(status_code=404, detail=detail)


@router.get("/redaction/{file_id}/versions", response_model=RedactionVersionsResponse)
async def get_redaction_versions(file_id: str, owner_id: str = Depends(require_auth)):
    """获取文件的匿名化版本历史"""
    try:
        _fms.assert_file_owner(file_id, owner_id)
        return _orch.get_versions(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/redaction/{file_id}/vision", response_model=VisionResult)
async def detect_sensitive_regions(
    file_id: str,
    page: int = 1,
    force: bool = False,
    include_result_image: bool = True,
    request: VisionDetectRequest | None = None,
    owner_id: str = Depends(require_auth),
):
    """Run visual recognition for one page."""
    # PaddleOCR-VL + HaS Text handle OCR/semantics.
    # LocateAnything handles all visual features.
    # The orchestrator merges and deduplicates both stages.


    try:
        _fms.assert_file_owner(file_id, owner_id)
        return await _orch.detect_vision(
            file_id=file_id,
            page=page,
            selected_ocr_has_types=request.selected_ocr_has_types if request else None,
            selected_visual_feature_types=request.selected_visual_feature_types if request else None,
            has_request=request is not None,
            force=force,
            include_result_image=include_result_image,
            owner_id=owner_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/redaction/entity-types", response_model=EntityTypeListResponse)
async def get_entity_types():
    """Return supported entity types."""
    return {"entity_types": _orch.get_entity_types_list()}


@router.get("/redaction/replacement-modes", response_model=ReplacementModeListResponse)
async def get_replacement_modes():
    """Return supported replacement modes."""
    return {"replacement_modes": _orch.get_replacement_modes_list()}


@router.get("/redaction/{file_id}/report", response_model=RedactionReport)
async def get_redaction_report(file_id: str, owner_id: str = Depends(require_auth)):
    """Return redaction quality report."""
    try:
        _fms.assert_file_owner(file_id, owner_id)
        return _orch.get_report(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

