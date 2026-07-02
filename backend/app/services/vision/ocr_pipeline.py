"""
OCR Pipeline - PaddleOCR text extraction + HaS NER sensitive entity detection.

Responsibilities:
- Running PaddleOCR-VL microservice to extract text blocks and visual regions
- HTML table cell extraction and expansion
- Running HaS local NER model on OCR text to identify sensitive entities
- Matching NER entities back to OCR bounding boxes (exact + fuzzy)
- Matching OCR text selected by HaS Text back to document coordinates
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import io
import logging
import threading
import time
from collections import OrderedDict
from difflib import SequenceMatcher
from html.parser import HTMLParser
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from app.core.config import settings
from app.core.visual_feature_categories import VISUAL_ONLY_ENTITY_TYPES
from app.models.type_mapping import TYPE_CN_TO_ID, TYPE_ID_TO_CN, has_query_labels_for
from app.services.ocr_has_vision_service import OCRTextBlock, SensitiveRegion
from app.services.vision.has_text_payload import (
    DEFAULT_HAS_TEXT_TYPE_IDS,
    _build_has_text_payload,
    _build_has_text_type_names,
    _canonical_image_text_type,
    _compact_text,
    _filter_blocks_for_has_text,
)

logger = logging.getLogger(__name__)


TABLE_PRECISION_ENTITY_TYPES = {
    "AMOUNT",
    "BANK_ACCOUNT",
    "ACCOUNT_NUMBER",
    "BANK_CARD",
    "COMPANY_CODE",
    "CONTRACT_NO",
}

OCR_VISUAL_ENTITY_TYPES = VISUAL_ONLY_ENTITY_TYPES

# --- Tuning constants (extracted magic numbers) -------------------------------
# Window (seconds) for treating a recent negative HaS health check as still valid.
_HAS_NEGATIVE_HEALTH_TTL_SEC = 5.0

# Default fallback median text-line height (px) when no block heights are known.
# Amount-pair lookback: scan this many chars before the entity for 大写/小写 markers.
_AMOUNT_PAIR_LOOKBACK_CHARS = 48
# Sentinel "infinitely far" tail distance when no 小写 marker is present.
_AMOUNT_PAIR_NO_LOWER_MARKER_UNITS = 999.0
# Max visual units between 小写 marker and amount to treat as one upper/lower pair.
_AMOUNT_PAIR_MAX_LOWER_TAIL_UNITS = 8.0

# Standalone-amount digit-count bounds.
_STANDALONE_AMOUNT_MIN_DIGITS = 4
_STANDALONE_AMOUNT_MAX_DIGITS = 14
# Probable amount-token digit-count bounds (with/without thousands separators).
# An amount value signature drops a trailing ".00"; require more than this many digits first.
_AMOUNT_TRAILING_ZEROS_MIN_DIGITS = 2

# Visual-row grouping tolerance: fraction of median block height, with a floor.
# Amount-table column detection needs at least this many cells in a header row.
# Horizontal padding around an amount column header: fraction of header width, with a floor.
# Slack (px) below a header baseline when testing column membership.
# Person form-field value visual-unit bounds and label-proximity tuning.
# Loose person-form expansion: max trailing-suffix length to treat as same value.
# Quality scoring weights for person form-field candidate ranking.
# Drop a person candidate whose block overlaps an already-selected block by this ratio.
# Visual-line same-line tests.
_SAME_LINE_VERTICAL_OVERLAP_RATIO = 0.35
_SAME_LINE_CENTER_HEIGHT_RATIO = 0.65
# Visual-line join gap cap: max(floor px, typical height * multiplier).
_VISUAL_LINE_JOIN_GAP_MIN_PX = 28
_VISUAL_LINE_JOIN_GAP_HEIGHT_MULT = 3.2
# Short-CJK-prefix bridging bounds.
_BRIDGE_LEFT_MIN_LEN = 2
_BRIDGE_LEFT_MAX_LEN = 6
_BRIDGE_RIGHT_MIN_LEN = 4
_BRIDGE_RIGHT_MAX_LEN = 24
_BRIDGE_COMBINED_MAX_LEN = 30
_BRIDGE_LEFT_MIN_CJK = 2
_BRIDGE_RIGHT_MIN_CJK = 3
# Confidence discount applied to a unioned (reconstructed) virtual block.
_UNION_BLOCK_CONFIDENCE_FACTOR = 0.95
# Tall non-text glyph filter for visual-line reconstruction.
_RECONSTRUCT_TALL_HEIGHT_MULT = 2.4
_RECONSTRUCT_TALL_ASPECT_MULT = 1.8

# Blank-page detection: minimum dimensions and ink-ratio thresholds.
_BLANK_PAGE_MIN_WIDTH_PX = 600
_BLANK_PAGE_MIN_HEIGHT_PX = 800
_BLANK_PAGE_THUMBNAIL_PX = 512
_BLANK_PAGE_DARK_PIXEL_MAX = 180
_BLANK_PAGE_INK_PIXEL_MAX = 230
_BLANK_PAGE_DARK_RATIO_MAX = 0.00002
_BLANK_PAGE_INK_RATIO_MAX = 0.0001

# Table-line heuristic: downsample size, dimension floor, darkness and line-count thresholds.
_TABLE_HEURISTIC_THUMBNAIL_PX = 640
_TABLE_HEURISTIC_MIN_DIM_PX = 80
_TABLE_HEURISTIC_DARK_PIXEL_MAX = 90
_TABLE_HEURISTIC_HORIZONTAL_DARK_RATIO = 0.35
_TABLE_HEURISTIC_VERTICAL_DARK_RATIO = 0.25
_TABLE_HEURISTIC_MIN_LINES = 3

# Coarse multi-line block detection.
_COARSE_MULTILINE_MIN_COMPACT_LEN = 40
_COARSE_MULTILINE_HEIGHT_MULT = 1.7

# Default OCR-item confidence when the service omits one.
_DEFAULT_OCR_ITEM_CONFIDENCE = 0.9

# OCR-block merge IOU thresholds and structure-precision supplement bounds.
_MERGE_DUPLICATE_IOU = 0.5
_MERGE_OVERLAP_IOU = 0.85
_SHORT_FIELD_MIN_COMPACT_LEN = 4
_SHORT_FIELD_MAX_COMPACT_LEN = 80
_SHORT_FIELD_MAX_DELIMITERS = 4
_SUPPLEMENT_WIDTH_RATIO = 1.2
_SUPPLEMENT_HEIGHT_RATIO = 2.2
_SUPPLEMENT_SIMILARITY_MIN = 0.55
_SUPPLEMENT_WIDER_RATIO = 1.1
_SUPPLEMENT_LONGER_TEXT_MARGIN = 6

# Red stamp pixel test thresholds.
_RED_STAMP_MIN_RED = 115
_RED_STAMP_RED_MINUS_GREEN = 30
_RED_STAMP_RED_MINUS_BLUE = 30
_RED_STAMP_OTHER_CHANNEL_FLOOR = 135
_RED_STAMP_OTHER_CHANNEL_RATIO = 0.78

# Seal-splitting geometry and red-row projection tuning.
_SEAL_SPLIT_MIN_DIM_PX = 40
_SEAL_SPLIT_MIN_ASPECT = 1.25
_SEAL_SPLIT_MIN_WIDTH_PX = 80
_SEAL_SPLIT_MIN_WIDTH_IMG_RATIO = 0.075
_SEAL_SMOOTH_RADIUS_MIN = 2
_SEAL_SMOOTH_RADIUS_MAX = 7
_SEAL_SMOOTH_RADIUS_HEIGHT_DIVISOR = 80
_SEAL_ACTIVE_THRESHOLD_MIN = 12
_SEAL_ACTIVE_THRESHOLD_WIDTH_RATIO = 0.10
_SEAL_CLOSE_GAP_MIN = 8
_SEAL_CLOSE_GAP_MAX = 24
_SEAL_CLOSE_GAP_HEIGHT_DIVISOR = 18
_SEAL_MIN_BAND_HEIGHT_MIN = 28
_SEAL_MIN_BAND_HEIGHT_MAX = 90
_SEAL_MIN_BAND_HEIGHT_WIDTH_RATIO = 0.35
_SEAL_PEAK_PROMINENCE_RATIO = 0.35
_SEAL_PEAK_MIN_DISTANCE_MIN = 48
_SEAL_PEAK_MIN_DISTANCE_WIDTH_RATIO = 0.55
_SEAL_MAX_PEAKS = 4
_SEAL_HALF_BAND_MIN = 64
_SEAL_HALF_BAND_WIDTH_RATIO = 0.52
_SEAL_BAND_BOX_MIN_PX = 24
_SEAL_BAND_BOX_MIN_WIDTH_RATIO = 0.18
_SEAL_BAND_PAD_MIN = 6
_SEAL_BAND_PAD_RATIO = 0.06

# Seal region overlay color (legacy /ocr path).
_SEAL_REGION_COLOR = (255, 0, 0)

# HTML table virtual-cell confidence discount.
_TABLE_CELL_CONFIDENCE_FACTOR = 0.9

# Bridge NER payload character cap.
_BRIDGE_PAYLOAD_MAX_CHARS = 1200
# Minimum entity text length by type for NER results.
_NER_DEFAULT_MIN_LEN = 2
_NER_MIN_LEN_BY_TYPE = {
    "PERSON": 2,
    "ORG": 2,
    "ADDRESS": 4,
}

# Document-title visual suffix lookahead (chars) for PROPERTY entities.
_PROPERTY_TITLE_TAIL_LOOKAHEAD_CHARS = 12

# Semantic vocabulary (data, not tuning): a table cell whose text IS one of
# these labels — optionally with a parenthesized unit suffix such as 单价（元）
# — declares its column to contain amount values.
AMOUNT_HEADER_LABELS = (
    "金额",
    "单价",
    "合价",
    "总价",
    "价格",
    "价款",
    "费用",
)
# Full- and half-width parentheses accepted around a header unit suffix.
_PAREN_OPEN_CHARS = "（("
_PAREN_CLOSE_CHARS = "）)"
# Characters allowed in an amount-formatted value (digits plus separators,
# currency symbols and grouping decoration). Shared by the standalone-amount
# block test and the table-cell amount-format test.
_AMOUNT_FORMAT_ALLOWED_CHARS = set("0123456789.,，￥¥$€£-()（）[] ")

# Per-character visual-unit weights.
_CHAR_UNIT_SPACE = 0.25
_CHAR_UNIT_CJK = 1.0
_CHAR_UNIT_ALNUM = 0.56
_CHAR_UNIT_PUNCT = 0.35
_CHAR_UNIT_OTHER = 0.65
_CHAR_UNIT_MIN_TOTAL = 0.01

# Form-field label/value width tuning.
# Visual-wrap break search window and scoring.
# Typical text-line height inference: minimum block height to consider.
_TEXTLINE_MIN_HEIGHT_PX = 4

# Entity-region estimation tuning.
# Entity-to-OCR matching: fuzzy match and per-type width-cap tuning.
_FUZZY_MATCH_MIN_ENTITY_LEN = 4
_FUZZY_MATCH_BLOCK_LEN_MULT = 3
_FUZZY_MATCH_BLOCK_LEN_FLOOR = 24
_FUZZY_MATCH_RATIO = 0.9
_FUZZY_MATCH_CONFIDENCE = 0.9
_TABLE_FALLBACK_CONFIDENCE = 0.8

_OCR_TEXT_BLOCK_CACHE_LOCK = threading.Lock()
_OCR_TEXT_BLOCK_CACHE: OrderedDict[
    tuple[Any, ...],
    tuple[float, list[OCRTextBlock], list[SensitiveRegion]],
] = OrderedDict()
_OCR_TEXT_BLOCK_INFLIGHT_LOCK = threading.Lock()
_OCR_TEXT_BLOCK_INFLIGHT: dict[tuple[Any, ...], _OcrOutputInflight] = {}
_HAS_TEXT_NER_INFLIGHT: dict[tuple[Any, ...], asyncio.Future] = {}
_HAS_TEXT_NER_INFLIGHT_LOOP: asyncio.AbstractEventLoop | None = None


class _OcrOutputInflight:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: tuple[list[OCRTextBlock], list[SensitiveRegion]] | None = None
        self.error: BaseException | None = None


def _copy_has_text_ner_result(
    result: Any,
) -> Any:
    if not isinstance(result, dict):
        return None
    return {
        key: list(value) if isinstance(value, list) else value
        for key, value in result.items()
    }


def _has_text_ner_inflight_key(
    has_client: Any,
    text_content: str,
    chinese_types: list[str],
) -> tuple[Any, ...]:
    identity: Any = type(has_client).__qualname__
    effective_base_url = getattr(has_client, "_effective_base_url", None)
    if callable(effective_base_url):
        try:
            identity = effective_base_url()
        except Exception:
            logger.debug("HaS client identity lookup failed", exc_info=True)
    else:
        identity = getattr(has_client, "base_url", identity)
    digest = hashlib.sha256(text_content.encode("utf-8", errors="ignore")).hexdigest()
    return (identity, tuple(chinese_types), digest)


def _begin_has_text_ner_inflight(
    key: tuple[Any, ...],
) -> tuple[bool, asyncio.Future]:
    global _HAS_TEXT_NER_INFLIGHT_LOOP
    loop = asyncio.get_running_loop()
    if _HAS_TEXT_NER_INFLIGHT_LOOP is not loop:
        _HAS_TEXT_NER_INFLIGHT.clear()
        _HAS_TEXT_NER_INFLIGHT_LOOP = loop

    future = _HAS_TEXT_NER_INFLIGHT.get(key)
    if future is not None:
        return False, future

    future = loop.create_future()
    _HAS_TEXT_NER_INFLIGHT[key] = future
    return True, future


def _finish_has_text_ner_inflight(
    key: tuple[Any, ...],
    future: asyncio.Future,
    result: Any,
) -> None:
    if _HAS_TEXT_NER_INFLIGHT.get(key) is future:
        _HAS_TEXT_NER_INFLIGHT.pop(key, None)
    if not future.done():
        future.set_result(_copy_has_text_ner_result(result))


def _has_recent_negative_health(has_client: Any) -> bool:
    checked_at = float(getattr(has_client, "_health_checked_at", 0.0) or 0.0)
    if checked_at <= 0:
        return False
    if bool(getattr(has_client, "_health_ready", False)):
        return False
    return time.monotonic() - checked_at < _HAS_NEGATIVE_HEALTH_TTL_SEC


def _get_cached_has_text_ner(
    has_client: Any,
    text_content: str,
    chinese_types: list[str],
) -> dict[str, list[str]] | None:
    getter = getattr(has_client, "get_cached_ner", None)
    if not callable(getter):
        return None
    try:
        cached = getter(text_content, chinese_types)
    except Exception:
        logger.debug("HaS NER cache lookup failed", exc_info=True)
        return None
    return cached if isinstance(cached, dict) else None


def _clone_text_block(block: OCRTextBlock) -> OCRTextBlock:
    return OCRTextBlock(
        text=block.text,
        polygon=[[float(point[0]), float(point[1])] for point in block.polygon],
        confidence=float(block.confidence),
        chars=[dict(char_box) for char_box in block.chars],
    )


def _clone_sensitive_region(region: SensitiveRegion) -> SensitiveRegion:
    return SensitiveRegion(
        text=region.text,
        entity_type=region.entity_type,
        left=int(region.left),
        top=int(region.top),
        width=int(region.width),
        height=int(region.height),
        confidence=float(region.confidence),
        source=region.source,
        color=tuple(region.color),
    )


def _clone_ocr_output(
    blocks: list[OCRTextBlock],
    visual_regions: list[SensitiveRegion],
) -> tuple[list[OCRTextBlock], list[SensitiveRegion]]:
    return (
        [_clone_text_block(block) for block in blocks],
        [_clone_sensitive_region(region) for region in visual_regions],
    )



def _record_ocr_cache_stage(
    stage_status: dict[str, Any] | None,
    stage: str,
    status: str,
) -> None:
    if stage_status is None:
        return
    stage_status[f"ocr_{stage}_cache_status"] = status
    if status == "hit":
        stage_status[f"ocr_{stage}_cache_hit"] = True
        stage_status["ocr_cache_hits"] = int(stage_status.get("ocr_cache_hits", 0) or 0) + 1
    elif status == "miss":
        stage_status[f"ocr_{stage}_cache_hit"] = False
        stage_status["ocr_cache_misses"] = int(stage_status.get("ocr_cache_misses", 0) or 0) + 1


def _record_ocr_stage_duration(
    stage_status: dict[str, Any] | None,
    stage: str,
    started_at: float,
) -> None:
    if stage_status is None:
        return
    key = f"ocr_{stage}_ms"
    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
    stage_status[key] = int(stage_status.get(key, 0) or 0) + elapsed_ms


def _record_has_text_metric(
    stage_status: dict[str, Any] | None,
    key: str,
    value: Any,
) -> None:
    if stage_status is not None:
        stage_status[key] = value


def _compact_amount_candidate(text: str) -> str:
    return _compact_text(text).strip(" \t\r\n:：;；,，.。()（）[]【】$¥￥")


def _amount_digit_count(text: str) -> int:
    return sum(1 for ch in text if ch.isdigit())


def _amount_digit_signature(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _amount_value_signature(text: str) -> str:
    """Normalize display variants of the same amount for dedupe.

    This is deliberately a value-level helper, not a detector. HaS still decides
    whether text is an amount; this only prevents OCR supplements such as
    1431400 and 1431400.00 from being kept as separate findings.
    """
    raw = str(text or "")
    digits = _amount_digit_signature(raw)
    if len(digits) > _AMOUNT_TRAILING_ZEROS_MIN_DIGITS and digits.endswith("00") and any(ch in raw for ch in ".,\uff0c\uff0e"):
        return digits[:-2]
    return digits


def _iter_percent_value_tokens(text: str) -> list[str]:
    """Return percent value substrings such as 40% without regular expressions."""
    raw = str(text or "")
    tokens: list[str] = []
    i = 0
    while i < len(raw):
        if not raw[i].isdigit():
            i += 1
            continue

        start = i
        while i < len(raw) and raw[i].isdigit():
            i += 1
        if i < len(raw) and raw[i] in ".\uff0e":
            decimal_start = i + 1
            decimal_end = decimal_start
            while decimal_end < len(raw) and raw[decimal_end].isdigit():
                decimal_end += 1
            if decimal_end > decimal_start:
                i = decimal_end

        if i < len(raw) and raw[i] in "%\uff05":
            tokens.append(raw[start : i + 1])
            i += 1
            continue

        i = max(start + 1, i)
    return tokens


def _visual_match_text_for_entity(entity_type: str, entity_text: str) -> str:
    """Choose the visible span to place a box on for a semantic entity.

    Amount percentages are often returned by HaS with surrounding business
    context ("contract amount 40%"). The sensitive value on the page is the
    percentage token itself, so use that shorter visible span when available.
    """
    if entity_type != "AMOUNT":
        return entity_text
    percent_tokens = _iter_percent_value_tokens(entity_text)
    if not percent_tokens:
        return entity_text
    for token in percent_tokens:
        if _compact_text(token) != _compact_text(entity_text):
            return token
    return entity_text


def _extend_amount_pair_for_visual_match(
    block_text: str,
    entity_text: str,
    start: int,
) -> tuple[str, int]:
    """Keep RMB uppercase/lowercase amount pairs together when HaS returns one side."""
    if start < 0 or not entity_text:
        return entity_text, start

    end = start + len(entity_text)
    if start > 0 and block_text[start - 1] in "，,":
        start -= 1
    if end < len(block_text) and block_text[end] in "，,":
        end += 1

    before_start = max(0, start - _AMOUNT_PAIR_LOOKBACK_CHARS)
    before = block_text[before_start:start]
    lower_pos = before.rfind("小写")
    upper_pos = before.rfind("人民币大写")
    if upper_pos < 0:
        upper_pos = before.rfind("大写")
    lower_tail_units = _char_visual_units(before[lower_pos:]) if lower_pos >= 0 else _AMOUNT_PAIR_NO_LOWER_MARKER_UNITS
    if upper_pos >= 0 and lower_pos >= 0 and upper_pos < lower_pos and lower_tail_units <= _AMOUNT_PAIR_MAX_LOWER_TAIL_UNITS:
        phrase_start = before_start + upper_pos
        phrase = block_text[phrase_start:end].strip()
        leading_trim = len(block_text[phrase_start:end]) - len(block_text[phrase_start:end].lstrip())
        return phrase, phrase_start + leading_trim

    return block_text[start:end], start


def _visual_match_span_for_entity(
    entity_type: str,
    block_text: str,
    entity_text: str,
    occurrence_start: int,
) -> tuple[str, int]:
    visual_text = _visual_match_text_for_entity(entity_type, entity_text)
    visual_start = occurrence_start
    if visual_text != entity_text:
        relative_visual_start = entity_text.find(visual_text)
        if relative_visual_start >= 0:
            visual_start = occurrence_start + relative_visual_start

    if entity_type == "AMOUNT":
        return _extend_amount_pair_for_visual_match(block_text, visual_text, visual_start)

    visual_text = _extend_entity_for_visual_match(
        entity_type,
        block_text,
        visual_text,
        visual_start,
    )
    return visual_text, visual_start
















def _is_amount_format_text(text: str) -> bool:
    """Format test: the text is one numeric value (digits plus optional
    thousands separators / decimal point / currency symbols).

    This is a literal-format judgement, like the standalone-date test: it says
    nothing about whether the number is sensitive. Semantics come from table
    structure (an amount-labelled column header).
    """
    compact = _compact_amount_candidate(text)
    if not compact or not any(ch.isdigit() for ch in compact):
        return False
    return all(ch in _AMOUNT_FORMAT_ALLOWED_CHARS for ch in compact)


def _is_standalone_amount_ocr_block(text: str) -> bool:
    """Return True when an OCR block is essentially one amount value."""
    compact = _compact_amount_candidate(text)
    if not _is_amount_format_text(compact):
        return False
    digits = _amount_digit_count(compact)
    if digits < _STANDALONE_AMOUNT_MIN_DIGITS or digits > _STANDALONE_AMOUNT_MAX_DIGITS:
        return False
    return bool(_amount_value_signature(compact))


def _is_amount_header_label(text: str) -> bool:
    """Identity test: the text IS an amount column-header label.

    A header label is a vocabulary term (AMOUNT_HEADER_LABELS) optionally
    followed by one parenthesized unit suffix — 单价（元）, 合价(元), 金额（万元）.
    Mixed full-/half-width parentheses (OCR artifacts) are accepted. Running
    text that merely contains a vocabulary word (合同金额：...) never matches.
    """
    compact = _compact_text(text)
    if compact and compact[-1] in _PAREN_CLOSE_CHARS:
        open_index = max(compact.rfind(open_char) for open_char in _PAREN_OPEN_CHARS)
        if open_index > 0:
            compact = compact[:open_index]
    return compact in AMOUNT_HEADER_LABELS


def _amount_header_column_spans(
    placements: list[tuple[str, int, int, int, int]],
) -> list[tuple[int, int, int]]:
    """(first_data_row, col_start, col_end) for every amount-label header cell."""
    return [
        (row + row_span, col, col + col_span)
        for text, row, col, row_span, col_span in placements
        if _is_amount_header_label(text)
    ]


def _is_amount_column_cell(
    row: int,
    col: int,
    col_span: int,
    header_spans: list[tuple[int, int, int]],
) -> bool:
    """The cell sits below an amount header and its HTML column span intersects it."""
    return any(
        row >= first_data_row and col < col_end and col + col_span > col_start
        for first_data_row, col_start, col_end in header_spans
    )


def _amount_values_from_table_placements(
    placements: list[tuple[str, int, int, int, int]],
) -> list[str]:
    """Amount-formatted data cells inside amount-labelled HTML columns."""
    header_spans = _amount_header_column_spans(placements)
    if not header_spans:
        return []
    return [
        text
        for text, row, col, _row_span, col_span in placements
        if _is_amount_format_text(text) and _is_amount_column_cell(row, col, col_span, header_spans)
    ]


def _amount_values_from_header_spans(blocks: list[OCRTextBlock]) -> list[str]:
    """Amount recall for flattened table layouts (per-cell boxes, no markup).

    PP-StructureV3 often returns a wired table as independent cell text boxes
    without `<table>` HTML. The header cell box itself then defines the column:
    a value belongs to the column when its horizontal center lies inside the
    header's own span and the cell sits below the header. Pure containment
    against the table's own boxes — no padding, tolerance or clustering.
    """
    headers = [block for block in blocks if _is_amount_header_label(block.text)]
    if not headers:
        return []
    values: list[str] = []
    for block in blocks:
        if not _is_amount_format_text(block.text):
            continue
        center_x = float(block.left) + float(block.width) / 2.0
        for header in headers:
            if (
                float(header.left) <= center_x <= float(header.left + header.width)
                and float(block.top) >= float(header.top + header.height)
            ):
                values.append(str(block.text))
                break
    return values


def recall_table_amount_entities(ocr_blocks: list[OCRTextBlock]) -> list[dict[str, str]]:
    """Structural AMOUNT recall from table semantics, independent of HaS NER.

    The 0.6B HaS model does not tag context-free bare numbers; in a table the
    amount semantics live in the column header. Recall uses only structure:
    - `<table>` HTML blocks: amount-labelled header -> same HTML column index
      span, rows below the header (_amount_values_from_table_placements).
    - expanded virtual cells: the same column logic, precomputed per cell in
      extract_table_cells from the real HTML indices.
    - flattened layouts: header-box span containment (_amount_values_from_header_spans).
    Regions come from match_entities_to_ocr (whole matched block + IoU dedupe).
    """
    values: list[str] = []
    flat_blocks: list[OCRTextBlock] = []
    for block in ocr_blocks:
        text = str(block.text or "")
        if text.lstrip().startswith("<table") and "</table>" in text:
            values.extend(_amount_values_from_table_placements(_parse_table_placements(text)))
        elif getattr(block, "_table_html_cell", False):
            if getattr(block, "_table_amount_cell", False):
                values.append(text)
        else:
            flat_blocks.append(block)
    values.extend(_amount_values_from_header_spans(flat_blocks))

    entities: list[dict[str, str]] = []
    seen_signatures: set[str] = set()
    for value in values:
        text = _compact_text(value)
        signature = _amount_value_signature(text)
        if not text or not signature or signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        entities.append({"type": "AMOUNT", "text": text, "source": "table_semantic"})
    return entities


def _merge_table_amount_entities(
    entities: list[dict[str, str]],
    table_amount_entities: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Append structural amount recalls not already covered by NER values."""
    if not table_amount_entities:
        return entities
    seen_signatures = {
        signature
        for entity in entities
        if _canonical_image_text_type(str(entity.get("type", ""))) == "AMOUNT"
        for signature in [_amount_value_signature(str(entity.get("text", "")))]
        if signature
    }
    merged = list(entities)
    for entity in table_amount_entities:
        signature = _amount_value_signature(entity["text"])
        if signature and signature in seen_signatures:
            continue
        if signature:
            seen_signatures.add(signature)
        merged.append(dict(entity))
    return merged


# Semantic vocabulary (data, not tuning): field labels whose value IS a
# document number. Derived from the DOCUMENT_NUMBER cn_terms in TYPE_REGISTRY,
# the single source of truth for type vocabulary.
DOCUMENT_NUMBER_FIELD_LABEL_TERMS: tuple[str, ...] = tuple(
    term for term, type_id in TYPE_CN_TO_ID.items() if type_id == "DOCUMENT_NUMBER"
)

# Full- and half-width colon accepted as the label/value separator in a form field.
_FIELD_LABEL_COLON_CHARS = "：:"


def _is_document_number_field_label(text: str) -> bool:
    """Identity test: the text IS a document-number field label.

    A field label is a label phrase ending with a vocabulary term —
    合同协议号, 运输工具名称及航次号 — optionally with a trailing colon
    (form separator), which is stripped first. Only the compact label
    phrase's own suffix is tested, mirroring _is_amount_header_label:
    values and running text never match.
    """
    compact = _compact_text(text)
    while compact and compact[-1] in _FIELD_LABEL_COLON_CHARS:
        compact = compact[:-1]
    if not compact:
        return False
    return any(compact.endswith(term) for term in DOCUMENT_NUMBER_FIELD_LABEL_TERMS)


def _split_field_label_value(text: str) -> tuple[str, str] | None:
    """Split a `标签：值` block at its first colon (full- or half-width)."""
    indices = [text.find(ch) for ch in _FIELD_LABEL_COLON_CHARS]
    indices = [index for index in indices if index >= 0]
    if not indices:
        return None
    index = min(indices)
    return text[:index], text[index + 1:]


def _is_document_number_format_text(text: str) -> bool:
    """Format test: a document number contains at least one digit.

    The form-field counterpart of _is_amount_format_text: when the field next
    to a document-number label is empty, the spatially nearest block is the
    next preprinted label (货物存放地点) — pure text with no digits — and must
    not be recalled as a value.
    """
    return any(ch.isdigit() for ch in _compact_text(text))


def recall_form_field_document_numbers(ocr_blocks: list[OCRTextBlock]) -> list[dict[str, str]]:
    """Structural DOCUMENT_NUMBER recall from form-field labels, independent of
    HaS NER — the form-field generalization of recall_table_amount_entities.

    Three label/value layouts, all identity/containment tests on existing
    geometry (no new tolerances):
    - one block `标签：值`: the part before the first colon is the field label.
    - label cell above its value (form grids such as customs declarations):
      the value's horizontal center lies inside the label cell's own span and
      the value is the nearest block below — the same construction as
      _amount_values_from_header_spans.
    - label block and value block on the same visual line: the nearest block to
      the right (existing _blocks_same_visual_line test).
    Only runs when DOCUMENT_NUMBER is selected (the caller gates on the schema).
    """
    prepared: list[tuple[OCRTextBlock, str]] = []
    for block in ocr_blocks:
        text = _block_search_text(block)
        if not _compact_text(text) or text.lstrip().startswith("<table"):
            continue
        prepared.append((block, text))

    values: list[str] = []

    for _block, text in prepared:
        split = _split_field_label_value(text)
        if split is None:
            continue
        label_part, value_part = split
        if (
            _is_document_number_field_label(label_part)
            and _compact_text(value_part)
            and _is_document_number_format_text(value_part)
        ):
            values.append(value_part.strip())

    label_blocks = [
        (block, text) for block, text in prepared if _is_document_number_field_label(text)
    ]
    for label, _label_text in label_blocks:
        candidates = [
            (block, text)
            for block, text in prepared
            if block is not label and not _is_document_number_field_label(text)
        ]
        below = [
            (block, text)
            for block, text in candidates
            if float(block.top) >= float(label.top + label.height)
            and float(label.left)
            <= float(block.left) + float(block.width) / 2.0
            <= float(label.left + label.width)
        ]
        if below:
            # The format test runs on the nearest block only: when the field is
            # empty, the nearest block is the next preprinted label and the
            # recall must yield nothing rather than leapfrog to farther text.
            _value_block, value_text = min(below, key=lambda item: float(item[0].top))
            if _is_document_number_format_text(value_text):
                values.append(value_text.strip())
            continue
        right = [
            (block, text)
            for block, text in candidates
            if block.left >= label.left + label.width and _blocks_same_visual_line(label, block)
        ]
        if right:
            _value_block, value_text = min(right, key=lambda item: int(item[0].left))
            if _is_document_number_format_text(value_text):
                values.append(value_text.strip())

    entities: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        compact = _compact_text(value)
        if not compact or compact in seen:
            continue
        seen.add(compact)
        entities.append({"type": "DOCUMENT_NUMBER", "text": value, "source": "form_field_ocr"})
    return entities


def _merge_form_field_document_entities(
    entities: list[dict[str, str]],
    recalled: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Append form-field document numbers HaS did not already return."""
    if not recalled:
        return entities
    seen = {
        _compact_text(str(entity.get("text", "")))
        for entity in entities
        if _canonical_image_text_type(str(entity.get("type", ""))) == "DOCUMENT_NUMBER"
    }
    merged = list(entities)
    for entity in recalled:
        compact = _compact_text(entity["text"])
        if compact and compact not in seen:
            seen.add(compact)
            merged.append(dict(entity))
    return merged












def _blocks_same_visual_line(left: OCRTextBlock, right: OCRTextBlock) -> bool:
    left_top = float(left.top)
    right_top = float(right.top)
    left_bottom = left_top + max(1.0, float(left.height))
    right_bottom = right_top + max(1.0, float(right.height))
    overlap = min(left_bottom, right_bottom) - max(left_top, right_top)
    if overlap > 0 and overlap / max(1.0, min(float(left.height), float(right.height))) >= _SAME_LINE_VERTICAL_OVERLAP_RATIO:
        return True
    left_center = left_top + float(left.height) / 2
    right_center = right_top + float(right.height) / 2
    return abs(left_center - right_center) <= max(float(left.height), float(right.height)) * _SAME_LINE_CENTER_HEIGHT_RATIO


def _should_join_visual_line_blocks(left: OCRTextBlock, right: OCRTextBlock) -> bool:
    if not _blocks_same_visual_line(left, right):
        return False
    gap = int(right.left) - int(left.left + left.width)
    if gap < 0:
        return False
    typical_height = max(1, int(max(left.height, right.height)))
    return gap <= max(_VISUAL_LINE_JOIN_GAP_MIN_PX, int(typical_height * _VISUAL_LINE_JOIN_GAP_HEIGHT_MULT))


def _is_plain_cjk_or_alnum(text: str) -> bool:
    compact = _compact_text(text)
    return bool(compact) and all(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in compact)


def _cjk_count(text: str) -> int:
    return sum(1 for ch in _compact_text(text) if "\u4e00" <= ch <= "\u9fff")


def _should_bridge_short_cjk_prefix(left: OCRTextBlock, right: OCRTextBlock) -> bool:
    left_text = _compact_text(left.text)
    right_text = _compact_text(right.text)
    if not (_BRIDGE_LEFT_MIN_LEN <= len(left_text) <= _BRIDGE_LEFT_MAX_LEN and _BRIDGE_RIGHT_MIN_LEN <= len(right_text) <= _BRIDGE_RIGHT_MAX_LEN):
        return False
    if len(left_text + right_text) > _BRIDGE_COMBINED_MAX_LEN:
        return False
    if not (_is_plain_cjk_or_alnum(left_text) and _is_plain_cjk_or_alnum(right_text)):
        return False
    if any(ch.isdigit() for ch in left_text):
        return False
    return _cjk_count(left_text) >= _BRIDGE_LEFT_MIN_CJK and _cjk_count(right_text) >= _BRIDGE_RIGHT_MIN_CJK


def _join_visual_line_text(left: str, right: str) -> str:
    if _is_plain_cjk_or_alnum(left) and _is_plain_cjk_or_alnum(right):
        return f"{_compact_text(left)}{_compact_text(right)}"
    return f"{str(left).strip()} {str(right).strip()}".strip()


def _union_ocr_blocks(blocks: list[OCRTextBlock], text: str) -> OCRTextBlock:
    left = min(int(block.left) for block in blocks)
    top = min(int(block.top) for block in blocks)
    right = max(int(block.left + block.width) for block in blocks)
    bottom = max(int(block.top + block.height) for block in blocks)
    return OCRTextBlock(
        text=text,
        polygon=[
            [left, top],
            [right, top],
            [right, bottom],
            [left, bottom],
        ],
        confidence=min(float(block.confidence) for block in blocks) * _UNION_BLOCK_CONFIDENCE_FACTOR,
    )


def reconstruct_visual_line_blocks(ocr_blocks: list[OCRTextBlock]) -> list[OCRTextBlock]:
    """Create entity-agnostic virtual lines from adjacent OCR blocks."""
    typical_height = _infer_typical_textline_height(ocr_blocks) or 0
    text_blocks = [
        block
        for block in ocr_blocks
        if _compact_text(block.text)
        and not str(block.text or "").lstrip().startswith("<table")
        and not (
            typical_height
            and block.height > typical_height * _RECONSTRUCT_TALL_HEIGHT_MULT
            and block.width < block.height * _RECONSTRUCT_TALL_ASPECT_MULT
        )
    ]
    if len(text_blocks) < 2:
        return []

    virtual_blocks: list[OCRTextBlock] = []
    seen: set[str] = set()
    ordered_blocks = sorted(text_blocks, key=lambda item: (item.left, item.top))
    for left in ordered_blocks:
        right_candidates = [
            right
            for right in ordered_blocks
            if right.left > left.left
            and _should_join_visual_line_blocks(left, right)
            and _should_bridge_short_cjk_prefix(left, right)
        ]
        if not right_candidates:
            continue
        right = min(right_candidates, key=lambda item: item.left - (left.left + left.width))
        text = _join_visual_line_text(str(left.text or ""), str(right.text or ""))
        compact = _compact_text(text)
        if compact and compact not in seen:
            seen.add(compact)
            virtual_blocks.append(_union_ocr_blocks([left, right], text))

    return virtual_blocks


def _add_has_text_duration(
    stage_status: dict[str, Any] | None,
    key: str,
    elapsed_ms: int,
) -> None:
    if stage_status is None:
        return
    stage_status[key] = int(stage_status.get(key, 0) or 0) + max(0, int(elapsed_ms))


def _ocr_cache_enabled() -> bool:
    return settings.OCR_TEXT_BLOCK_CACHE_TTL_SEC > 0 and settings.OCR_TEXT_BLOCK_CACHE_MAX_ITEMS > 0


def _ocr_service_cache_identity(ocr_service: Any) -> tuple[str, str, int]:
    base_url = str(getattr(ocr_service, "base_url", "") or "")
    service_name = f"{type(ocr_service).__module__}.{type(ocr_service).__qualname__}"
    return base_url, service_name, id(ocr_service)


def _image_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _ocr_cache_key(
    stage: str,
    image: Image.Image,
    image_bytes: bytes,
    ocr_service: Any,
) -> tuple[Any, ...]:
    config_bits: tuple[Any, ...]
    if stage == "vl":
        config_bits = (int(settings.OCR_MAX_NEW_TOKENS),)
    else:
        config_bits = ()
    return (
        stage,
        hashlib.sha256(image_bytes).hexdigest(),
        image.width,
        image.height,
        image.mode,
        _ocr_service_cache_identity(ocr_service),
        config_bits,
    )


def _get_cached_ocr_output(
    key: tuple[Any, ...],
    stage: str,
    stage_status: dict[str, Any] | None,
) -> tuple[list[OCRTextBlock], list[SensitiveRegion]] | None:
    if not _ocr_cache_enabled():
        _record_ocr_cache_stage(stage_status, stage, "disabled")
        return None

    now = time.monotonic()
    ttl = float(settings.OCR_TEXT_BLOCK_CACHE_TTL_SEC)
    with _OCR_TEXT_BLOCK_CACHE_LOCK:
        cached = _OCR_TEXT_BLOCK_CACHE.get(key)
        if cached is None:
            _record_ocr_cache_stage(stage_status, stage, "miss")
            return None
        stored_at, blocks, visual_regions = cached
        if now - stored_at > ttl:
            _OCR_TEXT_BLOCK_CACHE.pop(key, None)
            _record_ocr_cache_stage(stage_status, stage, "miss")
            return None
        _OCR_TEXT_BLOCK_CACHE.move_to_end(key)
        _record_ocr_cache_stage(stage_status, stage, "hit")
        return _clone_ocr_output(blocks, visual_regions)


def _set_cached_ocr_output(
    key: tuple[Any, ...],
    blocks: list[OCRTextBlock],
    visual_regions: list[SensitiveRegion],
) -> None:
    if not _ocr_cache_enabled():
        return

    max_items = int(settings.OCR_TEXT_BLOCK_CACHE_MAX_ITEMS)
    with _OCR_TEXT_BLOCK_CACHE_LOCK:
        cached_blocks, cached_regions = _clone_ocr_output(blocks, visual_regions)
        _OCR_TEXT_BLOCK_CACHE[key] = (time.monotonic(), cached_blocks, cached_regions)
        _OCR_TEXT_BLOCK_CACHE.move_to_end(key)
        while len(_OCR_TEXT_BLOCK_CACHE) > max_items:
            _OCR_TEXT_BLOCK_CACHE.popitem(last=False)


def _begin_ocr_output_inflight(
    key: tuple[Any, ...],
) -> tuple[bool, _OcrOutputInflight]:
    with _OCR_TEXT_BLOCK_INFLIGHT_LOCK:
        inflight = _OCR_TEXT_BLOCK_INFLIGHT.get(key)
        if inflight is not None:
            return False, inflight
        inflight = _OcrOutputInflight()
        _OCR_TEXT_BLOCK_INFLIGHT[key] = inflight
        return True, inflight


def _finish_ocr_output_inflight(
    key: tuple[Any, ...],
    inflight: _OcrOutputInflight,
    result: tuple[list[OCRTextBlock], list[SensitiveRegion]] | None,
    error: BaseException | None = None,
) -> None:
    with _OCR_TEXT_BLOCK_INFLIGHT_LOCK:
        if _OCR_TEXT_BLOCK_INFLIGHT.get(key) is inflight:
            _OCR_TEXT_BLOCK_INFLIGHT.pop(key, None)
    if result is not None:
        inflight.result = _clone_ocr_output(*result)
    inflight.error = error
    inflight.event.set()


def _wait_for_ocr_output_inflight(
    inflight: _OcrOutputInflight,
) -> tuple[list[OCRTextBlock], list[SensitiveRegion]]:
    # 兜底超时：owner 正常路径总会 set event；若 owner 异常退出未触发 finish，
    # 避免同图请求永久挂死。超时按 inflight 失败处理。
    timeout = float(settings.OCR_TIMEOUT) + 30.0
    if not inflight.event.wait(timeout):
        raise TimeoutError(
            f"等待同图 OCR in-flight 结果超时（{timeout:.0f}s），按失败处理"
        )
    if inflight.error is not None:
        raise inflight.error
    if inflight.result is None:
        return [], []
    return _clone_ocr_output(*inflight.result)


# ---------------------------------------------------------------------------
# Image preparation
# ---------------------------------------------------------------------------

def prepare_image(image_bytes: bytes) -> tuple[Image.Image, int, int]:
    """Decode image bytes, apply EXIF orientation, convert to RGB."""
    image = Image.open(io.BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image, image.width, image.height


def _is_effectively_blank_page(image: Image.Image) -> tuple[bool, float, float]:
    """Return whether a page is blank enough to skip expensive OCR inference."""
    if image.width < _BLANK_PAGE_MIN_WIDTH_PX or image.height < _BLANK_PAGE_MIN_HEIGHT_PX:
        return False, 1.0, 1.0

    sample = image.convert("RGB")
    sample.thumbnail((_BLANK_PAGE_THUMBNAIL_PX, _BLANK_PAGE_THUMBNAIL_PX))
    gray = sample.convert("L")
    histogram = gray.histogram()
    total = sum(histogram)
    if total == 0:
        return True, 0.0, 0.0

    dark_pixels = sum(histogram[:_BLANK_PAGE_DARK_PIXEL_MAX])
    ink_pixels = sum(histogram[:_BLANK_PAGE_INK_PIXEL_MAX])
    dark_ratio = dark_pixels / total
    ink_ratio = ink_pixels / total

    # Keep this threshold deliberately low: it only skips pages with essentially
    # no visible ink, while preserving faint scans, small seals, and single-line
    # pages for the semantic OCR path.
    return dark_ratio <= _BLANK_PAGE_DARK_RATIO_MAX and ink_ratio <= _BLANK_PAGE_INK_RATIO_MAX, dark_ratio, ink_ratio


# ---------------------------------------------------------------------------
# PaddleOCR extraction
# ---------------------------------------------------------------------------

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

    # 惰性计算：structure-primary 提前 return 的路径无需扫描整页像素。
    table_like_cache: bool | None = None

    def table_like() -> bool:
        nonlocal table_like_cache
        if table_like_cache is None:
            table_like_cache = _looks_like_table(image) if adaptive_mode else False
        return table_like_cache
    needs_table_precision = bool(selected & TABLE_PRECISION_ENTITY_TYPES)
    needs_ocr_visual_regions = bool(selected & OCR_VISUAL_ENTITY_TYPES)
    needs_text_precision = adaptive_mode and bool(selected - OCR_VISUAL_ENTITY_TYPES)

    vl_disabled = not bool(getattr(settings, "OCR_VL_ENABLED", True))
    use_structure_primary = settings.OCR_STRUCTURE_ENABLED and (
        vl_disabled
        or (
            settings.OCR_STRUCTURE_PRIMARY
            and (not require_visual_regions or needs_ocr_visual_regions)
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
                        "Using PP-StructureV3 primary OCR path: %d blocks (min=%d, table_like=%s, table_types=%s)",
                        len(primary_structure_blocks),
                        min_blocks,
                        table_like(),
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
            _should_run_structure_fallback(image, blocks)
            or _has_coarse_markup_blocks(blocks)
            or (adaptive_mode and needs_table_precision and table_like())
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


def _looks_like_table(image: Image.Image) -> bool:
    gray = image.convert("L")
    # Downsample for a cheap table-line heuristic.
    gray.thumbnail((_TABLE_HEURISTIC_THUMBNAIL_PX, _TABLE_HEURISTIC_THUMBNAIL_PX))
    width, height = gray.size
    if width < _TABLE_HEURISTIC_MIN_DIM_PX or height < _TABLE_HEURISTIC_MIN_DIM_PX:
        return False
    dark = np.asarray(gray) < _TABLE_HEURISTIC_DARK_PIXEL_MAX
    horizontal = int(np.count_nonzero(dark.sum(axis=1) / width > _TABLE_HEURISTIC_HORIZONTAL_DARK_RATIO))
    vertical = int(np.count_nonzero(dark.sum(axis=0) / height > _TABLE_HEURISTIC_VERTICAL_DARK_RATIO))
    return horizontal >= _TABLE_HEURISTIC_MIN_LINES and vertical >= _TABLE_HEURISTIC_MIN_LINES


def _should_run_structure_fallback(image: Image.Image, blocks: list[OCRTextBlock]) -> bool:
    sparse = len(blocks) < max(1, int(settings.OCR_STRUCTURE_MIN_VL_BOXES))
    if not sparse:
        return False
    if any(block.text.lstrip().lower().startswith(("<table", "<html", "<div")) for block in blocks):
        return True
    return _looks_like_table(image)


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


def _is_coarse_markup_block(block: OCRTextBlock) -> bool:
    return block.text.lstrip().lower().startswith(("<table", "<html", "<div"))


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
            visual_regions.extend(_split_merged_seal_region(image, region))
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


def _merge_ocr_blocks(
    primary: list[OCRTextBlock],
    extra: list[OCRTextBlock],
    *,
    prefer_extra_text: bool = False,
) -> list[OCRTextBlock]:
    """Merge extra blocks into primary; primary wins on overlap.

    prefer_extra_text: the extra engine reads glyphs more accurately than the
    primary one (PaddleOCR-VL vs the PP-OCR line recognizer). When an extra
    block re-reads an existing line — same place with equal glyph count, or a
    fuller reading of the same pixels — its text is carried onto the existing
    block while the existing geometry and char boxes (value-crop evidence) are
    kept, and the box widens to the union so the mask never claims pixels it
    does not cover.
    """
    if extra:
        merged = [
            block for block in primary
            if not _is_coarse_markup_block(block)
        ]
    else:
        merged = list(primary)

    def iou(a: OCRTextBlock, b: OCRTextBlock) -> float:
        ax1, ay1, ax2, ay2 = a.bbox
        bx1, by1, bx2, by2 = b.bbox
        x1, y1 = max(ax1, bx1), max(ay1, by1)
        x2, y2 = min(ax2, bx2), min(ay2, by2)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        inter = (x2 - x1) * (y2 - y1)
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        return inter / (area_a + area_b - inter)

    def looks_like_short_field(block: OCRTextBlock) -> bool:
        text = str(block.text or "").strip()
        compact = _compact_text(text)
        if len(compact) < _SHORT_FIELD_MIN_COMPACT_LEN or len(compact) > _SHORT_FIELD_MAX_COMPACT_LEN:
            return False
        if not any(separator in text for separator in (":", "：")):
            return False
        if text.count(":") + text.count("：") > _SHORT_FIELD_MAX_DELIMITERS:
            return False
        return block.width > 0 and block.height > 0

    def is_structure_precision_supplement(existing: OCRTextBlock, candidate: OCRTextBlock) -> bool:
        if not looks_like_short_field(candidate):
            return False
        existing_text = _compact_text(existing.text)
        candidate_text = _compact_text(candidate.text)
        if not existing_text or not candidate_text or existing_text == candidate_text:
            return False
        if candidate.width > existing.width * _SUPPLEMENT_WIDTH_RATIO or candidate.height > existing.height * _SUPPLEMENT_HEIGHT_RATIO:
            return False
        similar = SequenceMatcher(None, candidate_text, existing_text).ratio()
        if candidate_text not in existing_text and existing_text not in candidate_text and similar < _SUPPLEMENT_SIMILARITY_MIN:
            return False
        return existing.width > candidate.width * _SUPPLEMENT_WIDER_RATIO or len(existing_text) > len(candidate_text) + _SUPPLEMENT_LONGER_TEXT_MARGIN

    def content_relation(candidate_compact: str, existing_compact: str) -> str | None:
        """How the candidate's content relates to the existing block's.

        Identity facts only, no similarity thresholds: 'same' for equal glyph
        counts (two recognizers reading the same glyphs differently, e.g.
        戬浜/我浜); 'subset'/'superset' when the shorter text is an in-order
        subsequence of the longer (one engine dropped or recovered glyphs);
        None when the readings are unrelated content.
        """
        if not candidate_compact or not existing_compact:
            return None
        if len(candidate_compact) == len(existing_compact):
            return "same"
        shorter, longer = sorted((candidate_compact, existing_compact), key=len)
        corresponding = sum(
            size
            for _shorter_pos, _longer_pos, size in SequenceMatcher(
                None, shorter, longer, autojunk=False
            ).get_matching_blocks()
        )
        if corresponding != len(shorter):
            return None
        return "subset" if shorter is candidate_compact else "superset"

    def adopted_block(existing: OCRTextBlock, candidate: OCRTextBlock) -> OCRTextBlock:
        left = min(existing.bbox[0], candidate.bbox[0])
        top = min(existing.bbox[1], candidate.bbox[1])
        right = max(existing.bbox[2], candidate.bbox[2])
        bottom = max(existing.bbox[3], candidate.bbox[3])
        return OCRTextBlock(
            text=candidate.text,
            polygon=[[left, top], [right, top], [right, bottom], [left, bottom]],
            confidence=existing.confidence,
            chars=existing.chars,
        )

    for block in extra:
        if _is_coarse_markup_block(block):
            continue
        compact = _compact_text(block.text)
        duplicate = False
        for index, existing in enumerate(merged):
            overlap = iou(block, existing)
            if overlap > _MERGE_DUPLICATE_IOU:
                relation = content_relation(compact, _compact_text(existing.text))
                if prefer_extra_text and relation in ("same", "superset"):
                    merged[index] = adopted_block(existing, block)
                    duplicate = True
                    break
                if relation in ("same", "subset"):
                    duplicate = True
                    break
            if overlap > _MERGE_OVERLAP_IOU:
                if is_structure_precision_supplement(existing, block):
                    continue
                duplicate = True
                break
        if not duplicate:
            merged.append(block)
    return merged


def _split_merged_seal_region(image: Image.Image, region: SensitiveRegion) -> list[SensitiveRegion]:
    """Split a model-returned seal box when it visibly contains stacked seals.

    PaddleOCR-VL sometimes returns one tall region around two adjacent red
    stamps. Redacting the combined box works, but it hides too much nearby text
    and makes manual review awkward. This post-process is intentionally generic:
    it only runs for unusually tall seal boxes and separates them by red-pixel
    row projections inside the box.
    """
    if region.entity_type != "SEAL":
        return [region]
    if region.width < _SEAL_SPLIT_MIN_DIM_PX or region.height < _SEAL_SPLIT_MIN_DIM_PX:
        return [region]
    if region.height < region.width * _SEAL_SPLIT_MIN_ASPECT:
        return [region]

    img_w, img_h = image.size
    if region.width < max(_SEAL_SPLIT_MIN_WIDTH_PX, int(img_w * _SEAL_SPLIT_MIN_WIDTH_IMG_RATIO)):
        return [region]
    x1 = max(0, min(region.left, img_w - 1))
    y1 = max(0, min(region.top, img_h - 1))
    x2 = max(x1 + 1, min(region.left + region.width, img_w))
    y2 = max(y1 + 1, min(region.top + region.height, img_h))
    crop = image.crop((x1, y1, x2, y2)).convert("RGB")
    width, height = crop.size
    arr = np.asarray(crop, dtype=np.int32)
    red = arr[:, :, 0]
    green = arr[:, :, 1]
    blue = arr[:, :, 2]
    channel_cap = np.maximum(
        _RED_STAMP_OTHER_CHANNEL_FLOOR,
        (red * _RED_STAMP_OTHER_CHANNEL_RATIO).astype(np.int32),
    )
    red_mask = (
        (red >= _RED_STAMP_MIN_RED)
        & (red - green >= _RED_STAMP_RED_MINUS_GREEN)
        & (red - blue >= _RED_STAMP_RED_MINUS_BLUE)
        & (green <= channel_cap)
        & (blue <= channel_cap)
    )
    red_rows: list[int] = [int(v) for v in red_mask.sum(axis=1)]

    # Smooth the projection so sparse red text and broken rings are treated as
    # one seal band while preserving larger vertical gaps between stamps.
    radius = max(_SEAL_SMOOTH_RADIUS_MIN, min(_SEAL_SMOOTH_RADIUS_MAX, height // _SEAL_SMOOTH_RADIUS_HEIGHT_DIVISOR))
    smoothed = [
        sum(red_rows[max(0, y - radius): min(height, y + radius + 1)])
        for y in range(height)
    ]
    active_threshold = max(_SEAL_ACTIVE_THRESHOLD_MIN, int(width * _SEAL_ACTIVE_THRESHOLD_WIDTH_RATIO))
    close_gap = max(_SEAL_CLOSE_GAP_MIN, min(_SEAL_CLOSE_GAP_MAX, height // _SEAL_CLOSE_GAP_HEIGHT_DIVISOR))
    min_band_height = max(_SEAL_MIN_BAND_HEIGHT_MIN, min(_SEAL_MIN_BAND_HEIGHT_MAX, int(region.width * _SEAL_MIN_BAND_HEIGHT_WIDTH_RATIO)))

    bands: list[tuple[int, int]] = []
    in_band = False
    start = 0
    gap = 0
    for y, count in enumerate(smoothed):
        if count >= active_threshold:
            if not in_band:
                start = y
                in_band = True
            gap = 0
        elif in_band:
            gap += 1
            if gap >= close_gap:
                end = y - gap + 1
                if end - start >= min_band_height:
                    bands.append((start, end))
                in_band = False
                gap = 0
    if in_band and height - start >= min_band_height:
        bands.append((start, height - 1))

    if len(bands) < 2:
        max_projection = max(smoothed) if smoothed else 0
        peak_candidates: list[tuple[float, int]] = []
        if max_projection > 0:
            for y in range(1, height - 1):
                if (
                    smoothed[y] >= smoothed[y - 1]
                    and smoothed[y] >= smoothed[y + 1]
                    and smoothed[y] >= max_projection * _SEAL_PEAK_PROMINENCE_RATIO
                ):
                    peak_candidates.append((float(smoothed[y]), y))
        peaks: list[int] = []
        min_peak_distance = max(_SEAL_PEAK_MIN_DISTANCE_MIN, int(width * _SEAL_PEAK_MIN_DISTANCE_WIDTH_RATIO))
        for _score, y in sorted(peak_candidates, reverse=True):
            if all(abs(y - existing) >= min_peak_distance for existing in peaks):
                peaks.append(y)
            if len(peaks) >= _SEAL_MAX_PEAKS:
                break
        peaks.sort()
        if len(peaks) >= 2:
            half_band = max(_SEAL_HALF_BAND_MIN, int(width * _SEAL_HALF_BAND_WIDTH_RATIO))
            bands = [
                (max(0, peak - half_band), min(height - 1, peak + half_band))
                for peak in peaks
            ]

    if len(bands) < 2:
        return [region]

    split_regions: list[SensitiveRegion] = []
    for band_start, band_end in bands:
        y_start = max(0, band_start - radius)
        y_end = min(height - 1, band_end + radius)
        band_ys, band_xs = np.nonzero(red_mask[y_start : y_end + 1, :])
        if band_xs.size == 0:
            continue
        bx1, bx2 = int(band_xs.min()), int(band_xs.max())
        by1, by2 = int(band_ys.min()) + y_start, int(band_ys.max()) + y_start
        box_w = bx2 - bx1 + 1
        box_h = by2 - by1 + 1
        if box_w < max(_SEAL_BAND_BOX_MIN_PX, region.width * _SEAL_BAND_BOX_MIN_WIDTH_RATIO) or box_h < max(_SEAL_BAND_BOX_MIN_PX, region.width * _SEAL_BAND_BOX_MIN_WIDTH_RATIO):
            continue
        pad = max(_SEAL_BAND_PAD_MIN, int(max(box_w, box_h) * _SEAL_BAND_PAD_RATIO))
        left = max(0, x1 + bx1 - pad)
        top = max(0, y1 + by1 - pad)
        right = min(img_w, x1 + bx2 + pad + 1)
        bottom = min(img_h, y1 + by2 + pad + 1)
        split_regions.append(SensitiveRegion(
            text=region.text,
            entity_type=region.entity_type,
            left=left,
            top=top,
            width=max(1, right - left),
            height=max(1, bottom - top),
            confidence=region.confidence,
            source=region.source,
            color=region.color,
        ))

    return split_regions if len(split_regions) >= 2 else [region]


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
                split_regions = _split_merged_seal_region(image, region)
                visual_regions.extend(split_regions)
                logger.info(
                    "Found SEAL @ (%d, %d, %d, %d), split=%d",
                    left,
                    top,
                    right - left,
                    bottom - top,
                    len(split_regions),
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


# ---------------------------------------------------------------------------
# HTML table expansion
# ---------------------------------------------------------------------------

def _parse_table_placements(table_html: str) -> list[tuple[str, int, int, int, int]]:
    """
    Parse an HTML table into cell placements with explicit row/column indices.

    Returns (cell_text, row, col, row_span, col_span) per cell, with colspan /
    rowspan occupancy resolved so the column index is the true HTML grid column.
    """
    rows: list[list[tuple[str, int, int]]] = []

    class TableCellParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_cell = False
            self.current_cell = ""
            self.current_row: list[tuple[str, int, int]] = []
            self.current_colspan = 1
            self.current_rowspan = 1

        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self.current_row = []
            if tag in ("td", "th"):
                self.in_cell = True
                self.current_cell = ""
                self.current_colspan = 1
                self.current_rowspan = 1
                for k, v in attrs:
                    if k == "colspan":
                        try:
                            self.current_colspan = max(1, int(v))
                        except Exception:
                            self.current_colspan = 1
                    elif k == "rowspan":
                        try:
                            self.current_rowspan = max(1, int(v))
                        except Exception:
                            self.current_rowspan = 1

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.in_cell:
                self.in_cell = False
                cell_text = html.unescape(self.current_cell).strip()
                self.current_row.append((cell_text, self.current_colspan, self.current_rowspan))
            if tag == "tr":
                if self.current_row:
                    rows.append(self.current_row)
                self.current_row = []

        def handle_data(self, data):
            if self.in_cell:
                self.current_cell += data

    try:
        parser = TableCellParser()
        parser.feed(table_html)
        if getattr(parser, "current_row", None):
            rows.append(parser.current_row)
    except Exception as e:
        logger.warning("Failed to parse table HTML: %s", e)
        return []

    if not rows:
        return []

    placements: list[tuple[str, int, int, int, int]] = []
    occupied: set[tuple[int, int]] = set()
    for r_idx, row in enumerate(rows):
        col_idx = 0
        for cell_text, colspan, rowspan in row:
            while (r_idx, col_idx) in occupied:
                col_idx += 1
            col_span = max(1, colspan)
            row_span = max(1, rowspan)
            placements.append((cell_text, r_idx, col_idx, row_span, col_span))
            for rr in range(r_idx, r_idx + row_span):
                for cc in range(col_idx, col_idx + col_span):
                    occupied.add((rr, cc))
            col_idx += col_span

    return placements


def extract_table_cells(table_html: str, block: OCRTextBlock) -> list[OCRTextBlock]:
    """
    Parse an HTML table and create virtual OCRTextBlock per cell.

    Cell positions are estimated from row/column indices and the parent block's
    bounding box. Cells inside an amount-labelled column (header semantics +
    HTML column index) are tagged for the structural AMOUNT recall.
    """
    placements = _parse_table_placements(table_html)
    if not placements:
        return []

    num_rows = max(row + row_span for _, row, _, row_span, _ in placements)
    num_cols = max(col + col_span for _, _, col, _, col_span in placements)
    if num_rows == 0 or num_cols == 0:
        return []

    amount_header_spans = _amount_header_column_spans(placements)

    row_height = max(block.height / num_rows, 1.0)
    col_width = max(block.width / num_cols, 1.0)

    virtual_blocks: list[OCRTextBlock] = []
    for cell_text, r_idx, col_idx, row_span, col_span in placements:
        if cell_text.strip():
            cell_left = block.left + col_idx * col_width
            cell_top = block.top + r_idx * row_height
            cell_width = col_width * col_span
            cell_height = row_height * row_span

            cell_block = OCRTextBlock(
                text=cell_text,
                polygon=[
                    [cell_left, cell_top],
                    [cell_left + cell_width, cell_top],
                    [cell_left + cell_width, cell_top + cell_height],
                    [cell_left, cell_top + cell_height],
                ],
                confidence=block.confidence * _TABLE_CELL_CONFIDENCE_FACTOR,
            )
            cell_block._table_html_cell = True
            cell_block._table_amount_cell = bool(amount_header_spans) and _is_amount_format_text(
                cell_text
            ) and _is_amount_column_cell(r_idx, col_idx, col_span, amount_header_spans)
            virtual_blocks.append(cell_block)

    return virtual_blocks


def _html_to_plain_text(markup: str) -> str:
    parts: list[str] = []

    class PlainTextParser(HTMLParser):
        def handle_data(self, data):
            if data:
                parts.append(data)

    parser = PlainTextParser()
    parser.feed(markup)
    return " ".join(html.unescape(part).strip() for part in parts if part.strip()).strip()


def expand_table_blocks(ocr_blocks: list[OCRTextBlock]) -> list[OCRTextBlock]:
    """Expand HTML table blocks into per-cell blocks for cleaner NER input."""
    expanded: list[OCRTextBlock] = []
    for block in ocr_blocks:
        if block.text.startswith("<table") and "</table>" in block.text:
            cell_blocks = extract_table_cells(block.text, block)
            if cell_blocks:
                expanded.extend(cell_blocks)
                continue
            # parse failed - strip HTML tags as fallback
            plain = _html_to_plain_text(block.text)
            if plain:
                expanded.append(OCRTextBlock(
                    text=plain,
                    polygon=block.polygon,
                    confidence=block.confidence,
                ))
            else:
                expanded.append(block)
        else:
            expanded.append(block)
    return expanded


# ---------------------------------------------------------------------------
# HaS NER text analysis
# ---------------------------------------------------------------------------

# NER runs on the whole document, not per-line chunks: feeding the 0.6B model a
# context-free single cell (a lone "汉族") makes it force-fit that value into the
# nearest requested type when its true type isn't in the schema (民族 absent ->
# "汉族" lands under 性别). With the full page it has the context to assign 男->性别
# and leave 汉族 out — 找到就找到，找不到就没有。Tradeoff: the model dilutes recall on a
# long page and may drop an entity near the very end (e.g. a standalone signature
# date). Reordering/chunking to recover it reintroduces the force-fit, because this
# model classifies sequentially — order and recall are coupled. So a date-format
# backstop (below) catches those dropped dates — see _STANDALONE_DATE_RE.

async def run_has_text_analysis(
    ocr_blocks: list[OCRTextBlock],
    has_client: Any,
    vision_types: list | None = None,
    stage_status: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """
    Analyse OCR text with HaS local NER model to identify sensitive entities.
    Fully offline - no cloud API dependency.

    Args:
        ocr_blocks: OCR text blocks.
        has_client: HaSClient instance (may be None).
        vision_types: User-enabled vision type configs.

    Returns:
        [{type: "PERSON", text: "张三"}, ...]
    """
    total_start = time.perf_counter()
    _record_has_text_metric(stage_status, "has_text_cache_status", "not_started")
    _record_has_text_metric(stage_status, "has_text_slot_wait_ms", 0)
    _record_has_text_metric(stage_status, "has_text_duplicate_wait_ms", 0)
    _record_has_text_metric(stage_status, "has_text_model_ms", 0)

    if not ocr_blocks:
        _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_empty_ocr")
        _record_has_text_metric(
            stage_status,
            "has_text_total_ms",
            round((time.perf_counter() - total_start) * 1000),
        )
        return []

    # Structural AMOUNT recall from table semantics. Computed before any HaS
    # availability checks: it needs no model, and table amounts must surface
    # even when NER is skipped, fails, or returns nothing.
    amount_in_schema = vision_types is None or any(
        _canonical_image_text_type(getattr(vt, "id", "")) == "AMOUNT" for vt in vision_types
    )
    table_amount_entities = recall_table_amount_entities(ocr_blocks) if amount_in_schema else []
    if table_amount_entities:
        logger.info(
            "Table semantic AMOUNT recall: %s",
            [entity["text"] for entity in table_amount_entities],
        )
    _record_has_text_metric(
        stage_status, "has_text_table_amount_entities", len(table_amount_entities)
    )

    # Structural DOCUMENT_NUMBER recall from form-field labels (标签：值 and
    # label-cell layouts). Same contract as the table AMOUNT recall: computed
    # before any HaS availability checks and surfaced even when NER is skipped
    # or fails. Only active when DOCUMENT_NUMBER is selected in the schema.
    document_number_in_schema = vision_types is not None and any(
        _canonical_image_text_type(getattr(vt, "id", "")) == "DOCUMENT_NUMBER" for vt in vision_types
    )
    form_document_entities = (
        recall_form_field_document_numbers(ocr_blocks) if document_number_in_schema else []
    )
    if form_document_entities:
        logger.info(
            "Form-field DOCUMENT_NUMBER recall: %s",
            [entity["text"] for entity in form_document_entities],
        )
    _record_has_text_metric(
        stage_status, "has_text_form_document_entities", len(form_document_entities)
    )
    structural_entities = [*table_amount_entities, *form_document_entities]

    # Lazy re-init if client was not available at startup
    if not has_client:
        try:
            from app.services.has_client import HaSClient
            has_client = HaSClient()
        except Exception as e:
            logger.error("HaS Client init failed: %s", e)
            _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_no_client")
            _record_has_text_metric(
                stage_status,
                "has_text_total_ms",
                round((time.perf_counter() - total_start) * 1000),
            )
            return list(structural_entities)

    if _has_recent_negative_health(has_client):
        logger.warning("HaS service recently reported unavailable, skipping NER")
        _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_recent_unavailable")
        _record_has_text_metric(
            stage_status,
            "has_text_total_ms",
            round((time.perf_counter() - total_start) * 1000),
        )
        return list(structural_entities)

    try:
        prepare_start = time.perf_counter()
        selected_type_ids = [_canonical_image_text_type(getattr(vt, "id", "")) for vt in (vision_types or [])]
        candidate_blocks = _filter_blocks_for_has_text(ocr_blocks, selected_type_ids)
        _record_has_text_metric(stage_status, "has_text_reconstructed_lines", 0)
        has_payload = _build_has_text_payload(
            candidate_blocks,
            max_chars=settings.HAS_VISION_MAX_TEXT_CHARS,
            max_block_chars=settings.HAS_VISION_MAX_BLOCK_CHARS,
        )
        text_content = has_payload.content
        _add_has_text_duration(
            stage_status,
            "has_text_prepare_ms",
            round((time.perf_counter() - prepare_start) * 1000),
        )
        _record_has_text_metric(stage_status, "has_text_source_blocks", has_payload.source_block_count)
        _record_has_text_metric(stage_status, "has_text_eligible_blocks", has_payload.eligible_block_count)
        _record_has_text_metric(stage_status, "has_text_unique_blocks", len(has_payload.texts))
        _record_has_text_metric(stage_status, "has_text_duplicate_blocks", has_payload.duplicate_block_count)
        _record_has_text_metric(stage_status, "has_text_clipped_blocks", has_payload.clipped_block_count)
        _record_has_text_metric(stage_status, "has_text_input_chars", has_payload.input_chars)
        _record_has_text_metric(stage_status, "has_text_emitted_chars", has_payload.emitted_chars)
        _record_has_text_metric(stage_status, "has_text_omitted_chars", has_payload.omitted_chars)
        _record_has_text_metric(stage_status, "has_text_truncated", has_payload.truncated)

        if not text_content.strip():
            logger.info(
                "HaS skipped; no eligible OCR text blocks (source=%d, eligible=%d, duplicates=%d)",
                has_payload.source_block_count,
                has_payload.eligible_block_count,
                has_payload.duplicate_block_count,
            )
            _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_no_eligible_text")
            _record_has_text_metric(
                stage_status,
                "has_text_total_ms",
                round((time.perf_counter() - total_start) * 1000),
            )
            return list(structural_entities)

        min_text_chars = int(settings.HAS_VISION_MIN_TEXT_CHARS_FOR_NER)
        compact_chars = len(_compact_text(text_content))
        _record_has_text_metric(stage_status, "has_text_compact_chars", compact_chars)
        if compact_chars < min_text_chars:
            logger.info(
                "HaS skipped; compact OCR text chars=%d below min=%d (eligible=%d)",
                compact_chars,
                min_text_chars,
                has_payload.eligible_block_count,
            )
            _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_too_short")
            _record_has_text_metric(
                stage_status,
                "has_text_total_ms",
                round((time.perf_counter() - total_start) * 1000),
            )
            return list(structural_entities)

        logger.info(
            (
                "HaS analyzing unique_blocks=%d/%d, source_blocks=%d, "
                "input_chars=%d, emitted_chars=%d, duplicate_blocks=%d, "
                "clipped_blocks=%d, omitted_chars=%d, type_configs=%d, truncated=%s"
            ),
            len(has_payload.texts),
            has_payload.eligible_block_count,
            has_payload.source_block_count,
            has_payload.input_chars,
            has_payload.emitted_chars,
            has_payload.duplicate_block_count,
            has_payload.clipped_block_count,
            has_payload.omitted_chars,
            len(vision_types or []),
            has_payload.truncated,
        )

        # ----- type ID <-> Chinese name mappings -----

        if vision_types:
            chinese_types = _build_has_text_type_names(vision_types)
            if not chinese_types:
                logger.info("HaS skipped; selected OCR types are visual-only")
                _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_visual_only_types")
                _record_has_text_metric(
                    stage_status,
                    "has_text_total_ms",
                    round((time.perf_counter() - total_start) * 1000),
                )
                return list(structural_entities)
            logger.info("HaS using types for NER: %s", chinese_types)
        else:
            chinese_types = _build_has_text_type_names()
            logger.info("HaS using default types: %s", chinese_types)
        _record_has_text_metric(stage_status, "has_text_type_count", len(chinese_types))

        ner_result = _get_cached_has_text_ner(has_client, text_content, chinese_types)
        if ner_result is not None:
            _record_has_text_metric(stage_status, "has_text_cache_status", "hit_before_slot")
            logger.info("HaS NER cache hit before local slot wait")
        else:
            _record_has_text_metric(stage_status, "has_text_cache_status", "miss")
            inflight_key = _has_text_ner_inflight_key(has_client, text_content, chinese_types)
            owns_inflight, inflight_future = _begin_has_text_ner_inflight(inflight_key)
            if not owns_inflight:
                duplicate_wait_start = time.perf_counter()
                ner_result = await asyncio.shield(inflight_future)
                wait_ms = round((time.perf_counter() - duplicate_wait_start) * 1000)
                _record_has_text_metric(stage_status, "has_text_cache_status", "shared_inflight")
                _add_has_text_duration(stage_status, "has_text_duplicate_wait_ms", wait_ms)
                logger.info("HaS NER duplicate waited %dms without local slot", wait_ms)
            else:
                try:
                    # HaS httpx is synchronous - offload to a worker thread. Concurrency
                    # is bounded by the shared GPU inference gate (HAS_NER_GLOBAL_MAX_INFLIGHT,
                    # 1 = fully serialized); identical page payloads were already merged by
                    # the inflight registry above, so raising the gate never duplicates work.
                    from app.core.gpu_inference_gate import shared_gpu_inference_slot

                    queue_start = time.perf_counter()
                    async with shared_gpu_inference_slot("OCR HaS Text NER"):
                        queue_ms = round((time.perf_counter() - queue_start) * 1000)
                        _add_has_text_duration(stage_status, "has_text_slot_wait_ms", queue_ms)
                        if queue_ms > 0:
                            logger.info("HaS Text waited %dms for shared NER slot", queue_ms)
                        ner_result = _get_cached_has_text_ner(has_client, text_content, chinese_types)
                        if ner_result is not None:
                            _record_has_text_metric(stage_status, "has_text_cache_status", "hit_after_slot")
                            logger.info("HaS NER cache hit after slot wait")
                        else:
                            model_start = time.perf_counter()
                            ner_result = await asyncio.to_thread(
                                has_client.ner, text_content, chinese_types
                            )
                            _record_has_text_metric(stage_status, "has_text_cache_status", "model_call")
                            _add_has_text_duration(
                                stage_status,
                                "has_text_model_ms",
                                round((time.perf_counter() - model_start) * 1000),
                            )
                    _finish_has_text_ner_inflight(inflight_key, inflight_future, ner_result)
                except Exception:
                    _finish_has_text_ner_inflight(inflight_key, inflight_future, None)
                    raise

        if not ner_result or not isinstance(ner_result, dict):
            logger.info("HaS: no entities found by NER")
            _record_has_text_metric(stage_status, "has_text_entity_count", len(structural_entities))
            _record_has_text_metric(
                stage_status,
                "has_text_total_ms",
                round((time.perf_counter() - total_start) * 1000),
            )
            return list(structural_entities)

        logger.info("HaS NER result: %s", ner_result)

        # ----- reverse mapping: Chinese -> type ID -----
        # Every label the prompt asked for on an item's behalf maps back to
        # that item (has_query_labels_for is the same source the prompt was
        # built from, so query and answer stay symmetric — 大写金额 -> AMOUNT).
        if vision_types:
            chinese_to_id = {}
            for vt in vision_types:
                normalized_id = _canonical_image_text_type(vt.id)
                if not normalized_id:
                    continue
                chinese_to_id[vt.name] = normalized_id
                chinese_to_id[normalized_id] = normalized_id
                canonical_name = TYPE_ID_TO_CN.get(normalized_id)
                if canonical_name:
                    chinese_to_id[canonical_name] = normalized_id
                for query_label in has_query_labels_for(normalized_id):
                    chinese_to_id[query_label] = normalized_id
        else:
            chinese_to_id = {}
            for type_id in DEFAULT_HAS_TEXT_TYPE_IDS:
                chinese_to_id[TYPE_ID_TO_CN.get(type_id, type_id)] = type_id
                for query_label in has_query_labels_for(type_id):
                    chinese_to_id[query_label] = type_id

        bridge_ner_result: dict[str, list[str]] = {}
        bridge_blocks = reconstruct_visual_line_blocks(candidate_blocks)
        _record_has_text_metric(stage_status, "has_text_reconstructed_lines", len(bridge_blocks))
        if bridge_blocks:
            bridge_payload = _build_has_text_payload(
                bridge_blocks,
                max_chars=min(settings.HAS_VISION_MAX_TEXT_CHARS, _BRIDGE_PAYLOAD_MAX_CHARS),
                max_block_chars=settings.HAS_VISION_MAX_BLOCK_CHARS,
            )
            bridge_text = bridge_payload.content
            if bridge_text.strip():
                cached_bridge = _get_cached_has_text_ner(has_client, bridge_text, chinese_types)
                if cached_bridge is not None:
                    bridge_ner_result = cached_bridge
                else:
                    from app.core.gpu_inference_gate import shared_gpu_inference_slot

                    async with shared_gpu_inference_slot("OCR HaS Text bridge NER"):
                        cached_bridge = _get_cached_has_text_ner(has_client, bridge_text, chinese_types)
                        if cached_bridge is not None:
                            bridge_ner_result = cached_bridge
                        else:
                            model_start = time.perf_counter()
                            result = await asyncio.to_thread(has_client.ner, bridge_text, chinese_types)
                            _add_has_text_duration(
                                stage_status,
                                "has_text_model_ms",
                                round((time.perf_counter() - model_start) * 1000),
                            )
                            bridge_ner_result = result if isinstance(result, dict) else {}

        entities = []
        min_len_by_type = _NER_MIN_LEN_BY_TYPE

        merged_ner_result = dict(ner_result)
        for entity_type, entity_list in bridge_ner_result.items():
            if not entity_list:
                continue
            merged_ner_result.setdefault(entity_type, [])
            for text in entity_list:
                clean_text = _compact_text(text)
                if clean_text and clean_text not in merged_ner_result[entity_type]:
                    merged_ner_result[entity_type].append(clean_text)

        for entity_type, entity_list in merged_ner_result.items():
            if not entity_list:
                continue

            # Open vocabulary: the type IS what the model returned. If it matches a
            # label we sent for a schema item, use that item's id; otherwise keep the
            # raw model label (识别出来是啥就是啥) — never drop, never reconcile.
            normalized_type = chinese_to_id.get(entity_type, entity_type)
            min_len = min_len_by_type.get(normalized_type, _NER_DEFAULT_MIN_LEN)

            for entity_text in entity_list:
                text = entity_text.strip() if entity_text else ""
                if normalized_type in {"COMPANY_NAME", "BANK_NAME", "BANK_ACCOUNT", "AMOUNT"}:
                    text = _compact_text(text)
                if not text:
                    continue
                if len(text) < min_len:
                    # Below-min-length values (e.g. 性别 男) are kept: the
                    # matcher attaches them only by block equality or isolated
                    # token (_is_strict_match_entity), never bare containment.
                    logger.debug("HaS kept short value for strict matching: '%s' (%s)", text, normalized_type)

                entities.append({
                    "type": normalized_type,
                    "text": text,
                })
                logger.debug("HaS found entity: %s (%s)", text, normalized_type)

        # Structural table amounts the NER did not already return (value-level
        # dedupe via _amount_value_signature, same as the matcher uses).
        entities = _merge_table_amount_entities(entities, table_amount_entities)

        # Form-field document numbers the NER did not already return.
        entities = _merge_form_field_document_entities(entities, form_document_entities)

        # Boxes come from matching these values back to OCR blocks; mIoU is the
        # only merge step.
        logger.info("HaS total %d sensitive entities found", len(entities))
        _record_has_text_metric(stage_status, "has_text_entity_count", len(entities))
        _record_has_text_metric(
            stage_status,
            "has_text_total_ms",
            round((time.perf_counter() - total_start) * 1000),
        )
        return entities

    except Exception as e:
        logger.exception("HaS text analysis failed: %s", e)
        _record_has_text_metric(stage_status, "has_text_cache_status", "failed")
        _record_has_text_metric(
            stage_status,
            "has_text_total_ms",
            round((time.perf_counter() - total_start) * 1000),
        )
        # NER failed; structural table-amount / form-field recalls are still valid.
        return list(structural_entities)


# ---------------------------------------------------------------------------
# Entity-to-OCR matching
# ---------------------------------------------------------------------------

DOCUMENT_TITLE_SUFFIXES = {
    "合同",
    "协议",
    "清单",
    "方案",
    "报告",
    "通知",
    "函",
}


def _is_low_signal_vision_entity(entity_type: str, entity_text: str) -> bool:
    compact = _compact_text(entity_text)
    if not compact:
        return True
    return False


def _entity_type_from_block_context(entity_type: str, entity_text: str, block_text: str) -> str | None:
    return _canonical_image_text_type(entity_type)

def _extend_entity_for_visual_match(entity_type: str, block_text: str, entity_text: str, start: int) -> str:
    """Extend short semantic values to adjacent visual suffixes in the same line.

    HaS/field completion often returns the core business object, while the
    visible document title appends a generic suffix such as "合同".
    For redaction coordinates, the suffix belongs to the same visual phrase and
    must be covered to avoid readable tail characters.
    """
    if entity_type != "PROPERTY" or start < 0:
        return entity_text
    tail_start = start + len(entity_text)
    tail = _compact_text(block_text[tail_start: tail_start + _PROPERTY_TITLE_TAIL_LOOKAHEAD_CHARS])
    for suffix in sorted(DOCUMENT_TITLE_SUFFIXES, key=len, reverse=True):
        if tail.startswith(suffix):
            return entity_text + suffix
    return entity_text


def _char_visual_units(text: str) -> float:
    total = 0.0
    for ch in text or "":
        if ch.isspace():
            total += _CHAR_UNIT_SPACE
        elif "\u4e00" <= ch <= "\u9fff":
            total += _CHAR_UNIT_CJK
        elif ch.isdigit() or ("a" <= ch.lower() <= "z"):
            total += _CHAR_UNIT_ALNUM
        elif ch in ".,:;()[]{}<>-/\\|_+=*&^%$#@!?~`'\"":
            total += _CHAR_UNIT_PUNCT
        else:
            total += _CHAR_UNIT_OTHER
    return max(total, _CHAR_UNIT_MIN_TOTAL)










def _infer_typical_textline_height(blocks: list[OCRTextBlock]) -> int | None:
    heights = [
        block.height
        for block in blocks
        if block.height > _TEXTLINE_MIN_HEIGHT_PX
        and block.width > block.height
        and not block.text.lstrip().startswith(("<table", "<div"))
    ]
    if not heights:
        return None
    heights = sorted(heights)
    return int(heights[(len(heights) - 1) // 2])



def _dedupe_ocr_regions(regions: list[SensitiveRegion]) -> list[SensitiveRegion]:
    """Drop OCR regions that are spatial near-duplicates (same pixels).

    A single IoU pass with no type/text/source/ranking rules. Only regions that
    essentially coincide are merged, so two real PII values on different parts of
    the page — e.g. the same date in three table rows, or a name in the 姓名 cell
    and again in a signature — are always kept. The old bucket-key + same-line +
    startswith heuristics each risked dropping a distinct value (a missed
    redaction); IoU alone cannot.

    One containment pass runs first: mixed-granularity block sets (PP-Structure
    lines + PaddleOCR-VL layout paragraphs) can match the same value at both
    granularities, producing nested regions for one physical instance. A region
    whose box fully contains a strictly smaller region carrying the same type
    and same value is redundant outer evidence and is dropped — the entity's
    own pixels stay covered by the tighter box. Pure geometry, no thresholds;
    distinct occurrences never nest, so they are never dropped. Value identity
    is the matched text, except AMOUNT which reuses _amount_value_signature
    (the two engines read the same span with divergent punctuation, e.g.
    ￥1431400.00元 vs ￥1431400，00元 — one value, not two findings).
    """
    from app.services.vision.region_merger import deduplicate_by_iou

    def contains(outer: SensitiveRegion, inner: SensitiveRegion) -> bool:
        return (
            outer.left <= inner.left
            and outer.top <= inner.top
            and outer.left + outer.width >= inner.left + inner.width
            and outer.top + outer.height >= inner.top + inner.height
        )

    def value_identity(region: SensitiveRegion) -> tuple[str, str]:
        if region.entity_type == "AMOUNT":
            signature = _amount_value_signature(region.text)
            if signature:
                return ("amount", signature)
        return ("text", str(region.text or ""))

    tightest = [
        region
        for region in regions
        if not any(
            other is not region
            and other.entity_type == region.entity_type
            and value_identity(other) == value_identity(region)
            and region.width * region.height > other.width * other.height
            and contains(region, other)
            for other in regions
        )
    ]

    return deduplicate_by_iou(tightest, lambda r: (r.left, r.top, r.width, r.height))


# Chinese label -> canonical type id mapping for HaS entity matching.
_HAS_ENTITY_TYPE_MAPPING = {
    "人名": "PERSON",
    "姓名": "PERSON",
    "昵称": "NICKNAME",
    "实验室名称": "LAB_NAME",
    "实验室": "LAB_NAME",
    "机构": "INSTITUTION_NAME",
    "电话": "PHONE",
    "手机号": "PHONE",
    "电话号码": "PHONE",
    "身份证": "ID_CARD",
    "身份证号": "ID_CARD",
    "银行卡": "BANK_CARD",
    "银行卡号": "BANK_CARD",
    "地址": "ADDRESS",
    "公司": "COMPANY_NAME",
    "公司名称": "COMPANY_NAME",
}


def _block_search_text(block: OCRTextBlock) -> str:
    """Authoritative text to match entities against.

    block.chars are produced together with the box geometry, so when the OCR
    service mis-pairs text labels with boxes (observed PP-StructureV3
    pathology: duplicated boxes whose `text` belongs to a different box), the
    joined char boxes still spell the box's real content. The text label is
    kept only while the chars corroborate it as the same content:

    - same glyph sequence (whitespace ignored);
    - equal glyph counts: the char-level recognizer read the same glyphs
      differently (帐号 vs 账号, 江苏省×X市 vs 江苏省XX市);
    - chars form an in-order subsequence of the text: the service dropped
      some char boxes (observed: chars 9,000.00 under text 89,000.00) —
      partial evidence of the same content, not a contradiction.

    Anything else means the chars spell different content than the label, so
    match against the chars text: a value is only ever attached to a box that
    actually contains it. The old whole-block fallback attached the lying
    text label to a box holding different pixels.
    """
    block_text = str(block.text or "")
    chars = getattr(block, "chars", None) or []
    if not chars:
        return block_text
    chars_text = "".join(str(char_box.get("c", "")) for char_box in chars)
    compact_chars = _compact_text(chars_text)
    compact_block = _compact_text(block_text)
    if compact_chars == compact_block:
        return block_text
    if len(compact_chars) == len(compact_block):
        return block_text
    corresponding_glyphs = sum(
        size
        for _block_pos, _chars_pos, size in SequenceMatcher(
            None, compact_block, compact_chars, autojunk=False
        ).get_matching_blocks()
    )
    if corresponding_glyphs == len(compact_chars):
        return block_text
    return chars_text


def _entity_char_box_x_span(
    block: OCRTextBlock,
    search_text: str,
    span_start: int,
    span_end: int,
) -> tuple[int, int] | None:
    """X-range of the char boxes proven to render search_text[span_start:span_end).

    No proportional estimation and no thresholds: glyph correspondence comes
    from the monotone alignment (difflib matching blocks) of the two
    whitespace-stripped glyph sequences, which absorbs whitespace differences,
    same-glyph misreads (帐/账) and dropped char boxes alike. A crop is
    returned only when the span's first and last glyphs each have a
    corresponding box — char boxes run left-to-right, so that union also
    covers interior glyphs whose own box was dropped. Anything unprovable
    returns None and the caller masks the whole block.
    """
    chars = getattr(block, "chars", None) or []
    if not chars:
        return None

    # One entry per non-whitespace glyph; multi-char tokens ("2024-05-14")
    # contribute their box once per glyph.
    glyph_boxes: list[dict] = []
    chars_glyph_list: list[str] = []
    for char_box in chars:
        for glyph in _compact_text(str(char_box.get("c", ""))):
            chars_glyph_list.append(glyph)
            glyph_boxes.append(char_box)
    if not glyph_boxes:
        return None
    chars_glyphs = "".join(chars_glyph_list)

    # Map the raw [span_start, span_end) onto glyph (whitespace-free) indexes.
    search_glyph_list: list[str] = []
    span_glyph_start = span_glyph_end = 0
    for index, ch in enumerate(search_text):
        if ch.isspace():
            continue
        if index < span_start:
            span_glyph_start += 1
        if index < span_end:
            span_glyph_end += 1
        search_glyph_list.append(ch)
    if span_glyph_end <= span_glyph_start:
        return None
    search_glyphs = "".join(search_glyph_list)

    box_by_glyph: list[dict | None] = [None] * len(search_glyphs)
    if search_glyphs == chars_glyphs:
        box_by_glyph = list(glyph_boxes)
    else:
        for search_pos, chars_pos, size in SequenceMatcher(
            None, search_glyphs, chars_glyphs, autojunk=False
        ).get_matching_blocks():
            for offset in range(size):
                box_by_glyph[search_pos + offset] = glyph_boxes[chars_pos + offset]

    span_boxes = box_by_glyph[span_glyph_start:span_glyph_end]
    if not span_boxes or span_boxes[0] is None or span_boxes[-1] is None:
        return None
    left = int(min(box["x1"] for box in span_boxes if box is not None))
    right = int(max(box["x2"] for box in span_boxes if box is not None))
    if right <= left:
        return None
    return left, right


def _regions_overlap(a: SensitiveRegion, b: SensitiveRegion) -> bool:
    """The two regions share any pixels (topological, no thresholds)."""
    return (
        a.left < b.left + b.width
        and b.left < a.left + a.width
        and a.top < b.top + b.height
        and b.top < a.top + a.height
    )


def _char_word_class(ch: str) -> str:
    if "一" <= ch <= "鿿":
        return "cjk"
    if ch.isalnum():
        return "alnum"
    return ""


def _is_isolated_token_occurrence(text: str, start: int, end: int) -> bool:
    """The occurrence [start, end) is a whole token inside the block text.

    Token boundaries are identity facts, not tuned rules: a side is a boundary
    when it is the string edge, a non-word character (punctuation/space), or a
    script-class change (CJK vs latin/digit). 男 in 性别：男 is a token; 男
    inside 男科 is not.
    """
    if start < 0 or start >= end or end > len(text):
        return False
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    first_class = _char_word_class(text[start])
    last_class = _char_word_class(text[end - 1])
    before_is_boundary = not before or not _char_word_class(before) or _char_word_class(before) != first_class
    after_is_boundary = not after or not _char_word_class(after) or _char_word_class(after) != last_class
    return before_is_boundary and after_is_boundary


def _is_strict_match_entity(entity_type: str, entity_text: str) -> bool:
    """Whether a value is below the NER min length for its type.

    Such values (e.g. 男 under GENDER) are kept instead of dropped, but they
    only attach to a block when the block text IS the value or the value is an
    isolated token (_is_isolated_token_occurrence) — never by bare containment,
    and never via fuzzy or whole-table fallbacks. Reuses the existing
    _NER_MIN_LEN_BY_TYPE constants; no new thresholds.
    """
    min_len = _NER_MIN_LEN_BY_TYPE.get(entity_type, _NER_DEFAULT_MIN_LEN)
    return len(entity_text.strip()) < min_len


# RMB unit decoration accepted around a standalone amount cell (data).
_AMOUNT_UNIT_SUFFIX_CHARS = "元"


def _is_same_amount_value_block(entity_text: str, block_text: str) -> bool:
    """Same amount value in a different display form (￥1431400.00元 vs 1431400，00).

    Pure value-level normalization via _amount_value_signature; the block must
    itself BE one amount value (the existing standalone-amount format test,
    after stripping currency/unit decoration), so running text that merely
    contains the same digits never matches.
    """
    entity_signature = _amount_value_signature(entity_text)
    if not entity_signature:
        return False
    candidate = _compact_text(block_text).strip(_AMOUNT_UNIT_SUFFIX_CHARS)
    if not _is_standalone_amount_ocr_block(candidate):
        return False
    return _amount_value_signature(_compact_amount_candidate(candidate)) == entity_signature


def _narrow_charsless_block_to_lines(
    block: OCRTextBlock,
    block_text: str,
    occurrence_start: int,
    occurrence_text: str,
    prepared_blocks: list,
) -> tuple[int, int, int, int] | None:
    """Narrow a value matched on a chars-less PaddleOCR-VL paragraph block to the
    one PP-Structure line (with char boxes) it actually sits on.

    The VL supplement adds whole-paragraph blocks with no char boxes, so a value
    matched there is masked over the entire paragraph. The value sits on ONE of
    the char-boxed line blocks geometrically inside the paragraph: pick the line
    whose glyphs best match the value (argmax matched glyphs) and return the
    tight box of the matched char boxes (tight X) at that line's height (Y).
    Returns None when no line is located, so the caller keeps the safe
    whole-block mask and the value is never left unredacted.
    """
    if getattr(block, "chars", None):
        return None
    bl, bt, bw, bh = block.left, block.top, block.width, block.height
    lines = []
    for cand, cand_text, _is_tv in prepared_blocks:
        if cand is block or not getattr(cand, "chars", None):
            continue
        ccx = cand.left + cand.width / 2.0
        ccy = cand.top + cand.height / 2.0
        if bt <= ccy <= bt + bh and bl <= ccx <= bl + bw:
            lines.append((cand, cand_text))
    if len(lines) < 2:
        return None
    lines.sort(key=lambda lt: (round(lt[0].top), lt[0].left))

    occurrence_end = occurrence_start + len(occurrence_text)
    entity_glyphs = _compact_text(block_text[occurrence_start:occurrence_end])
    if not entity_glyphs:
        return None
    best_count = 0
    best_line = None
    best_boxes = []
    for cand, _cand_text in lines:
        line_glyphs = []
        line_boxes = []
        for char_box in (getattr(cand, "chars", None) or []):
            for glyph in _compact_text(str(char_box.get("c", ""))):
                line_glyphs.append(glyph)
                line_boxes.append(char_box)
        if not line_glyphs:
            continue
        matched_boxes = []
        for _epos, lpos, size in SequenceMatcher(
            None, entity_glyphs, "".join(line_glyphs), autojunk=False
        ).get_matching_blocks():
            for offset in range(size):
                matched_boxes.append(line_boxes[lpos + offset])
        if len(matched_boxes) > best_count:
            best_count = len(matched_boxes)
            best_line = cand
            best_boxes = matched_boxes
    if best_line is None or not best_boxes:
        return None
    left = min(int(box["x1"]) for box in best_boxes)
    right = max(int(box["x2"]) for box in best_boxes)
    if right <= left:
        return None
    return int(left), int(best_line.top), int(right - left), int(best_line.height)


def match_entities_to_ocr(
    ocr_blocks: list[OCRTextBlock],
    entities: list[dict[str, str]],
) -> list[SensitiveRegion]:
    """
    Match HaS-detected entities to OCR text blocks using text matching to get
    precise bounding boxes.  Supports sub-word positioning, HTML table expansion,
    and fuzzy matching.
    """
    regions: list[SensitiveRegion] = []

    # Expand HTML tables into virtual cell blocks
    expanded_blocks: list[OCRTextBlock] = []
    table_virtual_block_ids: set[int] = set()
    for block in ocr_blocks:
        if block.text.startswith("<table") and "</table>" in block.text:
            cell_blocks = extract_table_cells(block.text, block)
            if cell_blocks:
                expanded_blocks.extend(cell_blocks)
                table_virtual_block_ids.update(id(cell) for cell in cell_blocks)
                logger.debug("Expanded table into %d cells", len(cell_blocks))
            else:
                expanded_blocks.append(block)
        else:
            expanded_blocks.append(block)
    # No visual-line reconstruction and no sub-span position/size estimation:
    # match against the real OCR blocks and redact the whole matched block. mIoU
    # is the sole merge step downstream.
    # Table-virtual cells sort after direct blocks; the order is identical for
    # every entity, so sort once and resolve each block's authoritative text
    # (_block_search_text: chars-verified against the box) once outside the loop.
    ordered_blocks = sorted(expanded_blocks, key=lambda item: id(item) in table_virtual_block_ids)
    prepared_blocks = [
        (block, _block_search_text(block), id(block) in table_virtual_block_ids)
        for block in ordered_blocks
    ]

    standalone_amount_signatures = {
        signature
        for _block, search_text, is_table_virtual in prepared_blocks
        if not is_table_virtual and _is_standalone_amount_ocr_block(search_text)
        for signature in [_amount_value_signature(search_text)]
        if signature
    }

    for entity in entities:
        entity_text = entity.get("text", "").strip()
        entity_type = entity.get("type", "UNKNOWN")
        entity_source = str(entity.get("source") or "").strip()

        if not entity_text:
            continue

        normalized_type = _canonical_image_text_type(_HAS_ENTITY_TYPE_MAPPING.get(entity_type, entity_type.upper()))

        if _is_low_signal_vision_entity(normalized_type, entity_text):
            logger.debug("HaS skipped low-signal vision entity: '%s' (%s)", entity_text, normalized_type)
            continue

        matched = False
        strict_value = _is_strict_match_entity(normalized_type, entity_text)

        direct_amount_signatures: set[str] = set()
        # This entity's matches, with the evidence they carry: whether the
        # region pins the value's position (the block IS the value, or the
        # char-aligned crop located its glyphs) versus an uncropped
        # whole-block containment claim (no position evidence at all).
        entity_regions: list[tuple[SensitiveRegion, bool, bool]] = []
        for block, block_text, is_table_virtual in prepared_blocks:
            if block_text.startswith("<table"):
                continue

            # Exact containment match against the authoritative text. Blocks
            # whose char boxes disprove their text label never reach here with
            # the lying label (_block_search_text), so a value is only ever
            # attached to a box that actually contains it.
            if entity_text in block_text:
                contextual_type = _entity_type_from_block_context(normalized_type, entity_text, block_text)
                if contextual_type is None:
                    continue
                search_from = 0
                while True:
                    occurrence_start = block_text.find(entity_text, search_from)
                    if occurrence_start < 0:
                        break
                    if strict_value and not _is_isolated_token_occurrence(
                        block_text,
                        occurrence_start,
                        occurrence_start + len(entity_text),
                    ):
                        search_from = occurrence_start + max(1, len(entity_text))
                        continue
                    visual_text, visual_occurrence_start = _visual_match_span_for_entity(
                        contextual_type,
                        block_text,
                        entity_text,
                        occurrence_start,
                    )
                    if contextual_type == "AMOUNT":
                        amount_signature = _amount_value_signature(visual_text)
                        if (
                            amount_signature in standalone_amount_signatures
                            and not _is_standalone_amount_ocr_block(block_text)
                        ):
                            search_from = occurrence_start + max(1, len(entity_text))
                            continue
                        if is_table_virtual and amount_signature in direct_amount_signatures:
                            search_from = occurrence_start + max(1, len(entity_text))
                            continue
                        if not is_table_virtual and amount_signature:
                            direct_amount_signatures.add(amount_signature)
                    # Value-level crop: narrow x to the union of the char boxes
                    # proven by glyph alignment to render this occurrence;
                    # otherwise mask the whole block (safe). y/height stay the
                    # block's full line height (705318c contract: a single-line
                    # OCR block keeps its full vertical extent so the mask
                    # always covers the glyphs).
                    rl, rt, rw, rh = block.left, block.top, block.width, block.height
                    crop_span = _entity_char_box_x_span(
                        block,
                        block_text,
                        visual_occurrence_start,
                        visual_occurrence_start + len(visual_text),
                    )
                    if crop_span is not None:
                        rl, rw = crop_span[0], crop_span[1] - crop_span[0]
                    else:
                        narrowed_box = _narrow_charsless_block_to_lines(
                            block, block_text, visual_occurrence_start, visual_text, prepared_blocks
                        )
                        if narrowed_box is not None:
                            rl, rt, rw, rh = narrowed_box
                            crop_span = (rl, rl + rw)
                    has_position_evidence = (
                        crop_span is not None
                        or _compact_text(block_text) == _compact_text(visual_text)
                    )
                    entity_regions.append((
                        SensitiveRegion(
                            text=visual_text,
                            entity_type=contextual_type,
                            left=rl,
                            top=rt,
                            width=rw,
                            height=rh,
                            confidence=1.0,
                            source=(
                                entity_source
                                if entity_source in {"table_semantic", "form_field_ocr"}
                                else
                                "table_cell_match"
                                if is_table_virtual
                                else "text_match"
                            ),
                        ),
                        has_position_evidence,
                        not has_position_evidence,
                    ))
                    logger.debug(
                        "MATCH '%s' in '%s...' @ (%d, %d, %d, %d)",
                        entity_text, block_text[:20], rl, rt, rw, rh,
                    )
                    search_from = occurrence_start + max(1, len(entity_text))
                matched = True
                continue

            # Same amount value in a different display form — full/half-width
            # currency and separator variants (￥1431400.00元 vs 1431400，00).
            if normalized_type == "AMOUNT" and _is_same_amount_value_block(entity_text, block_text):
                amount_signature = _amount_value_signature(entity_text)
                if is_table_virtual and amount_signature in direct_amount_signatures:
                    continue
                if not is_table_virtual and amount_signature:
                    direct_amount_signatures.add(amount_signature)
                entity_regions.append((
                    SensitiveRegion(
                        text=block_text.strip() or entity_text,
                        entity_type=normalized_type,
                        left=block.left,
                        top=block.top,
                        width=block.width,
                        height=block.height,
                        confidence=1.0,
                        source=(
                            entity_source
                            if entity_source in {"table_semantic", "form_field_ocr"}
                            else
                            "table_cell_match"
                            if is_table_virtual
                            else "text_match"
                        ),
                    ),
                    True,  # the block is the value in another display form
                    False,
                ))
                logger.debug("MATCH '%s' ~ '%s' (amount value form)", entity_text, block_text[:20])
                matched = True

        # An uncropped whole-block region claimed only through text
        # containment (a chars-less PaddleOCR-VL paragraph) carries no
        # position evidence for the value. When the same entity also has a
        # position-evidenced region — its own dedicated box (the handwriting
        # block of a signature) or a char-aligned crop on another block — and
        # the two overlap, that region is the occurrence; the whole-block
        # claim is redundant cover over label/context. Overlap is topological
        # (intersection exists), immune to detector box wobble.
        evidenced_regions = [
            region for region, evidenced, _positionless in entity_regions if evidenced
        ]
        for region, _evidenced, positionless in entity_regions:
            if positionless and any(
                _regions_overlap(region, evidenced) for evidenced in evidenced_regions
            ):
                logger.debug(
                    "Dropped positionless whole-block claim for '%s' (evidenced region exists)",
                    region.text,
                )
                continue
            regions.append(region)

        # Fuzzy match (handles minor OCR misreads). Runs only after NO block
        # contained the value: the old in-loop fuzzy fired on an earlier
        # near-miss block and `break`-ed past a later block holding the exact
        # text, leaving that occurrence unredacted (e.g. the same credit code
        # printed twice, one copy misread by OCR).
        if (
            not matched
            and not strict_value
            and len(entity_text) >= _FUZZY_MATCH_MIN_ENTITY_LEN
        ):
            for block, block_text, _is_table_virtual in prepared_blocks:
                if block_text.startswith("<table"):
                    continue
                if len(block_text) <= max(len(entity_text) * _FUZZY_MATCH_BLOCK_LEN_MULT, _FUZZY_MATCH_BLOCK_LEN_FLOOR) and (
                    SequenceMatcher(None, entity_text, block_text).ratio() > _FUZZY_MATCH_RATIO
                ):
                    regions.append(SensitiveRegion(
                        text=entity_text,
                        entity_type=normalized_type,
                        left=block.left,
                        top=block.top,
                        width=block.width,
                        height=block.height,
                        confidence=_FUZZY_MATCH_CONFIDENCE,
                        source="fuzzy_match",
                    ))
                    logger.debug("MATCH '%s' ~ '%s...' (fuzzy)", entity_text, block_text[:20])
                    matched = True
                    break

        # Fallback: search in original (unexpanded) blocks
        if not matched and not strict_value:
            for block in ocr_blocks:
                if block.text.startswith("<table") and entity_text in block.text:
                    regions.append(SensitiveRegion(
                        text=entity_text,
                        entity_type=normalized_type,
                        left=block.left,
                        top=block.top,
                        width=block.width,
                        height=block.height,
                        confidence=_TABLE_FALLBACK_CONFIDENCE,
                        source="table_fallback",
                    ))
                    logger.debug(
                        "MATCH '%s' in table @ (%d, %d, %d, %d) [fallback]",
                        entity_text, block.left, block.top, block.width, block.height,
                    )
                    break

    deduped_regions = _dedupe_ocr_regions(regions)
    logger.info("Matched %d entities to OCR blocks (%d after dedupe)", len(regions), len(deduped_regions))
    return deduped_regions
