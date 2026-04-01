"""
脱敏处理 API 路由
处理文档脱敏、对比等操作
"""
import logging
import base64
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional

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
)
from app.services.redactor import Redactor, build_preview_entity_map
from app.services.vision_service import VisionService
from app.core.persistence import to_jsonable
from app.api.files import _file_store_lock, file_store

router = APIRouter()


class VisionDetectRequest(BaseModel):
    """视觉识别请求体"""
    selected_ocr_has_types: Optional[List[str]] = None
    selected_has_image_types: Optional[List[str]] = None


@router.post("/redaction/execute", response_model=RedactionResult)
async def execute_redaction(
    request: RedactionRequest,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    执行文档脱敏

    根据提供的实体列表和配置，对文档进行脱敏处理:
    - 文本类文档: 替换敏感文本
    - 图片类文档: 添加黑色遮罩
    """
    import time as _time
    _t0 = _time.perf_counter()

    cached = check_idempotency(x_idempotency_key)
    if cached is not None:
        return cached

    file_id = request.file_id

    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    file_info = file_store[file_id]
    
    redactor = Redactor()
    result = await redactor.redact(
        file_info=file_info,
        entities=request.entities,
        bounding_boxes=request.bounding_boxes,
        config=request.config,
    )
    
    # 更新文件存储：脱敏条数 + 本次实际提交的实体/框（识别阶段可能未写入 file_store，导致历史一直为 0）
    async with _file_store_lock:
        info = file_store.get(file_id)
        if info is None:
            # 文件已被删除，不复活记录
            logger.warning("file %s was deleted during redaction, skipping store update", file_id)
        else:
            info["output_path"] = result.get("output_path")
            info["entity_map"] = result.get("entity_map", {})
            info["redacted_count"] = int(result.get("redacted_count", 0))
            if request.bounding_boxes:
                info["bounding_boxes"] = {1: to_jsonable(request.bounding_boxes)}
            if request.entities:
                info["entities"] = to_jsonable(request.entities)
            # 版本历史追踪
            version_entry = {
                "version": len(info.get("redaction_history", [])) + 1,
                "output_file_id": result["output_file_id"],
                "output_path": result.get("output_path"),
                "redacted_count": result["redacted_count"],
                "entity_map": result.get("entity_map", {}),
                "mode": request.config.replacement_mode.value if hasattr(request.config.replacement_mode, 'value') else str(request.config.replacement_mode),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if "redaction_history" not in info:
                info["redaction_history"] = []
            info["redaction_history"].append(version_entry)
            file_store.set(file_id, info)
    audit_log("redact", "file", file_id, detail={"mode": request.config.replacement_mode})

    response = RedactionResult(
        file_id=file_id,
        output_file_id=result["output_file_id"],
        redacted_count=result["redacted_count"],
        entity_map=result.get("entity_map", {}),
        download_url=f"/api/v1/files/{file_id}/download?redacted=true",
        output_path=result.get("output_path"),
    )
    save_idempotency(x_idempotency_key, response)

    # Prometheus: 脱敏延迟 + 计数
    from app.core.metrics import REDACTION_DURATION, REDACTION_COUNT
    ft = (file_store.get(file_id) or {}).get("file_type", "unknown")
    REDACTION_DURATION.labels(file_type=str(ft)).observe(_time.perf_counter() - _t0)
    mode_val = request.config.replacement_mode.value if hasattr(request.config.replacement_mode, 'value') else str(request.config.replacement_mode)
    REDACTION_COUNT.labels(replacement_mode=mode_val).inc()

    return response


@router.post("/redaction/preview-map", response_model=PreviewEntityMapResponse)
async def preview_entity_map(body: PreviewEntityMapRequest):
    """根据当前勾选实体与替换模式，返回与 execute 一致的 entity_map（不写文件）。"""
    em = build_preview_entity_map(body.entities, body.config)
    return PreviewEntityMapResponse(entity_map=em)


@router.post("/redaction/{file_id}/preview-image", response_model=PreviewImageResponse)
async def preview_image_redaction(
    file_id: str,
    body: PreviewImageRequest,
    page: int = 1,
):
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="file not found")

    file_info = file_store[file_id]
    vision_service = VisionService()
    image_bytes = await vision_service.preview_redaction(
        file_path=file_info["file_path"],
        file_type=file_info["file_type"],
        bounding_boxes=body.bounding_boxes,
        page=page,
        image_method=body.config.image_redaction_method or "fill",
        strength=int(body.config.image_redaction_strength or 25),
        fill_color=body.config.image_fill_color or "#000000",
    )
    return PreviewImageResponse(
        file_id=file_id,
        page=page,
        image_base64=base64.b64encode(image_bytes).decode("ascii"),
    )


@router.get("/redaction/{file_id}/compare", response_model=CompareData)
async def get_comparison(file_id: str):
    """
    获取脱敏前后对比数据
    
    返回原始内容和脱敏后内容，用于前端展示对比视图
    """
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    file_info = file_store[file_id]
    
    if "output_path" not in file_info:
        raise HTTPException(status_code=400, detail="文件尚未脱敏")
    
    redactor = Redactor()
    compare_data = await redactor.get_comparison(file_info)
    
    return CompareData(
        file_id=file_id,
        original_content=compare_data["original"],
        redacted_content=compare_data["redacted"],
        changes=compare_data.get("changes", []),
    )


@router.get("/redaction/{file_id}/versions", response_model=RedactionVersionsResponse)
async def get_redaction_versions(file_id: str):
    """获取文件的脱敏版本历史"""
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    history = file_store[file_id].get("redaction_history", [])
    return {"file_id": file_id, "versions": history, "total": len(history)}


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
    # Read snapshot under lock
    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info:
            raise HTTPException(status_code=404, detail="文件不存在")
        snapshot = dict(file_info)

    # 获取两个 Pipeline 的类型配置
    from app.api.vision_pipeline import get_pipeline_types_for_mode, pipelines_db

    # 获取系统配置中启用的类型
    all_ocr_has_types = get_pipeline_types_for_mode("ocr_has")
    all_has_image_types = get_pipeline_types_for_mode("has_image")

    selected_ocr_has_ids: Optional[set[str]] = None
    selected_has_image_ids: Optional[set[str]] = None
    if request is None:
        selected_has_image_ids = set()
    else:
        if request.selected_ocr_has_types is not None:
            selected_ocr_has_ids = set(request.selected_ocr_has_types or [])
        if request.selected_has_image_types is not None:
            selected_has_image_ids = set(request.selected_has_image_types or [])
        else:
            selected_has_image_ids = set()

    if selected_ocr_has_ids is not None:
        ocr_has_types = [t for t in all_ocr_has_types if t.id in selected_ocr_has_ids]
    else:
        ocr_has_types = all_ocr_has_types

    if selected_has_image_ids is not None:
        has_image_types = [t for t in all_has_image_types if t.id in selected_has_image_ids]
    else:
        has_image_types = all_has_image_types

    ocr_has_enabled = pipelines_db.get("ocr_has", None) and pipelines_db["ocr_has"].enabled and len(ocr_has_types) > 0
    has_image_enabled = (
        pipelines_db.get("has_image", None)
        and pipelines_db["has_image"].enabled
        and len(has_image_types) > 0
    )

    if pipelines_db.get("ocr_has") and pipelines_db["ocr_has"].enabled and len(ocr_has_types) == 0:
        logger.info(
            "OCR+HaS 跳过：前端传入的类型列表为空（selected_ocr_has_types=[] 表示不跑文字 OCR）。"
            "若希望识别文字，请在侧栏勾选至少一类 OCR+HaS 类型，或清除 localStorage 键 ocrHasTypes 后刷新。"
        )

    logger.info("OCR+HaS selected: %s", [t.id for t in ocr_has_types] if ocr_has_types else [])
    logger.info("HaS Image selected: %s", [t.id for t in has_image_types] if has_image_types else [])

    # Long-running vision detection outside lock
    vision_service = VisionService()
    bounding_boxes, result_image = await vision_service.detect_with_dual_pipeline(
        file_path=snapshot["file_path"],
        file_type=snapshot["file_type"],
        page=page,
        ocr_has_types=ocr_has_types if ocr_has_enabled else None,
        has_image_types=has_image_types if has_image_enabled else None,
    )

    # Write back under lock
    async with _file_store_lock:
        if file_id in file_store:
            info = file_store.get(file_id)
            if "bounding_boxes" not in info:
                info["bounding_boxes"] = {}
            info["bounding_boxes"][page] = bounding_boxes
            file_store.set(file_id, info)

    return VisionResult(
        file_id=file_id,
        page=page,
        bounding_boxes=bounding_boxes,
        result_image=result_image,
    )


@router.get("/redaction/entity-types", response_model=EntityTypeListResponse)
async def get_entity_types():
    """获取支持的实体类型列表"""
    from app.models.schemas import EntityType
    
    entity_types = [
        {"value": EntityType.PERSON.value, "label": "人名", "color": "#F59E0B"},
        {"value": EntityType.ORG.value, "label": "机构/公司", "color": "#3B82F6"},
        {"value": EntityType.ID_CARD.value, "label": "身份证号", "color": "#EF4444"},
        {"value": EntityType.PHONE.value, "label": "电话号码", "color": "#10B981"},
        {"value": EntityType.ADDRESS.value, "label": "地址", "color": "#8B5CF6"},
        {"value": EntityType.BANK_CARD.value, "label": "银行卡号", "color": "#EC4899"},
        {"value": EntityType.CASE_NUMBER.value, "label": "案件编号", "color": "#6366F1"},
        {"value": EntityType.DATE.value, "label": "日期", "color": "#14B8A6"},
        {"value": EntityType.AMOUNT.value, "label": "金额", "color": "#F97316"},
        {"value": EntityType.CUSTOM.value, "label": "自定义", "color": "#6B7280"},
    ]
    
    return {"entity_types": entity_types}


@router.get("/redaction/replacement-modes", response_model=ReplacementModeListResponse)
async def get_replacement_modes():
    """获取支持的替换模式列表"""
    from app.models.schemas import ReplacementMode
    
    modes = [
        {
            "value": ReplacementMode.SMART.value,
            "label": "智能替换",
            "description": "将敏感信息替换为语义化的标识，如 '当事人甲'、'公司A'",
        },
        {
            "value": ReplacementMode.STRUCTURED.value,
            "label": "结构化语义标签",
            "description": "用结构化标签替换敏感信息，保留层级语义与指代关系",
        },
        {
            "value": ReplacementMode.MASK.value,
            "label": "掩码替换",
            "description": "将敏感信息替换为 *** 或部分隐藏，如 '张**'、'138****1234'",
        },
        {
            "value": ReplacementMode.CUSTOM.value,
            "label": "自定义替换",
            "description": "手动指定每个敏感信息的替换文本",
        },
    ]
    
    return {"replacement_modes": modes}


class RedactionReport(BaseModel):
    """脱敏质量报告"""
    file_id: str
    filename: str
    total_entities: int
    redacted_entities: int
    entity_type_distribution: dict[str, int] = Field(default_factory=dict, description="各类型实体数量")
    confidence_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="置信度分布：high(>0.8), medium(0.5-0.8), low(<0.5)"
    )
    source_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="来源分布：llm, regex, manual, has"
    )
    coverage_rate: float = Field(default=0.0, description="脱敏覆盖率（已脱敏/总识别）")
    redaction_mode: str = ""
    created_at: str = ""


@router.get("/redaction/{file_id}/report", response_model=RedactionReport)
async def get_redaction_report(file_id: str):
    """获取脱敏质量报告"""
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")

    file_info = file_store[file_id]
    entities = file_info.get("entities", [])

    # Count by type
    type_dist: dict[str, int] = {}
    confidence_dist = {"high": 0, "medium": 0, "low": 0}
    source_dist: dict[str, int] = {}

    total = 0
    selected = 0
    for e in entities:
        total += 1
        # Handle both dict and Pydantic model
        if isinstance(e, dict):
            etype = e.get("type", "UNKNOWN")
            conf = e.get("confidence", 1.0)
            src = e.get("source", "unknown")
            sel = e.get("selected", True)
        else:
            etype = getattr(e, "type", "UNKNOWN")
            conf = getattr(e, "confidence", 1.0)
            src = getattr(e, "source", "unknown") or "unknown"
            sel = getattr(e, "selected", True)

        type_dist[str(etype)] = type_dist.get(str(etype), 0) + 1
        source_dist[str(src)] = source_dist.get(str(src), 0) + 1

        if conf >= 0.8:
            confidence_dist["high"] += 1
        elif conf >= 0.5:
            confidence_dist["medium"] += 1
        else:
            confidence_dist["low"] += 1

        if sel:
            selected += 1

    # Also count bounding boxes
    bb_total = 0
    bbs = file_info.get("bounding_boxes", {})
    if isinstance(bbs, dict):
        for page_bbs in bbs.values():
            if isinstance(page_bbs, list):
                bb_total += len(page_bbs)
    elif isinstance(bbs, list):
        bb_total = len(bbs)

    redacted_count = file_info.get("redacted_count", 0)
    total_detected = total + bb_total
    coverage = (redacted_count / total_detected * 100) if total_detected > 0 else 0.0

    return RedactionReport(
        file_id=file_id,
        filename=file_info.get("original_filename", ""),
        total_entities=total_detected,
        redacted_entities=redacted_count,
        entity_type_distribution=type_dist,
        confidence_distribution=confidence_dist,
        source_distribution=source_dist,
        coverage_rate=round(coverage, 1),
        redaction_mode=str(file_info.get("replacement_mode", "")),
        created_at=file_info.get("created_at", ""),
    )
