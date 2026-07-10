"""Visual match-span selection for OCR↔entity matching.

Split out of ocr_entity_match.py (which re-exports these names and stays the
matching facade): choosing the visible span to place a redaction box on for a
semantic entity — percent tokens inside an amount phrase, RMB upper/lower
amount pairs, and document-title suffixes — plus the char visual-unit width
helper they share.
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


# Closed character classes for the currency value scanner — the same family
# as the percent scanner's '%': alphabet constants, not decision thresholds.
_CJK_NUMERALS = "〇零一二三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟两"
_CJK_MAGNITUDES = "十百千万亿"
_CURRENCY_UNITS = "元圆块"
_CURRENCY_PREFIXES = "￥¥$"


def _iter_currency_value_tokens(text: str) -> list[str]:
    """Currency value substrings（100元 / 十万元 / ￥3600000元 / 壹拾万圆整）,
    scanned without regular expressions like _iter_percent_value_tokens."""
    raw = str(text or "")
    tokens: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        start = i
        if raw[i] in _CURRENCY_PREFIXES:
            i += 1
        if i < n and raw[i].isdigit():
            while i < n and raw[i].isdigit():
                i += 1
            if i < n and raw[i] in ".．":
                decimal_end = i + 1
                while decimal_end < n and raw[decimal_end].isdigit():
                    decimal_end += 1
                if decimal_end > i + 1:
                    i = decimal_end
            while i < n and raw[i] in _CJK_MAGNITUDES:  # 100万元
                i += 1
        elif i < n and raw[i] in _CJK_NUMERALS:
            while i < n and raw[i] in _CJK_NUMERALS:
                i += 1
        else:
            i = start + 1
            continue
        if i < n and raw[i] in _CURRENCY_UNITS:
            i += 1
            if i < n and raw[i] == "整":
                i += 1
            tokens.append(raw[start:i])
        else:
            i = max(start + 1, i)
    return tokens


def _visual_match_text_for_entity(entity_type: str, entity_text: str) -> str:
    """Choose the visible span to place a box on for a semantic entity.

    Amounts are often returned by HaS with surrounding business context
    ("contract amount 40%", 人民币每亩每年100元, 保底十万元/每年左右). The
    sensitive ink on the page is the value token itself, so use that shorter
    visible span when available. Currency narrowing fires only when the
    entity holds exactly ONE value token — a multi-value entity keeps its
    whole span so no second value is ever uncovered.
    """
    if entity_type != "AMOUNT":
        return entity_text
    for token in _iter_percent_value_tokens(entity_text):
        if _compact_text(token) != _compact_text(entity_text):
            return token
    currency_tokens = _iter_currency_value_tokens(entity_text)
    if len(currency_tokens) == 1 and _compact_text(currency_tokens[0]) != _compact_text(entity_text):
        return currency_tokens[0]
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
