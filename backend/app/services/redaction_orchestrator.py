# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
匿名化编排服务层 — 从 api/redaction.py 提取。

在路由处理器与底层 Redactor/VisionService 之间的编排层：
- 匿名化执行与 file_store 更新
- entity_map 管理与版本追踪
- 报告生成（实体/bbox 统计）
- 视觉检测编排
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.persistence import to_jsonable
from app.models.schemas import (
    CompareData,
    Entity,
    EntityType,
    PreviewEntityMapResponse,
    PreviewImageResponse,
    RedactionConfig,
    RedactionReport,
    RedactionRequest,
    RedactionResult,
    RedactionVersionsResponse,
    ReplacementMode,
    VisionResult,
)
from app.services.redactor import Redactor, build_preview_entity_map
from app.services.vision_service import VisionService

logger = logging.getLogger(__name__)


def _get_file_store():
    from app.services.file_management_service import file_store
    return file_store


def _get_file_store_lock():
    from app.services.file_management_service import _file_store_lock
    return _file_store_lock


# ---------------------------------------------------------------------------
# Redaction execution
# ---------------------------------------------------------------------------

async def execute_redaction(request: RedactionRequest) -> RedactionResult:
    """
    Execute document redaction and update file_store.
    Returns RedactionResult. Raises ValueError if file not found.
    """
    import time as _time
    _t0 = _time.perf_counter()

    file_store = _get_file_store()
    lock = _get_file_store_lock()
    file_id = request.file_id

    if file_id not in file_store:
        raise ValueError("文件不存在")

    file_info = file_store[file_id]

    redactor = Redactor()
    result = await redactor.redact(
        file_info=file_info,
        entities=request.entities,
        bounding_boxes=request.bounding_boxes,
        config=request.config,
    )

    # 更新文件存储
    async with lock:
        info = file_store.get(file_id)
        if info is None:
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

    response = RedactionResult(
        file_id=file_id,
        output_file_id=result["output_file_id"],
        redacted_count=result["redacted_count"],
        entity_map=result.get("entity_map", {}),
        download_url=f"/api/v1/files/{file_id}/download?redacted=true",
        output_path=result.get("output_path"),
    )

    # Prometheus metrics
    from app.core.metrics import REDACTION_DURATION, REDACTION_COUNT
    ft = (file_store.get(file_id) or {}).get("file_type", "unknown")
    REDACTION_DURATION.labels(file_type=str(ft)).observe(_time.perf_counter() - _t0)
    mode_val = request.config.replacement_mode.value if hasattr(request.config.replacement_mode, 'value') else str(request.config.replacement_mode)
    REDACTION_COUNT.labels(replacement_mode=mode_val).inc()

    return response


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def preview_entity_map(entities: list, config: RedactionConfig) -> PreviewEntityMapResponse:
    """Build preview entity_map without writing files."""
    em = build_preview_entity_map(entities, config)
    return PreviewEntityMapResponse(entity_map=em)


async def preview_image(
    file_id: str,
    bounding_boxes: list,
    page: int,
    config: Any,
) -> PreviewImageResponse:
    """Generate preview redaction image. Raises ValueError if file not found."""
    file_store = _get_file_store()

    if file_id not in file_store:
        raise ValueError("file not found")

    file_info = file_store[file_id]
    vision_service = VisionService()
    image_bytes = await vision_service.preview_redaction(
        file_path=file_info["file_path"],
        file_type=file_info["file_type"],
        bounding_boxes=bounding_boxes,
        page=page,
        image_method=config.image_redaction_method or "fill",
        strength=int(config.image_redaction_strength or 25),
        fill_color=config.image_fill_color or "#000000",
    )
    return PreviewImageResponse(
        file_id=file_id,
        page=page,
        image_base64=base64.b64encode(image_bytes).decode("ascii"),
    )


# ---------------------------------------------------------------------------
# Comparison & version history
# ---------------------------------------------------------------------------

async def get_comparison(file_id: str) -> CompareData:
    """Get redaction before/after comparison. Raises ValueError on errors."""
    file_store = _get_file_store()

    if file_id not in file_store:
        raise ValueError("文件不存在")

    file_info = file_store[file_id]

    if "output_path" not in file_info:
        raise ValueError("文件尚未匿名化")

    redactor = Redactor()
    compare_data = await redactor.get_comparison(file_info)

    return CompareData(
        file_id=file_id,
        original_content=compare_data["original"],
        redacted_content=compare_data["redacted"],
        changes=compare_data.get("changes", []),
    )


def get_versions(file_id: str) -> dict[str, Any]:
    """Get redaction version history. Raises ValueError if file not found."""
    file_store = _get_file_store()

    if file_id not in file_store:
        raise ValueError("文件不存在")

    history = file_store[file_id].get("redaction_history", [])
    return {"file_id": file_id, "versions": history, "total": len(history)}


# ---------------------------------------------------------------------------
# Vision detection
# ---------------------------------------------------------------------------

async def detect_vision(
    file_id: str,
    page: int = 1,
    selected_ocr_has_types: Optional[list[str]] = None,
    selected_has_image_types: Optional[list[str]] = None,
    has_request: bool = True,
) -> VisionResult:
    """
    Run dual-pipeline vision detection. Raises ValueError if file not found.
    `has_request` indicates whether a request body was provided (affects defaults).
    """
    file_store = _get_file_store()
    lock = _get_file_store_lock()

    async with lock:
        file_info = file_store.get(file_id)
        if not file_info:
            raise ValueError("文件不存在")
        snapshot = dict(file_info)

    # 获取两个 Pipeline 的类型配置
    from app.services.pipeline_service import get_pipeline_types_for_mode, pipelines_db

    all_ocr_has_types = get_pipeline_types_for_mode("ocr_has")
    all_has_image_types = get_pipeline_types_for_mode("has_image")

    sel_ocr_ids: Optional[set[str]] = None
    sel_img_ids: Optional[set[str]] = None

    if not has_request:
        sel_img_ids = set()
    else:
        if selected_ocr_has_types is not None:
            sel_ocr_ids = set(selected_ocr_has_types or [])
        if selected_has_image_types is not None:
            sel_img_ids = set(selected_has_image_types or [])
        else:
            sel_img_ids = set()

    if sel_ocr_ids is not None:
        ocr_has_types = [t for t in all_ocr_has_types if t.id in sel_ocr_ids]
    else:
        ocr_has_types = all_ocr_has_types

    if sel_img_ids is not None:
        has_image_types = [t for t in all_has_image_types if t.id in sel_img_ids]
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

    vision_service = VisionService()
    bounding_boxes, result_image = await vision_service.detect_with_dual_pipeline(
        file_path=snapshot["file_path"],
        file_type=snapshot["file_type"],
        page=page,
        ocr_has_types=ocr_has_types if ocr_has_enabled else None,
        has_image_types=has_image_types if has_image_enabled else None,
    )

    # Write back under lock
    async with lock:
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


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def get_report(file_id: str) -> RedactionReport:
    """Generate redaction quality report. Raises ValueError if file not found."""
    file_store = _get_file_store()

    if file_id not in file_store:
        raise ValueError("文件不存在")

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


# ---------------------------------------------------------------------------
# Entity types / replacement modes reference data
# ---------------------------------------------------------------------------

def get_entity_types_list() -> list[dict[str, Any]]:
    """Return the built-in entity type reference list."""
    return [
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


def get_replacement_modes_list() -> list[dict[str, Any]]:
    """Return the built-in replacement mode reference list."""
    return [
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
