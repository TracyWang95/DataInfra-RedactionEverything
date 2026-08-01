"""PaddleOCR-VL / PP-StructureV3 extraction orchestration.

Split out of ocr_pipeline.py (which stays the public facade): run_paddle_ocr
routing (structure-primary, VL supplement, structure fallback), the table-line
heuristic, service result conversion and the low-level VL/structure service
calls with caching and in-flight dedupe.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

from PIL import Image

from app.core.config import settings
from app.services.ocr_has_vision_service import OCRTextBlock, SensitiveRegion
from app.services.vision.has_text_payload import (
    _canonical_image_text_type,
    _compact_text,
    _strip_vl_math_markup,
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

# Seal sentinel — cross-service contract with backend/scripts/ocr_server.py
# (SEAL_TEXT + the VL layout 'seal' class label): the OCR service emits a seal
# block as label="seal" with text=SEAL_TEXT. Single-sourced here for the two
# consumer sites below; keep in sync with ocr_server.py:SEAL_TEXT.
_OCR_SEAL_LABEL = "seal"
_OCR_SEAL_TEXT = "[公章]"


def _is_seal_ocr_item(label: object, text: object) -> bool:
    return str(label or "") == _OCR_SEAL_LABEL or str(text or "").strip() == _OCR_SEAL_TEXT


def _recover_under_seal_vl_text(vl_blocks, structure_blocks, seal_regions):
    """Recover the VL text a stamp sits on — exactly where PP-Structure breaks.

    A 乙方 red seal stamped across 海南工程服务有限公司 makes PP-StructureV3 shatter that
    line into stray fragments its NER can't type (or garble it), while PaddleOCR-VL's
    parsing reads the whole line. We normally DISCARD all VL text (merging it wholesale
    re-broke geometry — the 身份证 two-column giant box, the 日期 block that swallowed a
    signature). Recover a VL block ONLY when it overlaps a detected seal region: that
    confines the gain to stamp-obscured text and can never touch the non-seal regions
    where merging VL text did the damage (those blocks intersect no seal). We ADD the
    block (never overwrite a PP block's char boxes, so no giant-box regression); a
    charless VL block masks whole, which under a stamp is exactly right. Plain rectangle
    intersection — no threshold, no magic number.

    One exclusion: a stamp sitting only at a line's RIGHT edge does not shatter it — PP
    still reads the whole printed line as ONE char-boxed block (甲方：中海油…有限公司).
    Adding a charless VL duplicate on top then re-boxes the 甲方：field label whole,
    because a charless block masks its entire width. So skip recovery where a single
    char-boxed structure block solely covers the VL line (the same mutual-single overlap
    _vl_correct_charless_blocks uses): PP's real glyph geometry already crops that line
    to its value. A line a stamp TRULY shatters leaves multiple fragments or a charless
    block — never one covering char-boxed block — so genuine recovery is untouched.
    """
    if not vl_blocks or not seal_regions:
        return []

    def _intersects(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    seal_rects = [(r.left, r.top, r.left + r.width, r.top + r.height) for r in seal_regions]
    charboxed = [b for b in structure_blocks if getattr(b, "chars", None)]
    out = []
    for blk in vl_blocks:
        if not any(_intersects(blk.bbox, s) for s in seal_rects):
            continue
        covering = [p for p in charboxed if _intersects(blk.bbox, p.bbox)]
        if len(covering) == 1 and sum(
            1 for v in vl_blocks if _intersects(covering[0].bbox, v.bbox)
        ) == 1:
            continue
        out.append(blk)
    return out


def _recover_pp_missed_vl_text(vl_blocks, structure_blocks):
    """Recover a line PP-Structure missed ENTIRELY, that a VL paragraph carries.

    On the PP-primary path VL text is discarded, but PP-OCRv6 sometimes drops a faint
    line outright — the 法定代理人 line '…龙继临，男，1987年8月6日出生…' with its name and
    birthdate — while PaddleOCR-VL parses the whole paragraph. VL hands over only a
    charless paragraph rectangle (no per-line boxes), so the missed line's text and
    place are found by SUBTRACTION from the two engines' own output:

      • the PP lines OF THIS paragraph are the structure blocks whose y-CENTRE lies in
        the VL band and whose text is a substring of the VL text (the centre test
        rejects a same-text line from another paragraph and a short coincidence '号。');
      • the VL text they cover is the paragraph MINUS the missed line, so each remaining
        run is a line PP dropped, placed in the strip above/between/below.

    Two guards: strip VL's LaTeX form-fill markup ('$\\underline{\\text{河南新乡市}}$') so
    the run matches the markup-free entity; drop a run whose band is far shorter than the
    paragraph's line height (a handwritten FILL between two same-line labels, not a line).
    The emitted block is flagged recovered=True — additive, never overwrites a PP char box,
    and excluded downstream from the amount digit-propagation (an area '100' is not money).
    """
    if not vl_blocks or not structure_blocks:
        return []

    def _x_overlap(a, b):
        return a[0] < b[2] and b[0] < a[2]

    missed: list[tuple[str, int, int, int, int, float]] = []
    for vl in vl_blocks:
        vt = str(getattr(vl, "text", "") or "")
        if not vt or getattr(vl, "chars", None):
            continue
        vx1, vy1, vx2, vy2 = vl.bbox
        covered = []
        for s in structure_blocks:
            st = str(getattr(s, "text", "") or "").strip()
            scy = (s.bbox[1] + s.bbox[3]) / 2
            if st and vy1 <= scy <= vy2 and _x_overlap(vl.bbox, s.bbox) and st in vt:
                pos = vt.find(st)
                covered.append((pos, pos + len(st), s))
        if not covered:
            continue
        covered.sort()
        heights = sorted(c[2].bbox[3] - c[2].bbox[1] for c in covered)
        row = heights[len(heights) // 2]
        cursor = 0
        for i, (cs, ce, blk) in enumerate(covered):
            if cs > cursor:
                top = covered[i - 1][2].bbox[3] if i > 0 else vy1
                missed.append((vt[cursor:cs], vx1, top, vx2, blk.bbox[1], row))
            cursor = max(cursor, ce)
        if cursor < len(vt):
            missed.append((vt[cursor:], vx1, covered[-1][2].bbox[3], vx2, vy2, row))

    out = []
    for run, x1, top, x2, bot, row in missed:
        run = _strip_vl_math_markup(run).strip()
        if run and (bot - top) >= row * 0.5:
            out.append(OCRTextBlock(
                text=run, polygon=[[x1, top], [x2, top], [x2, bot], [x1, bot]], recovered=True
            ))
    return out


def _vl_correct_charless_blocks(structure_blocks, vl_blocks):
    """Let PaddleOCR-VL correct the text of a hard line PP-OCRv6 garbled.

    PP-OCRv6_medium sometimes misreads a clean printed line and returns it CHARLESS
    (no per-char boxes — it could not confidently segment it): the 签字上方 date
    2016年12月20号 came back as "201010". VL's parsing reads such lines correctly. Where
    a charless PP block has exactly ONE PaddleOCR-VL counterpart covering the same
    region (mutual sole overlap) and VL read DIFFERENT text, adopt VL's read. Two hard
    guards keep this from reviving old damage: (1) charless-only — a block WITH char
    boxes is a confident line whose text↔charbox geometry must stay coherent, and
    rewriting it is exactly what exploded the 身份证 two-column block into a giant box;
    (2) 1:1 — VL blocks that merge several PP lines are skipped, so no cross-line
    smear. Text only; PP keeps its geometry. Parameter-free — rectangle overlap +
    mutual-single, no threshold, no magic number.
    """
    if not vl_blocks:
        return structure_blocks

    def _intersects(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    from dataclasses import replace
    out = []
    for pp in structure_blocks:
        if not getattr(pp, "chars", None):
            overlapping_vl = [v for v in vl_blocks if _intersects(pp.bbox, v.bbox)]
            if len(overlapping_vl) == 1:
                v = overlapping_vl[0]
                if sum(1 for p2 in structure_blocks if _intersects(v.bbox, p2.bbox)) == 1:
                    vt = str(getattr(v, "text", "") or "").strip()
                    if vt and vt != str(getattr(pp, "text", "") or "").strip():
                        out.append(replace(pp, text=vt))
                        continue
        out.append(pp)
    return out


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

    # Speculatively fire the PaddleOCR-VL supplement in parallel with
    # PP-StructureV3. Both read the same image with independent engines
    # (PP-Structure on the OCR sidecar's paddle GPU, VL on the vLLM server), so
    # running them concurrently makes the OCR wall-clock max(structure, VL)
    # instead of the sum. When needs_text_precision + SUPPLEMENT_VL hold the
    # supplement runs regardless of the structure block count (and the sparse
    # fallback reuses the same result), so the parallel call is never wasted.
    _vl_state: dict = {"thread": None, "result": {}}

    def _supplement_vl_blocks() -> tuple[list[OCRTextBlock], list[SensitiveRegion]]:
        thread = _vl_state["thread"]
        if thread is not None:
            thread.join()
            result = _vl_state["result"]
            if "e" in result:
                raise result["e"]
            return result["r"]
        return _run_ocr_service(
            image,
            ocr_service,
            stage_status=stage_status,
            image_bytes=image_bytes(),
            service_available_checked=True,
        )

    if use_structure_primary:
        if not vl_disabled and needs_text_precision and bool(settings.OCR_STRUCTURE_PRIMARY_SUPPLEMENT_VL):
            image_bytes()  # memoize the PNG encode once so the two threads don't race it

            def _run_vl_supplement() -> None:
                try:
                    _vl_state["result"]["r"] = _run_ocr_service(
                        image, ocr_service, None, image_bytes(), True
                    )
                except BaseException as exc:  # surfaced by _supplement_vl_blocks
                    _vl_state["result"]["e"] = exc

            _vl_state["thread"] = threading.Thread(target=_run_vl_supplement, daemon=True)
            _vl_state["thread"].start()
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
                # VL is SEAL-ONLY: PP-StructureV3 owns ALL text; PaddleOCR-VL runs
                # only for its visual regions (seals) and its coarse text blocks are
                # DISCARDED. Merging VL text (overwrite OR add) is what broke the
                # pipeline the moment VL was enabled — the 身份证 two-column giant
                # box, a bordered 日期 cell boxed whole so the real signature folded
                # into it and vanished, spurious extra entities. A/B (VL on vs off,
                # real docs) proved VL's text supplement recovered nothing it claimed
                # (under-seal 公司名 stayed missed either way) while systematically
                # polluting geometry + NER. char-box attach still recovers
                # PP-Structure's OWN charless lines.
                _vl_blocks, vl_visual_regions = _supplement_vl_blocks()
                primary_structure_blocks = _vl_correct_charless_blocks(
                    primary_structure_blocks, _vl_blocks
                )
                merged_blocks = _attach_chars_to_charless_blocks(
                    list(primary_structure_blocks), image, ocr_service
                )
                # Recovered under-seal VL blocks are charless — re-OCR them for per-char
                # boxes too, so an entity on them (甲方：中海油…) crops to the value's
                # glyphs instead of the whole block (which would box the 甲方： label).
                merged_blocks += _attach_chars_to_charless_blocks(
                    _recover_under_seal_vl_text(_vl_blocks, merged_blocks, vl_visual_regions),
                    image,
                    ocr_service,
                )
                # Also recover a line PP-Structure missed ENTIRELY that a VL paragraph
                # carries (the faint 法定代理人 line's name+birthdate). Flagged recovered=True
                # so the amount digit-propagation skips it (a re-derived area line isn't money).
                merged_blocks += _attach_chars_to_charless_blocks(
                    _recover_pp_missed_vl_text(_vl_blocks, primary_structure_blocks),
                    image,
                    ocr_service,
                )
                logger.info(
                    "PP-StructureV3 primary OCR: %d blocks (VL text discarded — seal-only)",
                    len(primary_structure_blocks),
                )
                return merged_blocks, [*primary_structure_visual_regions, *vl_visual_regions]
            if needs_ocr_visual_regions and not primary_structure_visual_regions and not vl_disabled:
                # VL SEAL-ONLY (see rationale above): PP-StructureV3 produced no
                # visual regions, so PaddleOCR-VL runs ONLY to supply the seal
                # regions it missed. Its coarse text blocks are DISCARDED — merging
                # them polluted the text pipeline for a supplement A/B proved
                # worthless. char-box attach still recovers PP-Structure's own
                # charless lines.
                _vl_blocks, vl_visual_regions = _supplement_vl_blocks()
                primary_structure_blocks = _vl_correct_charless_blocks(
                    primary_structure_blocks, _vl_blocks
                )
                merged_blocks = _attach_chars_to_charless_blocks(
                    list(primary_structure_blocks), image, ocr_service
                )
                # Recovered under-seal VL blocks are charless — re-OCR them for per-char
                # boxes too, so an entity on them (甲方：中海油…) crops to the value's
                # glyphs instead of the whole block (which would box the 甲方： label).
                merged_blocks += _attach_chars_to_charless_blocks(
                    _recover_under_seal_vl_text(_vl_blocks, merged_blocks, vl_visual_regions),
                    image,
                    ocr_service,
                )
                # Also recover a line PP-Structure missed ENTIRELY that a VL paragraph
                # carries (the faint 法定代理人 line's name+birthdate). Flagged recovered=True
                # so the amount digit-propagation skips it (a re-derived area line isn't money).
                merged_blocks += _attach_chars_to_charless_blocks(
                    _recover_pp_missed_vl_text(_vl_blocks, primary_structure_blocks),
                    image,
                    ocr_service,
                )
                logger.info(
                    "PP-StructureV3 primary OCR found %d blocks, no visual regions; "
                    "PaddleOCR-VL supplied %d visual regions (VL text discarded — seal-only)",
                    len(primary_structure_blocks),
                    len(vl_visual_regions),
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

    blocks, visual_regions = _supplement_vl_blocks()
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
    # A charless PaddleOCR-VL paragraph block reaches the matcher with no glyph
    # geometry, so an entity matched on it falls back to the WHOLE-block box — which
    # pulls a leading field label ("甲方：中海油…") into the redaction box even though
    # the value span starts after the colon. Recover per-char boxes by re-OCR (the
    # same text-preserving pass the PP-primary return paths already run at 269/291),
    # so the matcher crops to the value's own glyphs and the label is left outside.
    # Model-centric: geometry from real re-OCR, no estimation. (Was wired on the
    # PP-primary paths but not this VL-primary one — the missing line, not new logic.)
    blocks = _attach_chars_to_charless_blocks(blocks, image, ocr_service)
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
        if _is_seal_ocr_item(label, text):
            region = SensitiveRegion(
                text=_OCR_SEAL_TEXT,
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
    charless = [block for block in blocks if not getattr(block, "chars", None)]
    if not charless:
        return blocks
    # Recover each charless block on its own worker (the OCR sidecars serialize
    # PP-Structure per GPU, so client-side crop-level fan-out just queues at the
    # server — block-level parallelism is what the two sidecars actually absorb).
    # Within a block the whole-block crop runs FIRST and the three half-width
    # sweeps only fire when it did not read the line end to end. On a clean page
    # the crop reads whole, so this is 1 crop per block instead of 4 — the
    # dominant OCR cost — and the sweeps would only re-detect the same text and
    # get deduped away.
    #
    # "Empty" is NOT the right gate. det does not only survive or die wholesale:
    # on the 农业合同 row it survives on the right segment and dies on the
    # underline+handwriting left half, so the crop returns a PARTIAL line. Gating
    # on empty skipped the sweeps exactly there and the left half kept no char
    # boxes at all, which is what makes the row fall back to a full-width slab.
    def _recover(block: OCRTextBlock) -> None:
        crops = _charless_block_crops(block, width, height)
        if not crops:
            return
        whole = _crop_char_segments(image, ocr_service, crops[0])
        if _segments_reach_both_edges(whole, crops[0]):
            _apply_char_segments(block, [whole])
            return
        sweeps = [_crop_char_segments(image, ocr_service, crop) for crop in crops[1:]]
        _apply_char_segments(block, [whole, *sweeps])

    if len(charless) == 1:
        _recover(charless[0])
        return blocks
    max_workers = min(len(charless), max(1, int(os.environ.get("OCR_REOCR_CONCURRENCY", "16") or "16")))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_recover, charless))
    return blocks


def _charless_block_crops(
    block: OCRTextBlock, width: int, height: int
) -> list[tuple[int, int, int, int]]:
    """Whole-block crop plus three anchored half-width sweep windows for one
    charless block ([] if degenerate). The engine's det collapses on an
    underline+handwriting row at block width (the 农业 row-1 printed label AND
    handwritten value both vanish) yet reads the same pixels inside a half-width
    window; same start/center/end half-size anchoring as the tile retry
    (_axis_positions), so anything narrower than half a window is whole inside at
    least one sweep."""
    left, top = max(0, int(block.left)), max(0, int(block.top))
    right = min(width, int(block.left + block.width))
    bottom = min(height, int(block.top + block.height))
    if right - left < 4 or bottom - top < 4:
        return []
    crops = [(left, top, right, bottom)]
    window = max(1, (right - left) // 2)
    crops.extend(
        (left + x0, top, min(right, left + x0 + window), bottom)
        for x0 in _axis_positions(right - left, window)
    )
    return crops


def _crop_char_segments(
    image: Image.Image, ocr_service: Any, crop: tuple[int, int, int, int]
) -> list:
    """Re-OCR one crop and return its (page-coord bbox, page-coord chars)
    segments — NO dedup (the caller dedups across a block's crops in order)."""
    crop_left, crop_top, crop_right, crop_bottom = crop
    try:
        crop_blocks, _ = _run_structure_service_with_visuals(
            image.crop((crop_left, crop_top, crop_right, crop_bottom)), ocr_service
        )
    except Exception as exc:
        logger.info("charless-block re-OCR failed: %s", exc)
        return []
    segments: list = []
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
        segments.append(((x1, y1, x2, y2), chars))
    return segments



def _segments_reach_both_edges(segments: list, crop: tuple[int, int, int, int]) -> bool:
    """Did this crop's read cover the line end to end?

    Tolerance is one recovered character's own width — a physical size measured
    off this page, not a tuned constant. A read that stops short of either edge
    left ink unread, so the sweeps still have work to do.
    """
    if not segments:
        return False
    crop_left, _crop_top, crop_right, _crop_bottom = crop
    read_left = min(bbox[0] for bbox, _chars in segments)
    read_right = max(bbox[2] for bbox, _chars in segments)
    widths = [
        float(char["x2"]) - float(char["x1"])
        for _bbox, chars in segments
        for char in chars
        if char.get("x2") is not None and char.get("x1") is not None
    ]
    if not widths:
        return False
    tolerance = max(widths)
    return read_left - crop_left <= tolerance and crop_right - read_right <= tolerance


def _apply_char_segments(block: OCRTextBlock, crop_segments_in_order: list) -> None:
    """Dedup a block's crop segments (first-seen wins, whole-block crop first)
    and attach them as the block's chars in reading order. No-op if nothing was
    recovered (the block stays a safe whole-block mask)."""
    kept_segments: list = []  # (page-coord bbox, page-coord chars)
    for segments in crop_segments_in_order:
        for (x1, y1, x2, y2), chars in segments:
            # Region-overlap identity dedupe: a segment overlapping an
            # already-kept one in BOTH x and y is the same physical text
            # re-detected through another window — first seen (the whole-block
            # crop) wins. A same-row segment at a new x range joins.
            if any(
                x1 < kx2 and kx1 < x2 and y1 < ky2 and ky1 < y2
                for (kx1, ky1, kx2, ky2), _kc in kept_segments
            ):
                continue
            kept_segments.append(((x1, y1, x2, y2), chars))
    if not kept_segments:
        return
    # Reading order across all kept segments: same row identity as _reading_order
    # (rows do not overlap in y; same-row segments do), then left-to-right.
    segment_blocks = [
        SimpleNamespace(
            top=bbox[1], left=bbox[0], height=bbox[3] - bbox[1], width=bbox[2] - bbox[0], chars=chars
        )
        for bbox, chars in kept_segments
    ]
    block.chars = [
        ch for seg in _reading_order(segment_blocks) for ch in seg.chars
    ]


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
            if _is_seal_ocr_item(label, item.text):
                region = SensitiveRegion(
                    text=_OCR_SEAL_TEXT,
                    entity_type="SEAL",
                    left=left,
                    top=top,
                    width=right - left,
                    height=bottom - top,
                    confidence=item.confidence if item.confidence is not None else _DEFAULT_OCR_ITEM_CONFIDENCE,
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
                confidence=float(getattr(item, "confidence", _DEFAULT_OCR_ITEM_CONFIDENCE) or _DEFAULT_OCR_ITEM_CONFIDENCE),
            ))

        if cacheable:
            _set_cached_ocr_output(cache_key, blocks, visual_regions)
    except Exception as e:
        _finish_ocr_output_inflight(cache_key, inflight, None, e)
        raise
    _finish_ocr_output_inflight(cache_key, inflight, (blocks, visual_regions))
    _record_ocr_stage_duration(stage_status, "vl", stage_start)
    return blocks, visual_regions
