"""PaddleOCR-VL / PP-StructureV3 extraction orchestration.

Split out of ocr_pipeline.py (which stays the public facade): run_paddle_ocr
routing (structure-primary, VL supplement, structure fallback), the table-line
heuristic, service result conversion and the low-level VL/structure service
calls with caching and in-flight dedupe.
"""
from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from typing import Any

from PIL import Image

from app.core.config import settings
from app.services.ocr_has_vision_service import OCRTextBlock, SensitiveRegion
from app.services.vision.has_text_payload import (
    _canonical_image_text_type,
    _compact_text,
)
from app.services.vision.locate_tiles import _axis_positions
from app.services.vision.ocr_block_merge import (
    _is_coarse_markup_block,
    _merge_ocr_blocks,
)
from app.services.vision.ocr_cache import (
    _begin_ocr_output_inflight,
    _finish_ocr_output_inflight,
    _get_cached_ocr_output,
    _image_png_bytes,
    _ocr_cache_key,
    _record_ocr_cache_stage,
    _record_ocr_stage_duration,
    _set_cached_ocr_output,
    _wait_for_ocr_output_inflight,
)
from app.services.vision.ocr_image_prep import _is_effectively_blank_page
from app.services.vision.ocr_tuning import (
    _COARSE_MULTILINE_HEIGHT_MULT,
    _COARSE_MULTILINE_MIN_COMPACT_LEN,
    _DEFAULT_OCR_ITEM_CONFIDENCE,
    _SEAL_REGION_COLOR,
    OCR_VISUAL_ENTITY_TYPES,
    TABLE_PRECISION_ENTITY_TYPES,
)
from app.services.vision.ocr_visual_lines import _infer_typical_textline_height

logger = logging.getLogger(__name__)


def run_paddle_ocr(
    image: Image.Image,
    ocr_service: Any,
    require_visual_regions: bool = False,
    selected_entity_types: list[str] | None = None,
    stage_status: dict[str, Any] | None = None,
) -> tuple[list[OCRTextBlock], list[SensitiveRegion]]:
    """
    Call PaddleOCR-VL microservice (port 8082) to extract text blocks and visual
    regions (e.g. seals).

    Returns:
        (text_blocks, visual_sensitive_regions)
    """
    if not ocr_service:
        logger.warning("OCR client not initialized")
        return [], []

    is_blank, dark_ratio, ink_ratio = _is_effectively_blank_page(image)
    if is_blank:
        if stage_status is not None:
            stage_status["ocr_blank_page_skipped"] = True
            stage_status["ocr_blank_dark_ratio"] = round(dark_ratio, 6)
            stage_status["ocr_blank_ink_ratio"] = round(ink_ratio, 6)
        logger.info(
            "OCR skipped effectively blank page (dark_ratio=%.6f, ink_ratio=%.6f)",
            dark_ratio,
            ink_ratio,
        )
        return [], []

    if not ocr_service.is_available():
        logger.warning("OCR microservice offline (8082)")
        return [], []

    encoded_image_bytes: bytes | None = None

    def image_bytes() -> bytes:
        nonlocal encoded_image_bytes
        if encoded_image_bytes is None:
            encoded_image_bytes = _image_png_bytes(image)
        return encoded_image_bytes

    selected = {_canonical_image_text_type(type_id) for type_id in (selected_entity_types or [])}
    adaptive_mode = selected_entity_types is not None

    needs_table_precision = bool(selected & TABLE_PRECISION_ENTITY_TYPES)
    needs_ocr_visual_regions = bool(selected & OCR_VISUAL_ENTITY_TYPES)
    needs_text_precision = adaptive_mode and bool(selected - OCR_VISUAL_ENTITY_TYPES)

    vl_disabled = not bool(getattr(settings, "OCR_VL_ENABLED", True))
    # PP-StructureV3 is the ONLY source of per-char boxes, and those boxes are
    # what narrows a redaction crop to the entity instead of masking the whole
    # OCR line. So it must run whenever text precision is needed — even when
    # visual regions are also requested (selecting a seal/signature set
    # require_visual_regions without needing OCR-derived visual regions). Skipping
    # it there left only VL's whole-line, char-box-less blocks, so every text
    # entity boxed as a full-width slab (phone-photo judgment: 龙继临/和勃 full
    # line, addresses collapsed flat).
    use_structure_primary = settings.OCR_STRUCTURE_ENABLED and (
        vl_disabled
        or (
            settings.OCR_STRUCTURE_PRIMARY
            and (not require_visual_regions or needs_ocr_visual_regions or needs_text_precision)
        )
    )

    primary_structure_blocks: list[OCRTextBlock] | None = None
    primary_structure_visual_regions: list[SensitiveRegion] = []
    if use_structure_primary:
        primary_structure_blocks, primary_structure_visual_regions = _run_structure_service_with_visuals(
            image,
            ocr_service,
            stage_status=stage_status,
            image_bytes=image_bytes(),
        )
        min_blocks = max(1, int(settings.OCR_STRUCTURE_PRIMARY_MIN_BOXES))
        if primary_structure_visual_regions and (require_visual_regions or needs_ocr_visual_regions) and not needs_text_precision:
            logger.info(
                "Using PP-StructureV3 primary visual path: %d text blocks, %d visual regions",
                len(primary_structure_blocks),
                len(primary_structure_visual_regions),
            )
            return primary_structure_blocks, primary_structure_visual_regions
        if len(primary_structure_blocks) >= min_blocks:
            if needs_text_precision and bool(settings.OCR_STRUCTURE_PRIMARY_SUPPLEMENT_VL) and not vl_disabled:
                # PP-StructureV3 stays the primary block set. PaddleOCR-VL only
                # supplements: VL full-page blocks merge in through the existing
                # whole-block IoU contract (_merge_ocr_blocks), so structure
                # blocks win on overlap and VL adds what structure missed
                # (e.g. text crushed under a red seal).
                vl_blocks, vl_visual_regions = _run_ocr_service(
                    image,
                    ocr_service,
                    stage_status=stage_status,
                    image_bytes=image_bytes(),
                    service_available_checked=True,
                )
                merged_blocks = _merge_ocr_blocks(
                    primary_structure_blocks, vl_blocks, prefer_extra_text=True
                )
                merged_blocks = _attach_chars_to_charless_blocks(merged_blocks, image, ocr_service)
                logger.info(
                    "PP-StructureV3 primary OCR kept %d blocks; PaddleOCR-VL supplement merged %d VL blocks (%d -> %d)",
                    len(primary_structure_blocks),
                    len(vl_blocks),
                    len(primary_structure_blocks),
                    len(merged_blocks),
                )
                return merged_blocks, [*primary_structure_visual_regions, *vl_visual_regions]
            if needs_ocr_visual_regions and not primary_structure_visual_regions and not vl_disabled:
                # PP-StructureV3 produced no visual regions, so PaddleOCR-VL
                # still runs to provide them — but the text-block set stays
                # structure-primary, same merge direction as the supplement
                # branch above. VL's generative whole-line blocks carry no
                # char boxes; letting them displace per-line structure blocks
                # masks label and value together as one full line.
                vl_blocks, vl_visual_regions = _run_ocr_service(
                    image,
                    ocr_service,
                    stage_status=stage_status,
                    image_bytes=image_bytes(),
                    service_available_checked=True,
                )
                merged_blocks = _merge_ocr_blocks(
                    primary_structure_blocks, vl_blocks, prefer_extra_text=True
                )
                merged_blocks = _attach_chars_to_charless_blocks(merged_blocks, image, ocr_service)
                logger.info(
                    "PP-StructureV3 primary OCR found %d blocks but no visual regions; "
                    "PaddleOCR-VL supplied %d visual regions, merged %d VL blocks (%d -> %d)",
                    len(primary_structure_blocks),
                    len(vl_visual_regions),
                    len(vl_blocks),
                    len(primary_structure_blocks),
                    len(merged_blocks),
                )
                return merged_blocks, [*primary_structure_visual_regions, *vl_visual_regions]
            else:
                if needs_text_precision:
                    logger.info(
                        "Using PP-StructureV3 primary OCR path: %d blocks; PaddleOCR-VL supplement disabled",
                        len(primary_structure_blocks),
                    )
                else:
                    logger.info(
                        "Using PP-StructureV3 primary OCR path: %d blocks (min=%d, table_types=%s)",
                        len(primary_structure_blocks),
                        min_blocks,
                        needs_table_precision,
                    )
                return primary_structure_blocks, primary_structure_visual_regions
        elif primary_structure_blocks:
            logger.info(
                "PP-StructureV3 primary OCR was sparse (%d < %d); falling back to PaddleOCR-VL",
                len(primary_structure_blocks),
                min_blocks,
            )

    if vl_disabled:
        # PaddleOCR-VL is disabled: never call /ocr (it would 503). Use whatever
        # PP-StructureV3 produced (even if sparse) as the OCR result.
        return (primary_structure_blocks or []), primary_structure_visual_regions

    blocks, visual_regions = _run_ocr_service(
        image,
        ocr_service,
        stage_status=stage_status,
        image_bytes=image_bytes(),
        service_available_checked=True,
    )
    if primary_structure_visual_regions:
        visual_regions = [*primary_structure_visual_regions, *visual_regions]
    should_structure_fallback = (
        settings.OCR_STRUCTURE_ENABLED
        and (
            _should_run_structure_fallback(blocks)
            or _has_coarse_markup_blocks(blocks)
            or (needs_table_precision and _has_coarse_multiline_blocks(blocks))
            or (needs_text_precision and bool(primary_structure_blocks))
            or (needs_text_precision and bool(settings.OCR_STRUCTURE_TEXT_PRECISION_ENABLED))
        )
    )
    if should_structure_fallback:
        if primary_structure_blocks is not None:
            structure_blocks = primary_structure_blocks
            structure_visual_regions = primary_structure_visual_regions
            if stage_status is not None:
                stage_status["ocr_structure_fallback_reused_primary"] = True
        else:
            structure_blocks, structure_visual_regions = _run_structure_service_with_visuals(
                image,
                ocr_service,
                stage_status=stage_status,
                image_bytes=image_bytes(),
            )
        if structure_visual_regions and structure_visual_regions is not primary_structure_visual_regions:
            visual_regions = [*visual_regions, *structure_visual_regions]
        if structure_blocks:
            before = len(blocks)
            blocks = _merge_ocr_blocks(blocks, structure_blocks)
            logger.info(
                "PP-StructureV3 OCR supplement added %d blocks (%d -> %d)",
                len(structure_blocks),
                before,
                len(blocks),
            )
    if blocks or visual_regions:
        logger.info("OCR got %d text blocks, %d visual regions", len(blocks), len(visual_regions))
    else:
        logger.info("No results from OCR service")
    return blocks, visual_regions


def _should_run_structure_fallback(blocks: list[OCRTextBlock]) -> bool:
    sparse = len(blocks) < max(1, int(settings.OCR_STRUCTURE_MIN_VL_BOXES))
    if not sparse:
        return False
    # OCR 产物即真相源：VL 版面把表格块以 <table html 回传，稀疏页只要携带任一
    # 标记块就补跑 PP-StructureV3——不再用像素启发预判表格。
    return any(block.text.lstrip().lower().startswith(("<table", "<html", "<div")) for block in blocks)


def _has_coarse_multiline_blocks(blocks: list[OCRTextBlock]) -> bool:
    typical_height = _infer_typical_textline_height(blocks)
    if not typical_height:
        return False
    for block in blocks:
        if block.text.lstrip().startswith(("<table", "<div")):
            return True
        compact_len = len(_compact_text(block.text))
        if compact_len >= _COARSE_MULTILINE_MIN_COMPACT_LEN and block.height > typical_height * _COARSE_MULTILINE_HEIGHT_MULT:
            return True
    return False


def _has_coarse_markup_blocks(blocks: list[OCRTextBlock]) -> bool:
    return any(_is_coarse_markup_block(block) for block in blocks)


def _ocr_items_to_blocks(items: list[Any], image: Image.Image) -> tuple[list[OCRTextBlock], list[SensitiveRegion]]:
    width, height = image.size
    blocks: list[OCRTextBlock] = []
    visual_regions: list[SensitiveRegion] = []

    for item in items:
        left = int(item.x * width)
        top = int(item.y * height)
        w = int(item.width * width)
        h = int(item.height * height)
        right = max(left + max(w, 1), left + 1)
        bottom = max(top + max(h, 1), top + 1)

        left = max(0, min(left, width - 1))
        top = max(0, min(top, height - 1))
        right = max(left + 1, min(right, width))
        bottom = max(top + 1, min(bottom, height))

        label = getattr(item, "label", "text") or "text"
        if str(label).strip().lower() in {"figure", "image", "picture", "diagram", "chart"}:
            continue
        text = str(getattr(item, "text", "") or "").strip()
        if label == "seal" or text == "[公章]":
            region = SensitiveRegion(
                text="[公章]",
                entity_type="SEAL",
                left=left,
                top=top,
                width=right - left,
                height=bottom - top,
                confidence=float(getattr(item, "confidence", _DEFAULT_OCR_ITEM_CONFIDENCE) or _DEFAULT_OCR_ITEM_CONFIDENCE),
                source="ocr_seal",
            )
            visual_regions.append(region)
            continue
        if not text:
            continue
        char_boxes = [
            {
                "c": str(ch.get("c", "")),
                "x1": int(ch["x"] * width),
                "y1": int(ch["y"] * height),
                "x2": int((ch["x"] + ch["w"]) * width),
                "y2": int((ch["y"] + ch["h"]) * height),
            }
            for ch in (getattr(item, "chars", None) or [])
            if isinstance(ch, dict) and "x" in ch and "w" in ch
        ]
        blocks.append(OCRTextBlock(
            text=text,
            polygon=[[left, top], [right, top], [right, bottom], [left, bottom]],
            confidence=float(getattr(item, "confidence", _DEFAULT_OCR_ITEM_CONFIDENCE) or _DEFAULT_OCR_ITEM_CONFIDENCE),
            chars=char_boxes,
        ))
    return blocks, visual_regions


def _reading_order(blocks: list[OCRTextBlock]) -> list[OCRTextBlock]:
    """Sort line blocks/segments into reading order: rows top-to-bottom, row
    members left-to-right. Rows are discovered by the y identity — a segment
    belongs to a row when its y-center falls inside the row's y band (same-row
    segments overlap in y; distinct physical rows do not) — so a tilted line's
    segments stay one row even when their integer tops differ."""
    rows: list[list] = []  # [row_top, row_bottom, [segments]]
    for segment in sorted(blocks, key=lambda item: item.top + item.height / 2.0):
        center_y = segment.top + segment.height / 2.0
        for row in rows:
            if row[0] <= center_y <= row[1]:
                row[2].append(segment)
                row[0] = min(row[0], segment.top)
                row[1] = max(row[1], segment.top + segment.height)
                break
        else:
            rows.append([segment.top, segment.top + segment.height, [segment]])
    rows.sort(key=lambda row: row[0])
    return [seg for row in rows for seg in sorted(row[2], key=lambda item: item.left)]


def _attach_chars_to_charless_blocks(
    blocks: list[OCRTextBlock],
    image: Image.Image,
    ocr_service: Any,
) -> list[OCRTextBlock]:
    """Recover per-char boxes for whole-line blocks that carry none.

    A charless block is a PaddleOCR-VL paragraph for a line PP-StructureV3
    skipped (faint phone-photo lines): with no char boxes, every text entity on
    it is masked as a full-width slab. Its crop, re-OCR'd on its own, gives the
    structure engine a clean single line to box per character; the recovered
    boxes are mapped back to full-image pixels. Only charless blocks are touched
    — a fully structure-covered page pays nothing (in the supplement path a
    handful of lines at most). Recovery is best-effort AND text-preserving: the
    re-OCR only contributes char boxes, never the block's authoritative text, so
    a crop misread cannot drop the entity; an empty/failed re-OCR leaves the
    block as a safe whole-block mask.
    """
    if not ocr_service or not hasattr(ocr_service, "extract_structure_boxes"):
        return blocks
    width, height = image.size
    for block in blocks:
        if getattr(block, "chars", None):
            continue
        left, top = max(0, int(block.left)), max(0, int(block.top))
        right = min(width, int(block.left + block.width))
        bottom = min(height, int(block.top + block.height))
        if right - left < 4 or bottom - top < 4:
            continue
        # Whole-block crop first, then three anchored half-width sweep windows:
        # the engine's det collapses on an underline+handwriting row at block
        # width (the 农业 row-1 printed label AND handwritten value both vanish)
        # yet reads the same pixels inside a half-width window. Same
        # start/center/end half-size anchoring identity as the tile retry
        # (_axis_positions): anything narrower than half a window is whole
        # inside at least one sweep.
        crops = [(left, top, right, bottom)]
        window = max(1, (right - left) // 2)
        crops.extend(
            (left + x0, top, min(right, left + x0 + window), bottom)
            for x0 in _axis_positions(right - left, window)
        )
        kept_segments: list = []  # (page-coord bbox, page-coord chars)
        for crop_left, crop_top, crop_right, crop_bottom in crops:
            try:
                crop_blocks, _ = _run_structure_service_with_visuals(
                    image.crop((crop_left, crop_top, crop_right, crop_bottom)), ocr_service
                )
            except Exception as exc:
                logger.info("charless-block re-OCR failed: %s", exc)
                continue
            for cb in crop_blocks:
                chars = [
                    {"c": ch["c"], "x1": crop_left + ch["x1"], "y1": crop_top + ch["y1"],
                     "x2": crop_left + ch["x2"], "y2": crop_top + ch["y2"]}
                    for ch in (getattr(cb, "chars", None) or [])
                ]
                if not chars:
                    continue
                x1 = min(c["x1"] for c in chars)
                y1 = min(c["y1"] for c in chars)
                x2 = max(c["x2"] for c in chars)
                y2 = max(c["y2"] for c in chars)
                # Region-overlap identity dedupe: a segment overlapping an
                # already-kept one in BOTH x and y is the same physical text
                # re-detected through another window — first seen (the
                # whole-block crop) wins. A same-row segment at a new x range
                # is genuinely new content and joins.
                if any(
                    x1 < kx2 and kx1 < x2 and y1 < ky2 and ky1 < y2
                    for (kx1, ky1, kx2, ky2), _kc in kept_segments
                ):
                    continue
                kept_segments.append(((x1, y1, x2, y2), chars))
        if not kept_segments:
            continue
        # Reading order across all kept segments: same row identity as
        # _reading_order (rows do not overlap in y; same-row segments do),
        # then left-to-right inside a row.
        segment_blocks = [
            SimpleNamespace(
                top=bbox[1], left=bbox[0], height=bbox[3] - bbox[1], width=bbox[2] - bbox[0], chars=chars
            )
            for bbox, chars in kept_segments
        ]
        block.chars = [
            ch for seg in _reading_order(segment_blocks) for ch in seg.chars
        ]
    return blocks


def _run_structure_service_with_visuals(
    image: Image.Image,
    ocr_service: Any,
    stage_status: dict[str, Any] | None = None,
    image_bytes: bytes | None = None,
) -> tuple[list[OCRTextBlock], list[SensitiveRegion]]:
    stage_start = time.perf_counter()
    if not ocr_service or not hasattr(ocr_service, "extract_structure_boxes"):
        _record_ocr_stage_duration(stage_status, "structure", stage_start)
        return [], []
    if image_bytes is None:
        image_bytes = _image_png_bytes(image)
    cache_key = _ocr_cache_key("structure", image, image_bytes, ocr_service)
    cached = _get_cached_ocr_output(cache_key, "structure", stage_status)
    if cached is not None:
        _record_ocr_stage_duration(stage_status, "structure", stage_start)
        return cached

    owns_inflight, inflight = _begin_ocr_output_inflight(cache_key)
    if not owns_inflight:
        blocks, visual_regions = _wait_for_ocr_output_inflight(inflight)
        _record_ocr_cache_stage(stage_status, "structure", "shared_inflight")
        _record_ocr_stage_duration(stage_status, "structure", stage_start)
        return blocks, visual_regions

    try:
        items = ocr_service.extract_structure_boxes(image_bytes)
    except Exception as e:
        logger.warning("PP-StructureV3 fallback failed: %s", e)
        _finish_ocr_output_inflight(cache_key, inflight, ([], []))
        _record_ocr_stage_duration(stage_status, "structure", stage_start)
        return [], []
    try:
        blocks, visual_regions = _ocr_items_to_blocks(items, image)
    except Exception as e:
        _finish_ocr_output_inflight(cache_key, inflight, None, e)
        raise
    _set_cached_ocr_output(cache_key, blocks, visual_regions)
    _finish_ocr_output_inflight(cache_key, inflight, (blocks, visual_regions))
    _record_ocr_stage_duration(stage_status, "structure", stage_start)
    return blocks, visual_regions


def _run_ocr_service(
    image: Image.Image,
    ocr_service: Any,
    stage_status: dict[str, Any] | None = None,
    image_bytes: bytes | None = None,
    service_available_checked: bool = False,
) -> tuple[list[OCRTextBlock], list[SensitiveRegion]]:
    """Low-level call to OCRService (PaddleOCR-VL) and result conversion."""
    stage_start = time.perf_counter()
    if not ocr_service:
        _record_ocr_stage_duration(stage_status, "vl", stage_start)
        return [], []
    if not service_available_checked and not ocr_service.is_available():
        _record_ocr_stage_duration(stage_status, "vl", stage_start)
        return [], []

    if image_bytes is None:
        image_bytes = _image_png_bytes(image)
    cache_key = _ocr_cache_key("vl", image, image_bytes, ocr_service)
    cached = _get_cached_ocr_output(cache_key, "vl", stage_status)
    if cached is not None:
        _record_ocr_stage_duration(stage_status, "vl", stage_start)
        return cached

    owns_inflight, inflight = _begin_ocr_output_inflight(cache_key)
    if not owns_inflight:
        result = _wait_for_ocr_output_inflight(inflight)
        _record_ocr_cache_stage(stage_status, "vl", "shared_inflight")
        _record_ocr_stage_duration(stage_status, "vl", stage_start)
        return result

    from app.services.ocr_service import OCRServiceError
    cacheable = True
    try:
        items = ocr_service.extract_text_boxes(image_bytes)
    except OCRServiceError as e:
        logger.warning("OCR 服务异常 (transient=%s): %s", e.transient, e)
        if not e.transient:
            _finish_ocr_output_inflight(cache_key, inflight, None, e)
            raise  # permanent error propagated
        cacheable = False
        items = []  # transient error degrades gracefully
    except Exception as e:
        _finish_ocr_output_inflight(cache_key, inflight, None, e)
        raise
    if not items:
        if cacheable:
            _set_cached_ocr_output(cache_key, [], [])
        _finish_ocr_output_inflight(cache_key, inflight, ([], []))
        _record_ocr_stage_duration(stage_status, "vl", stage_start)
        return [], []

    try:
        width, height = image.size
        blocks: list[OCRTextBlock] = []
        visual_regions: list[SensitiveRegion] = []

        for item in items:
            left = int(item.x * width)
            top = int(item.y * height)
            w = int(item.width * width)
            h = int(item.height * height)
            right = max(left + max(w, 1), left + 1)
            bottom = max(top + max(h, 1), top + 1)

            # clamp to image bounds
            left = max(0, min(left, width - 1))
            top = max(0, min(top, height - 1))
            right = max(left + 1, min(right, width))
            bottom = max(top + 1, min(bottom, height))

            # seals -> direct sensitive region
            label = getattr(item, 'label', 'text') or 'text'
            if label == "seal" or item.text.strip() == "[公章]":
                region = SensitiveRegion(
                    text="[公章]",
                    entity_type="SEAL",
                    left=left,
                    top=top,
                    width=right - left,
                    height=bottom - top,
                    confidence=item.confidence,
                    source="paddleocr_vl",
                    color=_SEAL_REGION_COLOR,
                )
                visual_regions.append(region)
                logger.info(
                    "Found SEAL @ (%d, %d, %d, %d)",
                    left,
                    top,
                    right - left,
                    bottom - top,
                )
                continue

            polygon = [
                [left, top],
                [right, top],
                [right, bottom],
                [left, bottom],
            ]
            blocks.append(OCRTextBlock(
                text=item.text,
                polygon=polygon,
                confidence=float(item.confidence),
            ))

        if cacheable:
            _set_cached_ocr_output(cache_key, blocks, visual_regions)
    except Exception as e:
        _finish_ocr_output_inflight(cache_key, inflight, None, e)
        raise
    _finish_ocr_output_inflight(cache_key, inflight, (blocks, visual_regions))
    _record_ocr_stage_duration(stage_status, "vl", stage_start)
    return blocks, visual_regions
