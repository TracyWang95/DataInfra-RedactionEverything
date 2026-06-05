"""
匿名化编排服务层 — 从 api/redaction.py 提取。

在路由处理器与底层 Redactor/VisionService 之间的编排层：
- 匿名化执行与 file_store 更新
- entity_map 管理与版本追踪
- 报告生成（实体 bbox 统计）
- 视觉检测编排
"""
from __future__ import annotations

import base64
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from app.core.visual_feature_categories import has_only_ocr_fallback_visual_slugs
from app.core.persistence import to_jsonable
from app.models.schemas import (
    BoundingBox,
    CompareData,
    EntityType,
    PreviewEntityMapResponse,
    PreviewImageResponse,
    RedactionConfig,
    RedactionReport,
    RedactionRequest,
    RedactionResult,
    ReplacementMode,
    VisionResult,
)
from app.services.redaction.image_redactor import prepare_image_redaction
from app.services.redactor import Redactor, build_preview_entity_map
from app.services.vision_service import VisionService

logger = logging.getLogger(__name__)


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _get_file_store():
    from app.services.file_management_service import file_store
    return file_store


def _get_file_store_lock():
    from app.services.file_management_service import _file_store_lock
    return _file_store_lock


def _group_boxes_by_page(boxes: list[Any]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for box in boxes:
        page = int(getattr(box, "page", 1) or 1)
        grouped.setdefault(page, []).append(to_jsonable(box))
    return grouped


def _request_item_selected(item: Any) -> bool:
    if isinstance(item, dict):
        return item.get("selected") is not False
    return getattr(item, "selected", True) is not False


def _selected_request_item_count(entities: list[Any], boxes: list[Any]) -> int:
    return sum(1 for item in entities if _request_item_selected(item)) + sum(
        1 for item in boxes if _request_item_selected(item)
    )


def _default_pipeline_types(types: list[Any]) -> list[Any]:
    return [
        t
        for t in types
        if getattr(t, "enabled", True) is not False
        and getattr(t, "default_enabled", False) is True
    ]


def _vision_type_ids(types: list[Any] | None) -> list[str]:
    return sorted(str(getattr(t, "id", t)) for t in (types or []))


def _vision_signature(
    page: int,
    ocr_has_types: list[Any] | None,
    visual_feature_types: list[Any] | None,
) -> dict[str, Any]:
    from app.core.config import settings

    return {
        "version": 4,
        "page": int(page),
        "ocr_has_types": _vision_type_ids(ocr_has_types),
        "visual_feature_types": _vision_type_ids(visual_feature_types),
        "visual_signature_max_side": int(
            getattr(settings, "VISUAL_FEATURES_SIGNATURE_MAX_IMAGE_SIDE", 640) or 640
        ),
    }


def _page_value(mapping: Any, page: int) -> Any:
    if not isinstance(mapping, dict):
        return None
    if page in mapping:
        return mapping[page]
    return mapping.get(str(page))


def _cached_vision_result(
    file_id: str,
    page: int,
    snapshot: dict[str, Any],
    signature: dict[str, Any],
    started: float,
) -> VisionResult | None:
    stored_signature = _page_value(snapshot.get("vision_detection_signature"), page)
    if stored_signature != signature:
        return None
    raw_boxes = _page_value(snapshot.get("bounding_boxes"), page)
    if not isinstance(raw_boxes, list):
        return None
    boxes = [
        box if isinstance(box, BoundingBox) else BoundingBox.model_validate({**box, "page": box.get("page", page)})
        for box in raw_boxes
        if isinstance(box, (dict, BoundingBox))
    ]
    quality = _page_value(snapshot.get("vision_quality"), page) or {}
    duration_ms = dict(quality.get("duration_ms") or {}) if isinstance(quality, dict) else {}
    duration_ms["request_total_ms"] = _elapsed_ms(started)
    return VisionResult(
        file_id=file_id,
        page=page,
        bounding_boxes=boxes,
        result_image=None,
        warnings=list(quality.get("warnings") or []) if isinstance(quality, dict) else [],
        pipeline_status=dict(quality.get("pipeline_status") or {}) if isinstance(quality, dict) else {},
        duration_ms=duration_ms,
        cache_status={
            "vision_result": "hit",
            "force": False,
            "signature_version": signature.get("version"),
        },
    )


def _boxes_from_page(raw_boxes: Any, page: int) -> list[BoundingBox]:
    if not isinstance(raw_boxes, list):
        return []
    return [
        box if isinstance(box, BoundingBox) else BoundingBox.model_validate({**box, "page": box.get("page", page)})
        for box in raw_boxes
        if isinstance(box, (dict, BoundingBox))
    ]


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
        raise ValueError("file not found")

    file_info = file_store[file_id]

    redactor = Redactor()
    result = await redactor.redact(
        file_info=file_info,
        entities=request.entities,
        bounding_boxes=request.bounding_boxes,
        config=request.config,
    )
    selected_item_count = _selected_request_item_count(request.entities, request.bounding_boxes)

    # 更新文件存储
    async with lock:
        info = file_store.get(file_id)
        if info is None:
            logger.warning("file %s was deleted during redaction, skipping store update", file_id)
        else:
            info["output_path"] = result.get("output_path")
            info["entity_map"] = result.get("entity_map", {})
            info["redacted_count"] = int(result.get("redacted_count", 0))
            info["bounding_boxes"] = _group_boxes_by_page(request.bounding_boxes)
            info["entities"] = to_jsonable(request.entities)
            # 版本历史追踪
            version_entry = {
                "version": len(info.get("redaction_history", [])) + 1,
                "output_file_id": result["output_file_id"],
                "output_path": result.get("output_path"),
                "redacted_count": selected_item_count,
                "replacement_count": result["redacted_count"],
                "entity_map": result.get("entity_map", {}),
                "mode": request.config.replacement_mode.value if hasattr(request.config.replacement_mode, 'value') else str(request.config.replacement_mode),
                "created_at": datetime.now(UTC).isoformat(),
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
    from app.core.metrics import REDACTION_COUNT, REDACTION_DURATION
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
    file_path = file_info.get("file_path")
    if not isinstance(file_path, str) or not os.path.isfile(file_path):
        raise ValueError("original file not found")
    vision_service = VisionService()
    safe_boxes, image_method, strength, fill_color = prepare_image_redaction(bounding_boxes, config)
    image_bytes = await vision_service.preview_redaction(
        file_path=file_path,
        file_type=file_info["file_type"],
        bounding_boxes=safe_boxes,
        page=page,
        image_method=image_method,
        strength=strength,
        fill_color=fill_color,
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
        raise ValueError("file not found")

    file_info = file_store[file_id]

    if "output_path" not in file_info:
        raise ValueError("file has not been redacted")

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
        raise ValueError("file not found")

    history = file_store[file_id].get("redaction_history", [])
    return {"file_id": file_id, "versions": history, "total": len(history)}


# ---------------------------------------------------------------------------
# Vision detection
# ---------------------------------------------------------------------------

async def detect_vision(
    file_id: str,
    page: int = 1,
    selected_ocr_has_types: list[str] | None = None,
    selected_visual_feature_types: list[str] | None = None,
    has_request: bool = True,
    force: bool = False,
    include_result_image: bool = True,
    merge_existing: bool = False,
    owner_id: str | None = None,
    signature_selected_ocr_has_types: list[str] | None = None,
    signature_selected_visual_feature_types: list[str] | None = None,
) -> VisionResult:
    """
    Run dual-pipeline vision detection. Raises ValueError if file not found.
    `has_request` indicates whether a request body was provided (affects defaults).
    """
    started = time.perf_counter()
    file_store = _get_file_store()
    lock = _get_file_store_lock()

    async with lock:
        file_info = file_store.get(file_id)
        if not file_info:
            raise ValueError("file not found")
        snapshot = dict(file_info)
    owner_id = owner_id or str(snapshot.get("owner_id") or "local_user")

    # 获取两个 Pipeline 的类型配置
    from app.services.pipeline_service import get_pipeline, get_pipeline_types_for_mode

    all_ocr_has_types = get_pipeline_types_for_mode("ocr_has", owner_id=owner_id)
    default_ocr_has_types = _default_pipeline_types(all_ocr_has_types)
    default_visual_feature_types = _default_pipeline_types(
        get_pipeline_types_for_mode("visual_features", owner_id=owner_id)
    )
    selectable_visual_feature_types = get_pipeline_types_for_mode(
        "visual_features",
        enabled_only=False,
        owner_id=owner_id,
    )

    sel_ocr_ids: set[str] | None = None
    sel_visual_ids: set[str] | None = None

    if has_request:
        if selected_ocr_has_types is not None:
            sel_ocr_ids = set(selected_ocr_has_types or [])
        if selected_visual_feature_types is not None:
            sel_visual_ids = set(selected_visual_feature_types or [])

    if sel_ocr_ids is not None:
        ocr_has_types = [t for t in all_ocr_has_types if t.id in sel_ocr_ids]
    else:
        ocr_has_types = default_ocr_has_types

    if sel_visual_ids is not None:
        visual_feature_types = [t for t in selectable_visual_feature_types if t.id in sel_visual_ids]
    else:
        visual_feature_types = default_visual_feature_types

    if (
        selected_ocr_has_types is not None
        and len(selected_ocr_has_types) > 0
        and len(ocr_has_types) == 0
        and len(default_ocr_has_types) > 0
    ):
        logger.warning(
            "selected_ocr_has_types contains no valid IDs; fallback to default OCR+HaS types."
        )
        ocr_has_types = default_ocr_has_types

    if (
        sel_visual_ids is not None
        and len(sel_visual_ids) > 0
        and len(visual_feature_types) == 0
        and len(default_visual_feature_types) > 0
    ):
        if has_only_ocr_fallback_visual_slugs(list(sel_visual_ids)):
            logger.info(
                "selected visual feature types contain OCR/local-fallback-only IDs; "
                "LocateAnything will not run for these IDs."
            )
        else:
            logger.warning(
                "selected visual feature types contain no valid IDs; fallback to default enabled visual feature types."
            )
            visual_feature_types = default_visual_feature_types

    ocr_pipeline = get_pipeline("ocr_has", owner_id=owner_id)
    visual_pipeline = get_pipeline("visual_features", owner_id=owner_id)
    ocr_has_enabled = bool(ocr_pipeline and ocr_pipeline.enabled and len(ocr_has_types) > 0)
    visual_features_enabled = (
        visual_pipeline
        and visual_pipeline.enabled
        and len(visual_feature_types) > 0
    )

    if ocr_pipeline and ocr_pipeline.enabled and len(ocr_has_types) == 0:
        logger.info(
            "OCR+HaS skipped because selected_ocr_has_types=[] was supplied."
        )

    logger.info("OCR+HaS selected: %s", [t.id for t in ocr_has_types] if ocr_has_types else [])
    logger.info("Visual features selected: %s", [t.id for t in visual_feature_types] if visual_feature_types else [])

    effective_ocr_types = ocr_has_types if ocr_has_enabled else None
    effective_visual_feature_types = visual_feature_types if visual_features_enabled else None

    signature_ocr_types = effective_ocr_types
    signature_visual_feature_types = effective_visual_feature_types
    if signature_selected_ocr_has_types is not None:
        sig_ocr_ids = set(signature_selected_ocr_has_types or [])
        signature_ocr_types = [t for t in all_ocr_has_types if t.id in sig_ocr_ids] if sig_ocr_ids else None
    sig_visual_ids: set[str] | None = None
    if signature_selected_visual_feature_types is not None:
        sig_visual_ids = set(signature_selected_visual_feature_types or [])
    if sig_visual_ids is not None:
        signature_visual_feature_types = [t for t in selectable_visual_feature_types if t.id in sig_visual_ids] if sig_visual_ids else None

    signature = _vision_signature(page, signature_ocr_types, signature_visual_feature_types)
    if not force:
        cached = _cached_vision_result(file_id, page, snapshot, signature, started)
        if cached is not None:
            logger.info(
                "Vision cache hit file=%s page=%d boxes=%d elapsed=%.2fs",
                file_id[:8],
                page,
                len(cached.bounding_boxes),
                time.perf_counter() - started,
            )
            return cached
    else:
        logger.info("Vision force refresh file=%s page=%d", file_id[:8], page)

    vision_service = VisionService()
    bounding_boxes, result_image = await vision_service.detect_with_dual_pipeline(
        file_path=snapshot["file_path"],
        file_type=snapshot["file_type"],
        page=page,
        ocr_has_types=effective_ocr_types,
        visual_feature_types=effective_visual_feature_types,
        include_result_image=include_result_image,
    )
    warnings = list(getattr(vision_service, "last_warnings", []) or [])
    pipeline_status = dict(getattr(vision_service, "last_pipeline_status", {}) or {})
    duration_ms = dict(getattr(vision_service, "last_duration_ms", {}) or {})
    if merge_existing:
        existing_boxes = _boxes_from_page(_page_value(snapshot.get("bounding_boxes"), page), page)
        if existing_boxes:
            merged_boxes = [*existing_boxes, *bounding_boxes]
            bounding_boxes = VisionService()._deduplicate_boxes(merged_boxes)
        existing_quality = _page_value(snapshot.get("vision_quality"), page) or {}
        if isinstance(existing_quality, dict):
            existing_status = dict(existing_quality.get("pipeline_status") or {})
            existing_duration = dict(existing_quality.get("duration_ms") or {})
            pipeline_status = {**existing_status, **pipeline_status}
            duration_ms = {**existing_duration, **duration_ms}
            succeeded_labels = {
                label
                for label, status in pipeline_status.items()
                if isinstance(status, dict) and status.get("ran") and not status.get("failed")
            }
            stale_prefixes = tuple(f"{label} failed:" for label in sorted(succeeded_labels))
            existing_warnings = [
                warning
                for warning in list(existing_quality.get("warnings") or [])
                if not str(warning).startswith(stale_prefixes)
            ]
            warnings = [
                *existing_warnings,
                *warnings,
            ]
    duration_ms["request_total_ms"] = _elapsed_ms(started)
    cache_status = {
        "vision_result": "force_refresh" if force else "miss",
        "force": bool(force),
        "signature_version": signature.get("version"),
    }
    vision_quality = {
        "warnings": warnings,
        "pipeline_status": pipeline_status,
        "duration_ms": duration_ms,
    }

    # Write back under lock
    async with lock:
        if file_id in file_store:
            info = file_store.get(file_id)
            if "bounding_boxes" not in info:
                info["bounding_boxes"] = {}
            info["bounding_boxes"][page] = bounding_boxes
            if "vision_quality" not in info or not isinstance(info.get("vision_quality"), dict):
                info["vision_quality"] = {}
            info["vision_quality"][page] = vision_quality
            if "vision_detection_signature" not in info or not isinstance(info.get("vision_detection_signature"), dict):
                info["vision_detection_signature"] = {}
            info["vision_detection_signature"][page] = signature
            file_store.set(file_id, info)

    logger.info(
        "Vision detect stored file=%s page=%d boxes=%d elapsed=%.2fs",
        file_id[:8],
        page,
        len(bounding_boxes),
        time.perf_counter() - started,
    )
    return VisionResult(
        file_id=file_id,
        page=page,
        bounding_boxes=bounding_boxes,
        result_image=result_image,
        warnings=warnings,
        pipeline_status=pipeline_status,
        duration_ms=duration_ms,
        cache_status=cache_status,
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def get_report(file_id: str) -> RedactionReport:
    """Generate redaction quality report. Raises ValueError if file not found."""
    file_store = _get_file_store()

    if file_id not in file_store:
        raise ValueError("file not found")

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

    def _is_selected_box(box: Any) -> bool:
        return not isinstance(box, dict) or box.get("selected", True) is not False

    # Also count bounding boxes
    bb_total = 0
    bb_selected = 0
    bbs = file_info.get("bounding_boxes", {})
    if isinstance(bbs, dict):
        for page_bbs in bbs.values():
            if isinstance(page_bbs, list):
                bb_total += len(page_bbs)
                bb_selected += sum(1 for box in page_bbs if _is_selected_box(box))
    elif isinstance(bbs, list):
        bb_total = len(bbs)
        bb_selected = sum(1 for box in bbs if _is_selected_box(box))

    redacted_count = file_info.get("redacted_count", 0)
    total_detected = total + bb_total
    selected_detected = selected + bb_selected
    if total_detected == 0 and isinstance(redacted_count, int) and redacted_count > 0:
        total_detected = redacted_count
        selected_detected = redacted_count
    redacted_entities = selected_detected if file_info.get("output_path") else 0
    coverage = (redacted_entities / total_detected * 100) if total_detected > 0 else 0.0

    return RedactionReport(
        file_id=file_id,
        filename=file_info.get("original_filename", ""),
        total_entities=total_detected,
        redacted_entities=redacted_entities,
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

