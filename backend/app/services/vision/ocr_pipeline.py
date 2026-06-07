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

from PIL import Image, ImageOps

from app.core.config import settings
from app.models.type_mapping import TYPE_ID_TO_CN
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

_AMOUNT_TOKEN_PREFIX_CHARS = frozenset("¥￥$€£")
_AMOUNT_TOKEN_BEFORE_BLOCKERS = frozenset("_.")
_AMOUNT_TOKEN_AFTER_BLOCKERS = frozenset("_.%")

OCR_VISUAL_ENTITY_TYPES = {
    "SEAL",
    "SIGNATURE",
    "FINGERPRINT",
    "PHOTO",
    "QR_CODE",
    "HANDWRITING",
    "WATERMARK",
}

# --- Tuning constants (extracted magic numbers) -------------------------------
# Window (seconds) for treating a recent negative HaS health check as still valid.
_HAS_NEGATIVE_HEALTH_TTL_SEC = 5.0

# Default fallback median text-line height (px) when no block heights are known.
_DEFAULT_BLOCK_HEIGHT_PX = 12.0

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
_AMOUNT_TOKEN_MIN_DIGITS = 5
_AMOUNT_TOKEN_MAX_DIGITS = 14
_AMOUNT_TOKEN_MIN_DIGITS_WITH_SEPARATOR = 4
# An amount value signature drops a trailing ".00"; require more than this many digits first.
_AMOUNT_TRAILING_ZEROS_MIN_DIGITS = 2

# Visual-row grouping tolerance: fraction of median block height, with a floor.
_VISUAL_ROW_TOLERANCE_HEIGHT_RATIO = 0.75
_VISUAL_ROW_TOLERANCE_MIN_PX = 8.0
# Amount-table column detection needs at least this many cells in a header row.
_AMOUNT_TABLE_MIN_ROW_CELLS = 3
# Horizontal padding around an amount column header: fraction of header width, with a floor.
_AMOUNT_COLUMN_PAD_WIDTH_RATIO = 0.45
_AMOUNT_COLUMN_PAD_MIN_PX = 12.0
# Slack (px) below a header baseline when testing column membership.
_AMOUNT_COLUMN_HEADER_SLACK_PX = 8

# Person form-field value visual-unit bounds and label-proximity tuning.
_PERSON_FIELD_LABEL_LOOKAHEAD_CHARS = 5
_PERSON_FIELD_MIN_PREFIX_UNITS = 2.0
_PERSON_FIELD_SHORT_LABEL_MAX_OFFSET = 2
_PERSON_FIELD_LONG_PREFIX_UNITS = 4.0
_PERSON_FIELD_VALUE_MAX_UNITS = 8.0
_PERSON_FIELD_VALUE_MIN_UNITS = 2
# Loose person-form expansion: max trailing-suffix length to treat as same value.
_PERSON_FORM_EXPANSION_MAX_SUFFIX = 2
# Quality scoring weights for person form-field candidate ranking.
_PERSON_FIELD_ANCHOR_WEIGHT = 4
_PERSON_FIELD_TRAILING_PENALTY = 3
_PERSON_FIELD_MAX_DELIMITER_SCORE = 4
_PERSON_FIELD_ODD_CHAR_PENALTY = 3
# Drop a person candidate whose block overlaps an already-selected block by this ratio.
_PERSON_FIELD_OVERLAP_DROP_RATIO = 0.65

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

# Per-character visual-unit weights.
_CHAR_UNIT_SPACE = 0.25
_CHAR_UNIT_CJK = 1.0
_CHAR_UNIT_ALNUM = 0.56
_CHAR_UNIT_PUNCT = 0.35
_CHAR_UNIT_OTHER = 0.65
_CHAR_UNIT_MIN_TOTAL = 0.01

# Form-field label/value width tuning.
_FORM_LABEL_MAX_UNITS = 8.0
_FORM_ROW_MIN_WIDTH_HEIGHT_MULT = 8
_FORM_ROW_MIN_DELIMITERS = 3
_FIELD_VALUE_WIDTH_MIN_HEIGHT_PX = 10
_FIELD_VALUE_WIDTH_HEIGHT_RATIO = 0.65

# Visual-wrap break search window and scoring.
_WRAP_BREAK_SEARCH_WINDOW = 12
_WRAP_BREAK_SCORE_PUNCT = 30
_WRAP_BREAK_SCORE_AMOUNT_PREFIX = 24
_WRAP_BREAK_SCORE_AMOUNT_DIGIT = 20
_WRAP_BREAK_SCORE_SPACE = 12

# Typical text-line height inference: minimum block height to consider.
_TEXTLINE_MIN_HEIGHT_PX = 4

# Entity-region estimation tuning.
_COMPRESSED_LINES_MIN_HEIGHT_MULT = 1.5
_COMPRESSED_LINES_PER_LINE_MULT = 0.65
_MULTILINE_SPLIT_HEIGHT_MULT = 1.7
_VISUAL_LINE_HEIGHT_MULT = 1.55
_LINE_HEIGHT_CAP_MULT = 1.2
_ENTITY_REGION_PAD_X_RATIO = 0.006
_ENTITY_REGION_PAD_X_MIN = 2
_ENTITY_REGION_MIN_WIDTH_FLOOR = 18
_ENTITY_REGION_MIN_WIDTH_PER_CHAR = 10
_ENTITY_REGION_START_RATIO_CLAMP = 1.0
_ENTITY_REGION_WIDTH_RATIO_FLOOR = 0.01

# Dedupe priority and ranking tuning.
_DEDUPE_BUCKET_PX = 4
_DEDUPE_AMOUNT_OVERLAP_DUP = 0.35
_DEDUPE_DEFAULT_OVERLAP_DUP = 0.7
_DEDUPE_SAME_LINE_VERTICAL_OVERLAP = 0.55
_DEDUPE_SAME_LINE_BOX_OVERLAP = 0.25
_DEDUPE_SAME_LINE_HORIZONTAL_GAP_RATIO = 0.6
_DEDUPE_SHORT_VALUE_MAX_UNITS = 6.0
_DEDUPE_SAME_CENTER_HEIGHT_RATIO = 0.65
_DEDUPE_LONG_VALUE_MIN_UNITS = 6.0
_DEDUPE_PRIORITY = {
    "BANK_NAME": 5,
    "BANK_ACCOUNT": 5,
    "PHONE": 5,
    "ID_CARD": 5,
    "AMOUNT": 5,
    "PERSON": 5,
    "ORG": 3,
    "LEGAL_PARTY": 2,
}
_DEDUPE_SOURCE_RANK_FORM_FIELD = 3
_DEDUPE_SOURCE_RANK_TEXT_MATCH = 2
_DEDUPE_SOURCE_RANK_VISUAL_TABLE = 1

# Amount coordinate-conflict resolution tuning.
_AMOUNT_CONFLICT_MIN_AMOUNTS = 3
_AMOUNT_COLUMN_CLUSTER_TOLERANCE_PX = 70
_AMOUNT_COLUMN_DOMINANT_MIN_CLUSTER = 3
_AMOUNT_CONFLICT_OVERLAP_MIN = 0.85

# Entity-to-OCR matching: fuzzy match and per-type width-cap tuning.
_FUZZY_MATCH_MIN_ENTITY_LEN = 4
_FUZZY_MATCH_BLOCK_LEN_MULT = 3
_FUZZY_MATCH_BLOCK_LEN_FLOOR = 24
_FUZZY_MATCH_RATIO = 0.9
_FUZZY_MATCH_CONFIDENCE = 0.9
_TABLE_FALLBACK_CONFIDENCE = 0.8
_TOKEN_CAP_MIN_PX = 24
_TOKEN_CAP_HEIGHT_FLOOR = 10
_TOKEN_CAP_HEIGHT_RATIO = 0.75
_AMOUNT_TOKEN_CAP_MIN_PX = 28
_AMOUNT_TOKEN_CAP_PERCENT_HEIGHT_RATIO = 0.42
_AMOUNT_TOKEN_CAP_HEIGHT_RATIO = 0.75

_OCR_TEXT_BLOCK_CACHE_LOCK = threading.Lock()
_OCR_TEXT_BLOCK_CACHE: OrderedDict[
    tuple[Any, ...],
    tuple[float, list[OCRTextBlock], list[SensitiveRegion]],
] = OrderedDict()
_OCR_TEXT_BLOCK_INFLIGHT_LOCK = threading.Lock()
_OCR_TEXT_BLOCK_INFLIGHT: dict[tuple[Any, ...], _OcrOutputInflight] = {}
_HAS_TEXT_NER_LOCK: asyncio.Lock | None = None
_HAS_TEXT_NER_LOCK_LOOP: asyncio.AbstractEventLoop | None = None
_HAS_TEXT_NER_INFLIGHT: dict[tuple[Any, ...], asyncio.Future] = {}
_HAS_TEXT_NER_INFLIGHT_LOOP: asyncio.AbstractEventLoop | None = None


class _OcrOutputInflight:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: tuple[list[OCRTextBlock], list[SensitiveRegion]] | None = None
        self.error: BaseException | None = None


def _get_has_text_ner_lock() -> asyncio.Lock:
    """Serialize local HaS Text calls inside this process.

    llama.cpp serves one small local model for all scanned-PDF pages. Letting
    page workers submit concurrent NER calls tends to increase cold-start tail
    latency without improving recall, while OCR and visual feature grounding can still run on
    their own paths.
    """
    global _HAS_TEXT_NER_LOCK, _HAS_TEXT_NER_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _HAS_TEXT_NER_LOCK is None or _HAS_TEXT_NER_LOCK_LOOP is not loop:
        _HAS_TEXT_NER_LOCK = asyncio.Lock()
        _HAS_TEXT_NER_LOCK_LOOP = loop
    return _HAS_TEXT_NER_LOCK


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


def clear_ocr_text_block_cache() -> None:
    """Clear process-local OCR output cache. Intended for tests and admin hooks."""
    with _OCR_TEXT_BLOCK_CACHE_LOCK:
        _OCR_TEXT_BLOCK_CACHE.clear()
    with _OCR_TEXT_BLOCK_INFLIGHT_LOCK:
        _OCR_TEXT_BLOCK_INFLIGHT.clear()


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


def _is_percent_value_text(text: str) -> bool:
    compact = _compact_text(text)
    return bool(compact) and compact in {_compact_text(token) for token in _iter_percent_value_tokens(compact)}


def _is_amount_token_before_boundary(text: str, start: int) -> bool:
    if start <= 0:
        return True
    prev = text[start - 1]
    return not (prev.isalnum() or prev in _AMOUNT_TOKEN_BEFORE_BLOCKERS)


def _is_amount_token_after_boundary(text: str, end: int) -> bool:
    if end >= len(text):
        return True
    nxt = text[end]
    return not (nxt.isalnum() or nxt in _AMOUNT_TOKEN_AFTER_BLOCKERS)


def _iter_probable_amount_tokens(text: str) -> list[str]:
    """Scan OCR text for standalone amount-like numeric tokens without regex."""
    tokens: list[str] = []
    raw = str(text or "")
    i = 0
    while i < len(raw):
        start = i
        if raw[i] in _AMOUNT_TOKEN_PREFIX_CHARS:
            i += 1
            if i >= len(raw) or not raw[i].isdigit():
                i = start + 1
                continue
        elif not raw[i].isdigit():
            i += 1
            continue

        last_digit_end = i
        saw_separator = False
        saw_decimal = False
        while i < len(raw):
            if raw[i].isdigit():
                last_digit_end = i + 1
                i += 1
                continue
            if raw[i] in ",，" and i + 1 < len(raw) and raw[i + 1].isdigit():
                saw_separator = True
                i += 1
                continue
            if (
                raw[i] in ".．"
                and not saw_decimal
                and i + 1 < len(raw)
                and raw[i + 1].isdigit()
            ):
                saw_decimal = True
                i += 1
                continue
            break

        end = last_digit_end
        candidate = _compact_amount_candidate(raw[start:end])
        digit_count = _amount_digit_count(candidate)
        if not (
            _AMOUNT_TOKEN_MIN_DIGITS <= digit_count <= _AMOUNT_TOKEN_MAX_DIGITS
            or (saw_separator and _AMOUNT_TOKEN_MIN_DIGITS_WITH_SEPARATOR <= digit_count <= _AMOUNT_TOKEN_MAX_DIGITS)
        ):
            i = start + 1
            continue

        if _is_amount_token_before_boundary(raw, start) and _is_amount_token_after_boundary(raw, end):
            tokens.append(candidate)
        i = max(start + 1, end)
    return tokens


def _is_probable_table_amount_token(text: str) -> bool:
    compact = _compact_amount_candidate(text)
    if not compact or "%" in compact:
        return False
    if any(ch.isalpha() for ch in compact):
        return False
    digits = _amount_digit_count(compact)
    return _AMOUNT_TOKEN_MIN_DIGITS <= digits <= _AMOUNT_TOKEN_MAX_DIGITS and bool(_iter_probable_amount_tokens(compact))


_AMOUNT_TABLE_HEADER_KEYWORDS = (
    "\u91d1\u989d",  # 金额
    "\u5355\u4ef7",  # 单价
    "\u5408\u4ef7",  # 合价
    "\u603b\u4ef7",  # 总价
    "\u4ef7\u6b3e",  # 价款
    "\u4ef7\u683c",  # 价格
    "\u8d39\u7528",  # 费用
    "\u4eba\u6c11\u5e01",  # 人民币
)

_AMOUNT_TABLE_ROW_KEYWORDS = (
    "\u5408\u8ba1",  # 合计
    "\u603b\u8ba1",  # 总计
    "\u5c0f\u8ba1",  # 小计
    "\u91d1\u989d",  # 金额
    "\u4eba\u6c11\u5e01",  # 人民币
    "\u00a5",
    "\uffe5",
)


def _has_any_compact_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    compact = _compact_text(text)
    return any(keyword in compact for keyword in keywords)


def _block_center_x(block: OCRTextBlock) -> float:
    return float(block.left) + float(block.width) / 2


def _block_center_y(block: OCRTextBlock) -> float:
    return float(block.top) + float(block.height) / 2


def _median_block_height(blocks: list[OCRTextBlock]) -> float:
    heights = sorted(float(block.height) for block in blocks if block.height > 0)
    if not heights:
        return _DEFAULT_BLOCK_HEIGHT_PX
    return heights[(len(heights) - 1) // 2]


def _group_blocks_into_visual_rows(blocks: list[OCRTextBlock]) -> list[list[OCRTextBlock]]:
    relevant = [
        block
        for block in blocks
        if str(block.text or "").strip()
        and not str(block.text or "").lstrip().lower().startswith(("<table", "<html", "<div"))
    ]
    if not relevant:
        return []

    tolerance = max(_VISUAL_ROW_TOLERANCE_MIN_PX, _median_block_height(relevant) * _VISUAL_ROW_TOLERANCE_HEIGHT_RATIO)
    rows: list[list[OCRTextBlock]] = []
    row_centers: list[float] = []
    for block in sorted(relevant, key=lambda item: (_block_center_y(item), item.left)):
        center_y = _block_center_y(block)
        best_index = None
        best_distance = tolerance + 1
        for index, row_center in enumerate(row_centers):
            distance = abs(center_y - row_center)
            if distance <= tolerance and distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            rows.append([block])
            row_centers.append(center_y)
            continue
        rows[best_index].append(block)
        row_centers[best_index] = sum(_block_center_y(item) for item in rows[best_index]) / len(rows[best_index])

    for row in rows:
        row.sort(key=lambda item: item.left)
    return rows


def _amount_table_column_ranges(rows: list[list[OCRTextBlock]]) -> list[tuple[float, float, float]]:
    ranges: list[tuple[float, float, float]] = []
    for row in rows:
        if len(row) < _AMOUNT_TABLE_MIN_ROW_CELLS:
            continue
        row_text = " ".join(block.text for block in row)
        if not _has_any_compact_keyword(row_text, _AMOUNT_TABLE_HEADER_KEYWORDS):
            continue
        for block in row:
            if not _has_any_compact_keyword(block.text, _AMOUNT_TABLE_HEADER_KEYWORDS):
                continue
            pad = max(_AMOUNT_COLUMN_PAD_MIN_PX, float(block.width) * _AMOUNT_COLUMN_PAD_WIDTH_RATIO)
            ranges.append((
                max(0.0, float(block.left) - pad),
                float(block.left + block.width) + pad,
                float(block.top + block.height),
            ))
    return ranges


def _is_in_amount_semantic_column(block: OCRTextBlock, ranges: list[tuple[float, float, float]]) -> bool:
    center = _block_center_x(block)
    top = float(block.top)
    return any(left <= center <= right and top >= header_bottom - _AMOUNT_COLUMN_HEADER_SLACK_PX for left, right, header_bottom in ranges)


def _append_unique_amount_entity(
    entities: list[dict[str, str]],
    seen_digit_signatures: set[str],
    token: str,
) -> None:
    candidate = _compact_amount_candidate(token)
    signature = _amount_value_signature(candidate)
    if not signature or signature in seen_digit_signatures or not _is_probable_table_amount_token(candidate):
        return
    seen_digit_signatures.add(signature)
    entities.append({"type": "AMOUNT", "text": candidate, "source": "table_semantic"})


def _is_standalone_amount_ocr_block(text: str) -> bool:
    """Return True when an OCR block is essentially one amount value."""
    compact = _compact_amount_candidate(text)
    if not compact:
        return False
    allowed = set("0123456789.,，￥¥$€£-()（）[] ")
    if any(ch not in allowed for ch in compact):
        return False
    digits = _amount_digit_count(compact)
    if digits < _STANDALONE_AMOUNT_MIN_DIGITS or digits > _STANDALONE_AMOUNT_MAX_DIGITS:
        return False
    return bool(_amount_value_signature(compact))


def _augment_amount_entities_from_ocr(
    entities: list[dict[str, str]],
    ocr_blocks: list[OCRTextBlock],
    selected_type_ids: list[str],
) -> list[dict[str, str]]:
    """Recover table amount cells from structural table context.

    HaS Text owns semantic classification for running text. Table cells are
    different: the amount semantics often live in the column header while the
    data cell itself is only a number. Use OCR geometry plus table headers/total
    rows to add those cells back without scanning arbitrary page numbers.
    """
    if "AMOUNT" not in selected_type_ids:
        return entities

    seen_digit_signatures = {
        signature
        for entity in entities
        if _canonical_image_text_type(entity.get("type")) == "AMOUNT"
        for signature in [_amount_value_signature(str(entity.get("text", "")))]
        if signature
    }
    augmented = list(entities)

    rows = _group_blocks_into_visual_rows(ocr_blocks)
    amount_columns = _amount_table_column_ranges(rows)
    if not amount_columns and not any(
        _has_any_compact_keyword(" ".join(block.text for block in row), _AMOUNT_TABLE_ROW_KEYWORDS)
        for row in rows
    ):
        return entities

    for block in ocr_blocks:
        if not amount_columns or not _is_in_amount_semantic_column(block, amount_columns):
            continue
        for token in _iter_probable_amount_tokens(str(block.text or "")):
            before = len(augmented)
            _append_unique_amount_entity(augmented, seen_digit_signatures, token)
            if len(augmented) > before:
                logger.debug("Table semantic amount column recalled: %s", token)

    for row in rows:
        row_text = " ".join(block.text for block in row)
        if not _has_any_compact_keyword(row_text, _AMOUNT_TABLE_ROW_KEYWORDS):
            continue
        for block in row:
            for token in _iter_probable_amount_tokens(str(block.text or "")):
                before = len(augmented)
                _append_unique_amount_entity(augmented, seen_digit_signatures, token)
                if len(augmented) > before:
                    logger.debug("Table semantic amount row recalled: %s", token)

    return augmented


_PERSON_FIELD_LABELS = ("姓名", "患者姓名", "病人姓名")
_PERSON_FIELD_STOP_LABELS = (
    "性别",
    "年龄",
    "年",
    "床号",
    "住院号",
    "登记号",
    "科别",
    "病区",
    "日期",
    "时间",
)


def _is_person_value_char(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff" or ch.isalpha() or ch in "·.-"


def _looks_like_next_short_form_label(raw: str, cursor: int, chars: list[str]) -> bool:
    if _char_visual_units("".join(chars)) < _PERSON_FIELD_MIN_PREFIX_UNITS:
        return False
    window = raw[cursor : cursor + _PERSON_FIELD_LABEL_LOOKAHEAD_CHARS]
    for offset, ch in enumerate(window):
        if ch not in _FORM_FIELD_DELIMITERS:
            continue
        if offset <= 0:
            return False
        label = window[:offset]
        if not all(("\u4e00" <= item <= "\u9fff") or item.isalpha() for item in label):
            return False
        return offset <= _PERSON_FIELD_SHORT_LABEL_MAX_OFFSET or _char_visual_units("".join(chars)) >= _PERSON_FIELD_LONG_PREFIX_UNITS
    return False


def _iter_person_form_field_values(text: str) -> list[str]:
    values: list[str] = []
    raw = str(text or "")
    if not raw:
        return values

    for label in _PERSON_FIELD_LABELS:
        search_from = 0
        while True:
            label_pos = raw.find(label, search_from)
            if label_pos < 0:
                break
            cursor = label_pos + len(label)
            while cursor < len(raw) and raw[cursor].isspace():
                cursor += 1
            if cursor >= len(raw) or raw[cursor] not in _FORM_FIELD_DELIMITERS:
                search_from = label_pos + len(label)
                continue
            cursor += 1
            while cursor < len(raw) and raw[cursor].isspace():
                cursor += 1

            chars: list[str] = []
            while cursor < len(raw):
                if any(raw.startswith(stop_label, cursor) for stop_label in _PERSON_FIELD_STOP_LABELS):
                    break
                if _looks_like_next_short_form_label(raw, cursor, chars):
                    break
                ch = raw[cursor]
                if ch.isspace() or ch in _FORM_FIELD_DELIMITERS:
                    break
                if not _is_person_value_char(ch):
                    break
                chars.append(ch)
                cursor += 1
                if _char_visual_units("".join(chars)) > _PERSON_FIELD_VALUE_MAX_UNITS:
                    break
            value = "".join(chars).strip("路銉?- ")
            if _PERSON_FIELD_VALUE_MIN_UNITS <= _char_visual_units(value) <= _PERSON_FIELD_VALUE_MAX_UNITS and value not in values:
                values.append(value)
            search_from = max(cursor, label_pos + len(label))
    return values


def _is_loose_person_form_expansion(candidate: str, value: str) -> bool:
    if not candidate or not value or candidate == value:
        return False
    if not candidate.startswith(value):
        return False
    suffix = candidate[len(value) :]
    if len(suffix) > _PERSON_FORM_EXPANSION_MAX_SUFFIX:
        return False
    if suffix and all(ch == value[-1] for ch in suffix):
        return True
    return any(label.startswith(suffix) or suffix.startswith(label) for label in _PERSON_FIELD_STOP_LABELS)


def _ocr_block_area(block: OCRTextBlock) -> int:
    return max(1, int(block.width)) * max(1, int(block.height))


def _ocr_block_smaller_overlap(left: OCRTextBlock, right: OCRTextBlock) -> float:
    x1 = max(int(left.left), int(right.left))
    y1 = max(int(left.top), int(right.top))
    x2 = min(int(left.left + left.width), int(right.left + right.width))
    y2 = min(int(left.top + left.height), int(right.top + right.height))
    if x2 <= x1 or y2 <= y1:
        return 0.0
    overlap = (x2 - x1) * (y2 - y1)
    return overlap / max(1, min(_ocr_block_area(left), _ocr_block_area(right)))


def _person_form_field_quality(block: OCRTextBlock, value: str) -> tuple[int, int, int]:
    compact_text = _compact_text(block.text)
    anchor_score = 0
    for label in _PERSON_FIELD_LABELS:
        if label and label in compact_text:
            anchor_score += _PERSON_FIELD_ANCHOR_WEIGHT
    trailing_field_penalty = 0
    for label in _PERSON_FIELD_STOP_LABELS:
        if label and label in compact_text:
            trailing_field_penalty += _PERSON_FIELD_TRAILING_PENALTY
    delimiter_score = min(
        _PERSON_FIELD_MAX_DELIMITER_SCORE,
        sum(1 for ch in str(block.text or "") if ch in _FORM_FIELD_DELIMITERS),
    )
    odd_penalty = sum(1 for ch in value if ch in "'`\"?？")
    return (
        anchor_score + delimiter_score - trailing_field_penalty - odd_penalty * _PERSON_FIELD_ODD_CHAR_PENALTY,
        -_ocr_block_area(block),
        len(value),
    )


def _rank_person_form_field_candidates(
    ocr_blocks: list[OCRTextBlock],
) -> list[tuple[str, OCRTextBlock]]:
    candidates: list[tuple[str, OCRTextBlock, tuple[int, int, int]]] = []
    for block in ocr_blocks:
        for value in _iter_person_form_field_values(str(block.text or "")):
            candidates.append((value, block, _person_form_field_quality(block, value)))

    selected: list[tuple[str, OCRTextBlock]] = []
    selected_blocks: list[OCRTextBlock] = []
    for value, block, _quality in sorted(candidates, key=lambda item: item[2], reverse=True):
        if any(_ocr_block_smaller_overlap(block, existing) >= _PERSON_FIELD_OVERLAP_DROP_RATIO for existing in selected_blocks):
            continue
        selected.append((value, block))
        selected_blocks.append(block)
    return selected


def _augment_person_entities_from_ocr_form_fields(
    entities: list[dict[str, str]],
    ocr_blocks: list[OCRTextBlock],
    selected_type_ids: list[str],
) -> list[dict[str, str]]:
    """Recover compact form names from OCR labels such as 姓名: before matching."""
    if "PERSON" not in selected_type_ids:
        return entities
    augmented = list(entities)
    seen = {
        _compact_text(entity.get("text", ""))
        for entity in augmented
        if _canonical_image_text_type(entity.get("type")) == "PERSON"
    }
    for value, _block in _rank_person_form_field_candidates(ocr_blocks):
        compact = _compact_text(value)
        if not compact or compact in seen:
            continue
        augmented = [
            entity
            for entity in augmented
            if not (
                _canonical_image_text_type(entity.get("type")) == "PERSON"
                and _is_loose_person_form_expansion(_compact_text(entity.get("text", "")), compact)
            )
        ]
        seen.add(compact)
        augmented.append({"type": "PERSON", "text": value, "source": "form_field_ocr"})
        logger.debug("Form field person recalled from OCR: %s", value)
    return augmented


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
    inflight.event.wait()
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
    pixels = list(gray.getdata())
    total = len(pixels)
    if total == 0:
        return True, 0.0, 0.0

    dark_pixels = sum(1 for value in pixels if value < _BLANK_PAGE_DARK_PIXEL_MAX)
    ink_pixels = sum(1 for value in pixels if value < _BLANK_PAGE_INK_PIXEL_MAX)
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
    table_like = _looks_like_table(image) if adaptive_mode else False
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
            if needs_text_precision and bool(settings.OCR_STRUCTURE_PRIMARY_SUPPLEMENT_VL):
                logger.info(
                    "PP-StructureV3 primary OCR found %d blocks; retaining PaddleOCR-VL supplement for text-coordinate fusion",
                    len(primary_structure_blocks),
                )
            elif needs_ocr_visual_regions and not primary_structure_visual_regions:
                logger.info(
                    "PP-StructureV3 primary OCR found %d blocks but no visual regions; retaining PaddleOCR-VL visual supplement",
                    len(primary_structure_blocks),
                )
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
                        table_like,
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
            or (adaptive_mode and table_like and needs_table_precision)
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
    pixels = gray.load()
    horizontal = 0
    vertical = 0
    for y in range(height):
        dark = sum(1 for x in range(width) if pixels[x, y] < _TABLE_HEURISTIC_DARK_PIXEL_MAX)
        if dark / width > _TABLE_HEURISTIC_HORIZONTAL_DARK_RATIO:
            horizontal += 1
    for x in range(width):
        dark = sum(1 for y in range(height) if pixels[x, y] < _TABLE_HEURISTIC_DARK_PIXEL_MAX)
        if dark / height > _TABLE_HEURISTIC_VERTICAL_DARK_RATIO:
            vertical += 1
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
        blocks.append(OCRTextBlock(
            text=text,
            polygon=[[left, top], [right, top], [right, bottom], [left, bottom]],
            confidence=float(getattr(item, "confidence", _DEFAULT_OCR_ITEM_CONFIDENCE) or _DEFAULT_OCR_ITEM_CONFIDENCE),
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


def _merge_ocr_blocks(primary: list[OCRTextBlock], extra: list[OCRTextBlock]) -> list[OCRTextBlock]:
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

    for block in extra:
        if _is_coarse_markup_block(block):
            continue
        compact = _compact_text(block.text)
        duplicate = False
        for existing in merged:
            overlap = iou(block, existing)
            if compact and compact == _compact_text(existing.text) and overlap > _MERGE_DUPLICATE_IOU:
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


def _is_red_stamp_pixel(r: int, g: int, b: int) -> bool:
    return (
        r >= _RED_STAMP_MIN_RED
        and r - g >= _RED_STAMP_RED_MINUS_GREEN
        and r - b >= _RED_STAMP_RED_MINUS_BLUE
        and g <= max(_RED_STAMP_OTHER_CHANNEL_FLOOR, int(r * _RED_STAMP_OTHER_CHANNEL_RATIO))
        and b <= max(_RED_STAMP_OTHER_CHANNEL_FLOOR, int(r * _RED_STAMP_OTHER_CHANNEL_RATIO))
    )


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
    pixels = crop.load()

    red_rows: list[int] = []
    for y in range(height):
        count = 0
        for x in range(width):
            if _is_red_stamp_pixel(*pixels[x, y]):
                count += 1
        red_rows.append(count)

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
        red_xs: list[int] = []
        red_ys: list[int] = []
        y_start = max(0, band_start - radius)
        y_end = min(height - 1, band_end + radius)
        for y in range(y_start, y_end + 1):
            for x in range(width):
                if _is_red_stamp_pixel(*pixels[x, y]):
                    red_xs.append(x)
                    red_ys.append(y)
        if not red_xs:
            continue
        bx1, bx2 = min(red_xs), max(red_xs)
        by1, by2 = min(red_ys), max(red_ys)
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
    _finish_ocr_output_inflight(cache_key, inflight, (blocks, visual_regions))
    _record_ocr_stage_duration(stage_status, "vl", stage_start)
    return blocks, visual_regions


# ---------------------------------------------------------------------------
# HTML table expansion
# ---------------------------------------------------------------------------

def extract_table_cells(table_html: str, block: OCRTextBlock) -> list[OCRTextBlock]:
    """
    Parse an HTML table and create virtual OCRTextBlock per cell.

    Cell positions are estimated from row/column indices and the parent block's
    bounding box.
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
    num_cols = 0
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
            num_cols = max(num_cols, col_idx + col_span)
            col_idx += col_span

    num_rows = max((row for row, _ in occupied), default=len(rows) - 1) + 1
    if num_rows == 0 or num_cols == 0:
        return []

    row_height = max(block.height / num_rows, 1.0)
    col_width = max(block.width / num_cols, 1.0)

    virtual_blocks: list[OCRTextBlock] = []
    for cell_text, r_idx, col_idx, row_span, col_span in placements:
        if cell_text.strip():
            cell_left = block.left + col_idx * col_width
            cell_top = block.top + r_idx * row_height
            cell_width = col_width * col_span
            cell_height = row_height * row_span

            virtual_blocks.append(OCRTextBlock(
                text=cell_text,
                polygon=[
                    [cell_left, cell_top],
                    [cell_left + cell_width, cell_top],
                    [cell_left + cell_width, cell_top + cell_height],
                    [cell_left, cell_top + cell_height],
                ],
                confidence=block.confidence * _TABLE_CELL_CONFIDENCE_FACTOR,
            ))

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
            return []

    if _has_recent_negative_health(has_client):
        logger.warning("HaS service recently reported unavailable, skipping NER")
        _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_recent_unavailable")
        _record_has_text_metric(
            stage_status,
            "has_text_total_ms",
            round((time.perf_counter() - total_start) * 1000),
        )
        return []

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
            return []

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
            return []

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
                return []
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
                    # HaS httpx is synchronous - offload to a worker thread. Keep local
                    # HaS Text calls serialized so scanned-PDF page concurrency does not
                    # amplify cold-start and queue latency inside llama.cpp.
                    lock = _get_has_text_ner_lock()
                    queue_start = time.perf_counter()
                    async with lock:
                        queue_ms = round((time.perf_counter() - queue_start) * 1000)
                        _add_has_text_duration(stage_status, "has_text_slot_wait_ms", queue_ms)
                        if queue_ms > 0:
                            logger.info("HaS Text waited %dms for local NER slot", queue_ms)
                        ner_result = _get_cached_has_text_ner(has_client, text_content, chinese_types)
                        if ner_result is not None:
                            _record_has_text_metric(stage_status, "has_text_cache_status", "hit_after_slot")
                            logger.info("HaS NER cache hit after local slot wait")
                        else:
                            model_start = time.perf_counter()
                            from app.core.gpu_inference_gate import shared_gpu_inference_slot

                            async with shared_gpu_inference_slot("OCR HaS Text NER"):
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
            _record_has_text_metric(stage_status, "has_text_entity_count", 0)
            _record_has_text_metric(
                stage_status,
                "has_text_total_ms",
                round((time.perf_counter() - total_start) * 1000),
            )
            return []

        logger.info("HaS NER result: %s", ner_result)

        # ----- reverse mapping: Chinese -> type ID -----
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
        else:
            chinese_to_id = {
                TYPE_ID_TO_CN.get(type_id, type_id): type_id
                for type_id in DEFAULT_HAS_TEXT_TYPE_IDS
            }

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
                    lock = _get_has_text_ner_lock()
                    async with lock:
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
                if len(text) < min_len:
                    logger.debug("HaS skipped too short: '%s' (%s)", text, normalized_type)
                    continue

                entities.append({
                    "type": normalized_type,
                    "text": text,
                })
                logger.debug("HaS found entity: %s (%s)", text, normalized_type)

        entities = _augment_person_entities_from_ocr_form_fields(entities, candidate_blocks, selected_type_ids)
        entities = _augment_amount_entities_from_ocr(entities, candidate_blocks, selected_type_ids)
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
        return []


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


def _char_unit(ch: str) -> float:
    return _char_visual_units(ch)


_FORM_FIELD_DELIMITERS = frozenset(":：")


def _is_form_label_char(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff" or ch.isalpha()


def _form_field_marker_before_entity(line_text: str, start_pos: int) -> str | None:
    if start_pos <= 0:
        return None
    prefix = line_text[:start_pos].rstrip()
    if not prefix or prefix[-1] not in _FORM_FIELD_DELIMITERS:
        return None
    label_end = len(prefix) - 1
    label_start = label_end
    while label_start > 0 and _is_form_label_char(prefix[label_start - 1]):
        label_start -= 1
    label = prefix[label_start:label_end]
    if not label:
        return None
    if _char_visual_units(label) > _FORM_LABEL_MAX_UNITS:
        return None
    return prefix[label_start:]


def _looks_like_compact_form_row(line_text: str, block: OCRTextBlock, line_height: int) -> bool:
    if block.width <= max(1, line_height) * _FORM_ROW_MIN_WIDTH_HEIGHT_MULT:
        return False
    return sum(1 for ch in str(line_text or "") if ch in _FORM_FIELD_DELIMITERS) >= _FORM_ROW_MIN_DELIMITERS


def _field_value_width_cap(entity_text: str, line_height: int, pad_x: int) -> int:
    return int(_char_visual_units(entity_text) * max(_FIELD_VALUE_WIDTH_MIN_HEIGHT_PX, line_height * _FIELD_VALUE_WIDTH_HEIGHT_RATIO)) + pad_x * 2


def _find_wrap_break(text: str, start: int, estimated: int) -> int:
    """Choose a natural visual-wrap boundary near an estimated character index."""
    if not text:
        return start
    lo = max(start + 1, estimated - _WRAP_BREAK_SEARCH_WINDOW)
    hi = min(len(text) - 1, estimated + _WRAP_BREAK_SEARCH_WINDOW)
    if lo > hi:
        return max(start + 1, min(len(text) - 1, estimated))

    # Prefer punctuation after the mark, then currency/digit starts. This keeps
    # amounts and identifiers intact when a long OCR row was visually wrapped.
    punctuation = "，。;；、：:)]）】"
    amount_prefixes = "￥¥$€£"
    best: tuple[int, int] | None = None
    for idx in range(lo, hi + 1):
        ch = text[idx]
        score = 0
        break_after = True
        if ch in punctuation:
            score = _WRAP_BREAK_SCORE_PUNCT
        elif ch in amount_prefixes and idx > start:
            score = _WRAP_BREAK_SCORE_AMOUNT_PREFIX
            break_after = False
        elif ch.isdigit() and idx > start and text[idx - 1] in amount_prefixes:
            score = _WRAP_BREAK_SCORE_AMOUNT_DIGIT
            break_after = False
        elif ch.isspace():
            score = _WRAP_BREAK_SCORE_SPACE
        if score:
            distance = abs(idx - estimated)
            candidate = idx + 1 if break_after else idx
            if candidate <= start:
                continue
            ranked = (score - distance, candidate)
            if best is None or ranked > best:
                best = ranked
    if best is not None:
        return min(len(text), max(start + 1, best[1]))

    candidate = max(start + 1, min(len(text), estimated))
    while candidate < len(text) and text[candidate - 1].isdigit() and text[candidate].isdigit():
        candidate += 1
    return min(len(text), candidate)


def _split_visual_lines(text: str, line_count: int) -> list[tuple[int, int, str]]:
    if line_count <= 1 or not text:
        return [(0, len(text), text)]
    total_units = _char_visual_units(text)
    target_units = total_units / line_count
    segments: list[tuple[int, int, str]] = []
    start = 0
    acc = 0.0
    next_target = target_units

    for idx, ch in enumerate(text):
        acc += _char_unit(ch)
        if len(segments) >= line_count - 1:
            break
        if acc >= next_target:
            end = _find_wrap_break(text, start, idx)
            segments.append((start, end, text[start:end]))
            start = end
            next_target = target_units * (len(segments) + 1)

    if start < len(text):
        segments.append((start, len(text), text[start:]))
    return [seg for seg in segments if seg[2]]


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


def _estimate_entity_region(
    block: OCRTextBlock,
    entity_text: str,
    typical_line_height: int | None = None,
    occurrence_start: int | None = None,
) -> tuple[int, int, int, int]:
    """
    Estimate a sub-box inside an OCR block for an exact text hit.

    PaddleOCR-VL often returns a whole form row or paragraph as one block. Using
    the entire OCR block for each entity makes the review screen look
    over-detected, so split by visual lines first and then estimate x by the
    entity's character position in that line.
    """
    block_text = block.text or ""
    explicit_lines = [line for line in block_text.splitlines() if line.strip()]
    lines = explicit_lines or [block_text]
    compressed_explicit_lines = (
        len(explicit_lines) > 1
        and typical_line_height is not None
        and block.height < typical_line_height * max(_COMPRESSED_LINES_MIN_HEIGHT_MULT, len(explicit_lines) * _COMPRESSED_LINES_PER_LINE_MULT)
    )

    line_index = 0
    line_text = block_text
    start_pos = occurrence_start if occurrence_start is not None else block_text.find(entity_text)

    line_count = 1 if compressed_explicit_lines else max(len(lines), 1)
    if line_count == 1 and typical_line_height and block.height > typical_line_height * _MULTILINE_SPLIT_HEIGHT_MULT:
        visual_line_height = max(1, int(typical_line_height * _VISUAL_LINE_HEIGHT_MULT))
        line_count = max(2, round(block.height / visual_line_height))
        visual_lines = _split_visual_lines(block_text, line_count)
        absolute_start = max(start_pos, 0)
        for idx, (seg_start, _seg_end, seg_text) in enumerate(visual_lines):
            relative_pos = seg_text.find(entity_text)
            if relative_pos >= 0:
                line_index = idx
                line_text = seg_text
                start_pos = relative_pos
                break
            if seg_start <= absolute_start:
                line_index = idx
                line_text = seg_text
                start_pos = max(0, absolute_start - seg_start)
    else:
        absolute_cursor = 0
        for idx, line in enumerate(lines):
            line_start = block_text.find(line, absolute_cursor)
            if line_start < 0:
                line_start = absolute_cursor
            line_end = line_start + len(line)
            absolute_cursor = line_end
            if occurrence_start is not None and line_start <= occurrence_start <= line_end:
                line_index = idx
                line_text = line
                start_pos = max(0, occurrence_start - line_start)
                break
            pos = line.find(entity_text)
            if pos >= 0:
                line_index = idx
                line_text = line
                start_pos = pos
                break
    if compressed_explicit_lines:
        line_index = 0

    line_top = block.top + int(block.height * line_index / line_count)
    next_line_top = block.top + int(block.height * (line_index + 1) / line_count)
    line_height = max(1, next_line_top - line_top)
    if typical_line_height:
        capped_height = max(1, int(typical_line_height * _LINE_HEIGHT_CAP_MULT))
        if line_height > capped_height:
            line_top += max(0, (line_height - capped_height) // 2)
            line_height = capped_height

    start_pos = max(start_pos, 0)
    before_text = line_text[:start_pos]
    text_units = _char_visual_units(line_text)
    before_units = _char_visual_units(before_text) if before_text else 0.0
    entity_units = _char_visual_units(entity_text)
    start_ratio = max(0.0, min(before_units / text_units, _ENTITY_REGION_START_RATIO_CLAMP))
    width_ratio = max(entity_units / text_units, _ENTITY_REGION_WIDTH_RATIO_FLOOR)

    pad_x = max(_ENTITY_REGION_PAD_X_MIN, int(block.width * _ENTITY_REGION_PAD_X_RATIO))
    sub_left = int(block.left + start_ratio * block.width) - pad_x
    sub_width = int(width_ratio * block.width) + pad_x * 2
    min_width = min(block.width, max(_ENTITY_REGION_MIN_WIDTH_FLOOR, len(entity_text) * _ENTITY_REGION_MIN_WIDTH_PER_CHAR))

    field_marker = _form_field_marker_before_entity(line_text, start_pos)
    if field_marker and _looks_like_compact_form_row(line_text, block, line_height):
        # start_pos is already after the compact form label (for example
        # "姓名:"). Keep the exact text anchor and only cap the value width,
        # otherwise short values drift into the following field.
        sub_width = min(sub_width, max(min_width, _field_value_width_cap(entity_text, line_height, pad_x)))

    sub_left = max(block.left, sub_left)
    sub_width = max(min_width, sub_width)
    if sub_left + sub_width > block.left + block.width:
        sub_width = max(1, block.left + block.width - sub_left)

    return sub_left, line_top, sub_width, line_height


def _dedupe_ocr_regions(regions: list[SensitiveRegion]) -> list[SensitiveRegion]:
    """Drop duplicate OCR matches that point at the same visual box/text."""
    priority = _DEDUPE_PRIORITY
    chosen: dict[tuple, SensitiveRegion] = {}
    for region in regions:
        key = (
            region.left // _DEDUPE_BUCKET_PX,
            region.top // _DEDUPE_BUCKET_PX,
            region.width // _DEDUPE_BUCKET_PX,
            region.height // _DEDUPE_BUCKET_PX,
            _compact_text(region.text),
        )
        existing = chosen.get(key)
        if existing is None:
            chosen[key] = region
            continue
        if priority.get(region.entity_type, 1) > priority.get(existing.entity_type, 1):
            chosen[key] = region

    def overlap_ratio(a: SensitiveRegion, b: SensitiveRegion) -> float:
        x1 = max(a.left, b.left)
        y1 = max(a.top, b.top)
        x2 = min(a.left + a.width, b.left + b.width)
        y2 = min(a.top + a.height, b.top + b.height)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        inter = (x2 - x1) * (y2 - y1)
        smaller = max(1, min(a.width * a.height, b.width * b.height))
        return inter / smaller

    def vertical_overlap_ratio(a: SensitiveRegion, b: SensitiveRegion) -> float:
        y1 = max(a.top, b.top)
        y2 = min(a.top + a.height, b.top + b.height)
        if y2 <= y1:
            return 0.0
        return (y2 - y1) / max(1, min(a.height, b.height))

    def region_rank(region: SensitiveRegion) -> tuple[int, int, int, int]:
        source = str(region.source or "").lower()
        source_rank = (
            _DEDUPE_SOURCE_RANK_FORM_FIELD
            if "form_field_ocr" in source
            else _DEDUPE_SOURCE_RANK_TEXT_MATCH
            if "text_match" in source
            else _DEDUPE_SOURCE_RANK_VISUAL_TABLE
            if "visual_line" in source or "table" in source
            else 0
        )
        area = max(1, region.width * region.height)
        text = _compact_text(region.text)
        if region.entity_type == "PERSON":
            return (source_rank, priority.get(region.entity_type, 1), len(text), -area)
        return (source_rank, priority.get(region.entity_type, 1), -area, len(text))

    same_line_dedupe_types = {
        "PERSON",
        "AGE",
        "GENDER",
        "DATE",
        "TIME",
        "BIRTH_DATE",
        "INSTITUTION_NAME",
        "COMPANY_NAME",
        "GOVERNMENT_AGENCY",
        "WORK_UNIT",
        "DEPARTMENT_NAME",
        "PROJECT_NAME",
        "CASE_NUMBER",
    }

    def same_text_line_duplicate(a: SensitiveRegion, b: SensitiveRegion) -> bool:
        if a.entity_type != b.entity_type:
            return False
        if a.entity_type not in same_line_dedupe_types:
            return False
        text = _compact_text(a.text)
        if not text or text != _compact_text(b.text):
            return False
        if vertical_overlap_ratio(a, b) < _DEDUPE_SAME_LINE_VERTICAL_OVERLAP:
            return False
        if overlap_ratio(a, b) >= _DEDUPE_SAME_LINE_BOX_OVERLAP:
            return True
        # No box overlap: a same-text pair on one line is only an OCR split of a
        # SINGLE value when the boxes are horizontally adjacent. Two same-text
        # boxes far apart on the same line are DISTINCT occurrences (e.g. the same
        # date printed under both 甲方 and 乙方) and must each be redacted.
        horizontal_gap = max(a.left, b.left) - min(a.left + a.width, b.left + b.width)
        if horizontal_gap > _DEDUPE_SAME_LINE_HORIZONTAL_GAP_RATIO * max(a.width, b.width):
            return False
        short_value = _char_visual_units(text) <= _DEDUPE_SHORT_VALUE_MAX_UNITS
        same_center_line = abs((a.top + a.height / 2) - (b.top + b.height / 2)) <= max(a.height, b.height) * _DEDUPE_SAME_CENTER_HEIGHT_RATIO
        if short_value and same_center_line:
            return True
        return _char_visual_units(text) >= _DEDUPE_LONG_VALUE_MIN_UNITS and same_center_line

    deduped: list[SensitiveRegion] = []
    for region in sorted(
        chosen.values(),
        key=lambda r: (
            priority.get(r.entity_type, 1),
            len(_compact_text(r.text)),
            r.confidence,
        ),
        reverse=True,
    ):
        region_text = _compact_text(region.text)
        duplicate_index: int | None = None
        for index, existing in enumerate(deduped):
            duplicate = (
                (
                    region_text == _compact_text(existing.text)
                    or (
                        region.entity_type == existing.entity_type
                        and region_text
                        and _compact_text(existing.text).startswith(region_text)
                    )
                )
                and overlap_ratio(region, existing) >= (_DEDUPE_AMOUNT_OVERLAP_DUP if region.entity_type == "AMOUNT" else _DEDUPE_DEFAULT_OVERLAP_DUP)
            ) or same_text_line_duplicate(region, existing)
            if duplicate:
                duplicate_index = index
                break
        if duplicate_index is None:
            deduped.append(region)
        elif region_rank(region) > region_rank(deduped[duplicate_index]):
            deduped[duplicate_index] = region
    return _filter_amount_coordinate_conflicts(deduped)


def _amount_region_value(region: SensitiveRegion) -> int:
    signature = _amount_value_signature(region.text)
    try:
        return int(signature or "0")
    except ValueError:
        return 0


def _filter_amount_coordinate_conflicts(regions: list[SensitiveRegion]) -> list[SensitiveRegion]:
    amounts = [region for region in regions if region.entity_type == "AMOUNT"]
    if len(amounts) < _AMOUNT_CONFLICT_MIN_AMOUNTS:
        return regions

    numeric_amounts = [region for region in amounts if _amount_region_value(region) > 0]
    if len(numeric_amounts) < _AMOUNT_CONFLICT_MIN_AMOUNTS:
        return regions

    centers = sorted(
        ((region.left + region.width / 2, index, region) for index, region in enumerate(numeric_amounts)),
        key=lambda item: (item[0], item[1]),
    )
    column_clusters: list[list[SensitiveRegion]] = []
    for center, _index, region in centers:
        if not column_clusters:
            column_clusters.append([region])
            continue
        cluster_center = sum(item.left + item.width / 2 for item in column_clusters[-1]) / len(column_clusters[-1])
        if abs(center - cluster_center) <= _AMOUNT_COLUMN_CLUSTER_TOLERANCE_PX:
            column_clusters[-1].append(region)
        else:
            column_clusters.append([region])
    dominant_columns = [
        sum(item.left + item.width / 2 for item in cluster) / len(cluster)
        for cluster in column_clusters
        if len(cluster) >= _AMOUNT_COLUMN_DOMINANT_MIN_CLUSTER
    ]

    def near_dominant_column(region: SensitiveRegion) -> bool:
        center = region.left + region.width / 2
        return any(abs(center - column) <= _AMOUNT_COLUMN_CLUSTER_TOLERANCE_PX for column in dominant_columns)

    keep_ids = {id(region) for region in regions}
    by_value: dict[str, list[SensitiveRegion]] = {}
    for region in numeric_amounts:
        signature = _amount_value_signature(region.text)
        if signature:
            by_value.setdefault(signature, []).append(region)
    for same_value_regions in by_value.values():
        if len(same_value_regions) <= 1:
            continue
        aligned = [region for region in same_value_regions if near_dominant_column(region)]
        if aligned:
            aligned_ids = {id(region) for region in aligned}
            for region in same_value_regions:
                if id(region) not in aligned_ids:
                    keep_ids.discard(id(region))

    def smaller_overlap(a: SensitiveRegion, b: SensitiveRegion) -> float:
        x1 = max(a.left, b.left)
        y1 = max(a.top, b.top)
        x2 = min(a.left + a.width, b.left + b.width)
        y2 = min(a.top + a.height, b.top + b.height)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        inter = (x2 - x1) * (y2 - y1)
        return inter / max(1, min(a.width * a.height, b.width * b.height))

    remaining_amounts = [region for region in numeric_amounts if id(region) in keep_ids]
    for index, region in enumerate(remaining_amounts):
        if id(region) not in keep_ids:
            continue
        conflicts = [
            other
            for other in remaining_amounts[index + 1 :]
            if id(other) in keep_ids
            and _amount_value_signature(other.text) != _amount_value_signature(region.text)
            and smaller_overlap(region, other) >= _AMOUNT_CONFLICT_OVERLAP_MIN
        ]
        if not conflicts:
            continue
        cluster = [region, *conflicts]
        winner = max(cluster, key=lambda item: (_amount_region_value(item), item.confidence))
        for item in cluster:
            if item is not winner:
                keep_ids.discard(id(item))

    return [region for region in regions if id(region) in keep_ids]


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
    reconstructed_blocks = reconstruct_visual_line_blocks(expanded_blocks)
    reconstructed_block_ids = {id(block) for block in reconstructed_blocks}
    expanded_blocks.extend(reconstructed_blocks)
    typical_line_height = _infer_typical_textline_height(expanded_blocks)
    standalone_amount_signatures = {
        signature
        for block in expanded_blocks
        if id(block) not in table_virtual_block_ids and _is_standalone_amount_ocr_block(block.text)
        for signature in [_amount_value_signature(block.text)]
        if signature
    }

    for entity in entities:
        entity_text = entity.get("text", "").strip()
        entity_type = entity.get("type", "UNKNOWN")
        entity_source = str(entity.get("source") or "").strip()

        if not entity_text:
            continue

        type_mapping = {
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
        normalized_type = _canonical_image_text_type(type_mapping.get(entity_type, entity_type.upper()))

        if _is_low_signal_vision_entity(normalized_type, entity_text):
            logger.debug("HaS skipped low-signal vision entity: '%s' (%s)", entity_text, normalized_type)
            continue

        matched = False

        direct_amount_signatures: set[str] = set()
        ordered_blocks = sorted(expanded_blocks, key=lambda item: id(item) in table_virtual_block_ids)
        for block in ordered_blocks:
            block_text = block.text

            if block_text.startswith("<table"):
                continue

            # Exact containment match
            if entity_text in block_text:
                contextual_type = _entity_type_from_block_context(normalized_type, entity_text, block_text)
                if contextual_type is None:
                    continue
                search_from = 0
                while True:
                    occurrence_start = block_text.find(entity_text, search_from)
                    if occurrence_start < 0:
                        break
                    visual_text, visual_occurrence_start = _visual_match_span_for_entity(
                        contextual_type,
                        block_text,
                        entity_text,
                        occurrence_start,
                    )
                    is_table_virtual = id(block) in table_virtual_block_ids
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
                    sub_left, sub_top, sub_width, sub_height = _estimate_entity_region(
                        block,
                        visual_text,
                        typical_line_height,
                        occurrence_start=visual_occurrence_start,
                    )
                    if contextual_type in {"PHONE", "ID_CARD", "BANK_ACCOUNT", "BANK_CARD", "DATE", "PERSON"}:
                        token_cap = max(_TOKEN_CAP_MIN_PX, int(_char_visual_units(visual_text) * max(_TOKEN_CAP_HEIGHT_FLOOR, sub_height * _TOKEN_CAP_HEIGHT_RATIO)))
                        sub_width = min(sub_width, token_cap)
                    elif contextual_type == "AMOUNT" and "大写" not in visual_text and "小写" not in visual_text:
                        height_factor = _AMOUNT_TOKEN_CAP_PERCENT_HEIGHT_RATIO if _is_percent_value_text(visual_text) else _AMOUNT_TOKEN_CAP_HEIGHT_RATIO
                        token_cap = max(_AMOUNT_TOKEN_CAP_MIN_PX, int(_char_visual_units(visual_text) * max(_TOKEN_CAP_HEIGHT_FLOOR, sub_height * height_factor)))
                        sub_width = min(sub_width, token_cap)

                    regions.append(SensitiveRegion(
                        text=visual_text,
                        entity_type=contextual_type,
                        left=sub_left,
                        top=sub_top,
                        width=sub_width,
                        height=sub_height,
                        confidence=1.0,
                        source=(
                            entity_source
                            if entity_source in {"table_semantic", "form_field_ocr"}
                            else
                            "table_cell_match"
                            if is_table_virtual
                            else "visual_line_match"
                            if id(block) in reconstructed_block_ids
                            else "text_match"
                        ),
                    ))
                    logger.debug(
                        "MATCH '%s' in '%s...' @ (%d, %d, %d, %d)",
                        entity_text, block_text[:20], sub_left, sub_top, sub_width, sub_height,
                    )
                    search_from = occurrence_start + max(1, len(entity_text))
                matched = True
                continue

            # Fuzzy match (handles minor OCR errors)
            elif not matched and len(entity_text) >= _FUZZY_MATCH_MIN_ENTITY_LEN and len(block_text) <= max(len(entity_text) * _FUZZY_MATCH_BLOCK_LEN_MULT, _FUZZY_MATCH_BLOCK_LEN_FLOOR) and (
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
        if not matched:
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
