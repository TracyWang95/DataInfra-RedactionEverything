"""Visual match-span selection for OCR↔entity matching.

Split out of ocr_entity_match.py (which re-exports these names and stays the
matching facade): choosing the visible span to place a redaction box on for a
semantic entity — RMB upper/lower amount pairs and document-title suffixes —
plus the char visual-unit width helper they share. Value-token narrowing
(人民币每亩每年100元 → 100元, 40% percents) is the model's job, upstream in
has_text_analysis._narrow_amount_entities.
"""
from __future__ import annotations

from app.services.vision.has_text_payload import _compact_text
from app.services.vision.ocr_tuning import (
    _AMOUNT_PAIR_LOOKBACK_CHARS,
    _AMOUNT_PAIR_MAX_LOWER_TAIL_UNITS,
    _AMOUNT_PAIR_NO_LOWER_MARKER_UNITS,
    _CHAR_UNIT_ALNUM,
    _CHAR_UNIT_CJK,
    _CHAR_UNIT_MIN_TOTAL,
    _CHAR_UNIT_OTHER,
    _CHAR_UNIT_PUNCT,
    _CHAR_UNIT_SPACE,
    _PROPERTY_TITLE_TAIL_LOOKAHEAD_CHARS,
)


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
    # Value-span narrowing lives upstream in the model now: HaS itself
    # extracts the bare value token from an AMOUNT span
    # (has_text_analysis._narrow_amount_entities) — no token grammar here.
    if entity_type == "AMOUNT":
        return _extend_amount_pair_for_visual_match(block_text, entity_text, occurrence_start)

    visual_text = _extend_entity_for_visual_match(
        entity_type,
        block_text,
        entity_text,
        occurrence_start,
    )
    return visual_text, occurrence_start


DOCUMENT_TITLE_SUFFIXES = {
    "合同",
    "协议",
    "清单",
    "方案",
    "报告",
    "通知",
    "函",
}


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
