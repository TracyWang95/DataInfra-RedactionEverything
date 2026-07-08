"""Entity-to-OCR matching: attach detected values to OCR boxes.

Split out of ocr_pipeline.py (which stays the public facade): visual match
span selection (amount pairs, document-title suffixes), char-box-proven value
crops, chars-less paragraph narrowing, strict/isolated-token rules, fuzzy and
table fallbacks, and spatial region dedupe.
"""
from __future__ import annotations

import logging
import unicodedata
from difflib import SequenceMatcher

from app.services.ocr_has_vision_service import OCRTextBlock, SensitiveRegion
from app.services.vision.has_text_payload import (
    _canonical_image_text_type,
    _compact_text,
)
from app.services.vision.ocr_table_semantics import (
    _amount_value_signature,
    _block_search_text,
    _compact_amount_candidate,
    _is_standalone_amount_ocr_block,
    extract_table_cells,
)
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
    _FUZZY_MATCH_BLOCK_LEN_FLOOR,
    _FUZZY_MATCH_BLOCK_LEN_MULT,
    _FUZZY_MATCH_CONFIDENCE,
    _FUZZY_MATCH_MIN_ENTITY_LEN,
    _FUZZY_MATCH_RATIO,
    _NER_DEFAULT_MIN_LEN,
    _NER_MIN_LEN_BY_TYPE,
    _PROPERTY_TITLE_TAIL_LOOKAHEAD_CHARS,
    _TABLE_FALLBACK_CONFIDENCE,
)

logger = logging.getLogger(__name__)


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


def _fold_glyph(glyph: str) -> str:
    """Width-fold one glyph (NFKC), kept only when it stays a single glyph."""
    folded = unicodedata.normalize("NFKC", glyph)
    return folded if len(folded) == 1 else glyph


def _entity_span_char_boxes(
    block: OCRTextBlock,
    search_text: str,
    span_start: int,
    span_end: int,
) -> list[dict | None] | None:
    """Char boxes proven to render search_text[span_start:span_end).

    No proportional estimation and no thresholds: glyph correspondence comes
    from the monotone alignment (difflib matching blocks) of the two
    whitespace-stripped glyph sequences, which absorbs whitespace differences,
    same-glyph misreads (帐/账) and dropped char boxes alike. Boxes are
    returned only when the span's first and last glyphs each have a
    corresponding box — char boxes run in reading order, so their union also
    covers interior glyphs whose own box was dropped (interior entries may be
    None). Anything unprovable returns None and the caller masks the whole
    block.
    """
    chars = getattr(block, "chars", None) or []
    if not chars:
        return None

    # One entry per non-whitespace glyph; multi-char tokens ("2024-05-14")
    # contribute their box once per glyph. Glyphs are width-folded (NFKC,
    # kept only when it stays a single glyph) so fullwidth／halfwidth
    # punctuation variants（） vs () — NER text and OCR chars routinely
    # disagree on these — still align; a mismatched span EDGE glyph would
    # otherwise fail the first/last-proven guard and drop the whole crop.
    glyph_boxes: list[dict] = []
    chars_glyph_list: list[str] = []
    for char_box in chars:
        for glyph in _compact_text(str(char_box.get("c", ""))):
            chars_glyph_list.append(_fold_glyph(glyph))
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
        search_glyph_list.append(_fold_glyph(ch))
    if span_glyph_end <= span_glyph_start:
        return None
    search_glyphs = "".join(search_glyph_list)

    box_by_glyph: list[dict | None] = [None] * len(search_glyphs)
    if search_glyphs == chars_glyphs:
        box_by_glyph = list(glyph_boxes)
    else:
        matching_blocks = SequenceMatcher(
            None, search_glyphs, chars_glyphs, autojunk=False
        ).get_matching_blocks()
        for search_pos, chars_pos, size in matching_blocks:
            for offset in range(size):
                box_by_glyph[search_pos + offset] = glyph_boxes[chars_pos + offset]
        if None in box_by_glyph:
            # The word engine can emit boxes out of reading order (e.g.
            # ['岁', '27'] for "27岁"), which the monotone alignment above
            # cannot cross-match. Pair each still-unmatched search glyph
            # with an unconsumed char box by glyph identity, only when that
            # glyph is unique among the unmatched on both sides - identity
            # plus uniqueness keeps the correspondence proven, still no
            # estimation and no thresholds.
            consumed: set[int] = set()
            for _search_pos, chars_pos, size in matching_blocks:
                consumed.update(range(chars_pos, chars_pos + size))
            unmatched_search: dict[str, list[int]] = {}
            for index, glyph in enumerate(search_glyphs):
                if box_by_glyph[index] is None:
                    unmatched_search.setdefault(glyph, []).append(index)
            unmatched_chars: dict[str, list[int]] = {}
            for index, glyph in enumerate(chars_glyphs):
                if index not in consumed:
                    unmatched_chars.setdefault(glyph, []).append(index)
            for glyph, search_positions in unmatched_search.items():
                char_positions = unmatched_chars.get(glyph) or []
                if len(search_positions) == 1 and len(char_positions) == 1:
                    box_by_glyph[search_positions[0]] = glyph_boxes[char_positions[0]]

    span_boxes = box_by_glyph[span_glyph_start:span_glyph_end]
    # Recover a MISREAD span-edge glyph from the proven neighbour just OUTSIDE
    # the span. The entity sits between the char before it and the char after
    # it, both of which are usually common chars the recognizer got right — so
    # a right-misread last glyph (洪棘颢 read as 洪棘题: 颢 unmatched, dropping
    # the whole crop and masking the full line) is bounded on the right by the
    # box of the char that FOLLOWS the entity (已 in …洪棘颢已缴纳), and a
    # left-misread first glyph by the char that PRECEDES it. Real neighbour
    # boxes, no estimation. Only fires when the entity keeps ≥1 proven interior
    # box (so the recovered edge is still anchored to the entity, not a bare
    # neighbour guess).
    if span_boxes and any(box is not None for box in span_boxes):
        span_boxes = list(span_boxes)
        if span_boxes[0] is None and span_glyph_start > 0:
            before = box_by_glyph[span_glyph_start - 1]
            anchor = next((box for box in span_boxes if box is not None), None)
            if before is not None and anchor is not None:
                span_boxes[0] = {"x1": before["x2"], "x2": before["x2"],
                                 "y1": anchor["y1"], "y2": anchor["y2"]}
        if span_boxes[-1] is None and span_glyph_end < len(box_by_glyph):
            after = box_by_glyph[span_glyph_end]
            anchor = next((box for box in reversed(span_boxes) if box is not None), None)
            if after is not None and anchor is not None:
                span_boxes[-1] = {"x1": after["x1"], "x2": after["x1"],
                                  "y1": anchor["y1"], "y2": anchor["y2"]}
    if not span_boxes or span_boxes[0] is None or span_boxes[-1] is None:
        return None
    return span_boxes




def _entity_char_box_line_rects(
    block: OCRTextBlock,
    search_text: str,
    span_start: int,
    span_end: int,
) -> list[tuple[int, int, int, int]] | None:
    """Per-text-line rects of the proven char boxes.

    Merged multi-line blocks make a cross-line entity's x-span union cover
    the block's full width and height ("地点：门诊三楼 / 北走廊东侧" boxed as
    one slab). Char boxes arrive in reading order, so a line break is where
    reading order resets leftward — the next box STARTS left of where the
    previous box started. That identity holds on tilted photos where the two
    lines' y-ranges overlap and a y test would fuse them. One tight rect per
    line, no thresholds.
    """
    span_boxes = _entity_span_char_boxes(block, search_text, span_start, span_end)
    if not span_boxes:
        return None
    rects: list[tuple[int, int, int, int]] = []
    current: tuple[int, int, int, int] | None = None
    previous_x1: float | None = None
    for box in span_boxes:
        if box is None:
            continue
        x1, y1 = float(box["x1"]), float(box["y1"])
        x2, y2 = float(box["x2"]), float(box["y2"])
        if current is not None and previous_x1 is not None and x1 < previous_x1:
            rects.append(current)
            current = None
        current = (
            (int(x1), int(y1), int(x2), int(y2))
            if current is None
            else (
                min(current[0], int(x1)),
                min(current[1], int(y1)),
                max(current[2], int(x2)),
                max(current[3], int(y2)),
            )
        )
        previous_x1 = x1
    if current is not None:
        rects.append(current)
    # Width must be real (x is evidential). Height is NOT filtered here: on
    # tilted photos the word engine collapses a line's char boxes to a
    # zero-height y-band, and that rect is grown to its structural row height
    # just below. Filtering zero-height here would drop the whole crop before
    # the grow runs and fall back to masking the full block (the court-judgment
    # photo's 被告付有才 line boxed as a full-width slab).
    rects = [r for r in rects if r[2] > r[0]]
    if not rects:
        return None
    # The word engine's char boxes on tilted photos collapse vertically:
    # every char in a line carries the same sliver y-band (2-10px of a ~26px
    # line) while x stays correct, and a mosaic drawn from that band leaves
    # the glyphs readable (the court-judgment photo: 44 boxes all rendered,
    # names still legible). Height is structural, not evidential: a block is
    # len(rects) uniform text rows, so each line rect gets at least its row's
    # share of the block height, centered on the chars' own y-center (which
    # stays correct even when the band collapses). Grow-only, clamped to the
    # block polygon.
    polygon = getattr(block, "polygon", None) or []
    ys = [int(pt[1]) for pt in polygon if isinstance(pt, (list, tuple)) and len(pt) >= 2]
    if ys:
        block_top, block_bottom = min(ys), max(ys)
        row_h = (block_bottom - block_top) / len(rects)
        if row_h > 0:
            grown: list[tuple[int, int, int, int]] = []
            for x1r, y1r, x2r, y2r in rects:
                cy = (y1r + y2r) / 2
                y1g = min(y1r, int(cy - row_h / 2))
                y2g = max(y2r, int(cy + row_h / 2))
                grown.append((x1r, max(block_top, y1g), x2r, min(block_bottom, y2g)))
            rects = [r for r in grown if r[2] > r[0] and r[3] > r[1]]
    # Final guard: any rect the grow could not give real height (missing
    # polygon) is dropped so the caller safely masks the whole block rather
    # than emit a zero-height crop.
    return [r for r in rects if r[3] > r[1]] or None


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


class _SynthCharsBlock:
    """Minimal shim: a chars list under the attribute the span alignment reads,
    plus the polygon its char-box line rects grow their height into.

    Without a polygon, _entity_char_box_line_rects cannot recover a collapsed
    (zero/sliver height) char y-band to its structural line height, so a
    synthesized block MUST carry the real vertical extent of the blocks its
    chars came from — otherwise a phone-photo's flattened char boxes yield
    sliver-height crops that leave the glyphs readable.
    """

    __slots__ = ("chars", "polygon")

    def __init__(self, chars: list, polygon: list | None = None) -> None:
        self.chars = chars
        self.polygon = polygon or []


def _charsless_block_line_rects(
    block: OCRTextBlock,
    block_text: str,
    occurrence_start: int,
    occurrence_text: str,
    prepared_blocks: list,
) -> list[tuple[int, int, int, int]] | None:
    """Per-line rects for a value matched on a chars-less merged block.

    Chars are synthesized from the char-boxed line blocks geometrically
    inside the merged block (the same containment discovery as
    _narrow_charsless_block_to_lines), then the proven-span alignment and
    the reading-order line split are reused as-is. A cross-line value
    (「地点：门诊三楼 / 北走廊东侧」) gets one tight rect per line instead
    of the whole-paragraph slab. Alignment failure returns None and the
    caller falls back to the argmax single-line narrow, then to the safe
    whole-block mask.
    """
    if getattr(block, "chars", None):
        return None
    bl, bt, bw, bh = block.left, block.top, block.width, block.height
    lines = []
    for cand, _cand_text, _is_tv in prepared_blocks:
        if cand is block or not getattr(cand, "chars", None):
            continue
        ccx = cand.left + cand.width / 2.0
        ccy = cand.top + cand.height / 2.0
        if bt <= ccy <= bt + bh and bl <= ccx <= bl + bw:
            lines.append(cand)
    if len(lines) < 2:
        return None
    lines.sort(key=lambda c: (round(c.top), c.left))
    synthesized: list = []
    for cand in lines:
        synthesized.extend(getattr(cand, "chars", None) or [])
    if not synthesized:
        return None
    poly = [
        [min(c.left for c in lines), min(c.top for c in lines)],
        [max(c.left + c.width for c in lines), min(c.top for c in lines)],
        [max(c.left + c.width for c in lines), max(c.top + c.height for c in lines)],
        [min(c.left for c in lines), max(c.top + c.height for c in lines)],
    ]
    return _entity_char_box_line_rects(
        _SynthCharsBlock(synthesized, poly),
        block_text,
        occurrence_start,
        occurrence_start + len(occurrence_text),
    )


def split_regions_across_lines(
    regions: list[SensitiveRegion],
    ocr_blocks: list[OCRTextBlock],
) -> list[SensitiveRegion]:
    """Split text regions that slab across several text lines into per-line rects.

    Whatever match path produced the region (exact occurrence, compact/fuzzy
    match, virtual union block), a region whose box geometrically contains two
    or more char-boxed line blocks and whose text provably aligns onto those
    lines' glyphs is a cross-line value — mask each line tightly instead of
    the full-width slab (「地点：门诊三楼 / 北走廊东侧」). Alignment reuses
    the proven-span machinery: unprovable regions are left untouched, so a
    region is never shrunk on a guess.
    """
    line_blocks = [b for b in ocr_blocks if getattr(b, "chars", None)]
    if not line_blocks:
        return regions
    out: list[SensitiveRegion] = []
    for region in regions:
        rl, rt = region.left, region.top
        rr, rb = region.left + region.width, region.top + region.height
        contained = [
            b for b in line_blocks
            if rl <= b.left + b.width / 2.0 <= rr and rt <= b.top + b.height / 2.0 <= rb
        ]
        if len(contained) < 2:
            out.append(region)
            continue
        contained.sort(key=lambda b: (round(b.top), b.left))
        synthesized: list = []
        for cand in contained:
            synthesized.extend(getattr(cand, "chars", None) or [])
        text = str(region.text or "")
        # Real vertical extent of the contained line blocks, so each split line
        # rect grows to its structural row height instead of the collapsed char
        # y-band (phone-photo lines flatten the char boxes but keep block height).
        poly = [
            [min(b.left for b in contained), min(b.top for b in contained)],
            [max(b.left + b.width for b in contained), min(b.top for b in contained)],
            [max(b.left + b.width for b in contained), max(b.top + b.height for b in contained)],
            [min(b.left for b in contained), max(b.top + b.height for b in contained)],
        ]
        rects = _entity_char_box_line_rects(
            _SynthCharsBlock(synthesized, poly), text, 0, len(text)
        )
        if not rects or len(rects) < 2:
            out.append(region)
            continue
        for lx1, ly1, lx2, ly2 in rects:
            out.append(region.__class__(
                text=text,
                entity_type=region.entity_type,
                left=lx1,
                top=ly1,
                width=lx2 - lx1,
                height=ly2 - ly1,
                confidence=region.confidence,
                source=region.source,
            ))
    return out


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


def _match_cross_block_entity(
    entity_text: str,
    entity_type: str,
    prepared_blocks: list[tuple[OCRTextBlock, str, bool]],
) -> list[SensitiveRegion]:
    """Anchor a newline-carrying entity value across adjacent OCR blocks.

    The value's own line break marks the wrap point: segment 0 must be the
    SUFFIX of some block, middle segments must be whole blocks, and the last
    segment the PREFIX of the following block. Matching is positional — the
    single-char tail of '刘中\\n琦' is only accepted as the prefix of the
    block that follows the block ending with '刘中', never anywhere else on
    the page. One region per segment (a wrapped value is physically several
    line pieces); x narrows to proven char boxes when available, y keeps the
    block's line height.
    """
    segments = [seg.strip() for seg in entity_text.split("\n") if seg.strip()]
    if len(segments) < 2:
        return []
    direct = [
        (block, block_text)
        for block, block_text, is_table_virtual in prepared_blocks
        if not is_table_virtual and not block_text.startswith("<table")
    ]
    out: list[SensitiveRegion] = []
    for i in range(len(direct) - len(segments) + 1):
        _, first_text = direct[i]
        if not first_text.endswith(segments[0]):
            continue
        if any(
            _compact_text(direct[i + k][1]) != _compact_text(segments[k])
            for k in range(1, len(segments) - 1)
        ):
            continue
        _, last_text = direct[i + len(segments) - 1]
        if not last_text.startswith(segments[-1]):
            continue
        for k, segment in enumerate(segments):
            block, block_text = direct[i + k]
            if k == 0:
                start = len(block_text) - len(segment)
            elif k == len(segments) - 1:
                start = 0
            else:
                start = max(0, block_text.find(segment))
            rl, rt, rw, rh = block.left, block.top, block.width, block.height
            line_rects = _entity_char_box_line_rects(
                block, block_text, start, start + len(segment)
            )
            if line_rects is not None and len(line_rects) == 1:
                lx1, _ly1, lx2, _ly2 = line_rects[0]
                rl, rw = lx1, lx2 - lx1
            out.append(SensitiveRegion(
                text=segment,
                entity_type=entity_type,
                left=rl,
                top=rt,
                width=rw,
                height=rh,
                confidence=1.0,
                source="text_match",
            ))
    return out


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

        if "\n" in entity_text:
            # A value that wraps across OCR blocks arrives with the line break
            # inside it (HaS tags '刘中\n琦' from the joined page text; the
            # date backstop scans the joined text the same way). No single
            # block contains that string — anchor it as consecutive
            # suffix/whole/prefix runs over adjacent blocks instead.
            cross_regions = _match_cross_block_entity(entity_text, normalized_type, prepared_blocks)
            if cross_regions:
                regions.extend(cross_regions)
                continue

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
                    line_rects = _entity_char_box_line_rects(
                        block,
                        block_text,
                        visual_occurrence_start,
                        visual_occurrence_start + len(visual_text),
                    )
                    crop_span = None
                    if line_rects is not None:
                        crop_span = (
                            min(r[0] for r in line_rects),
                            max(r[2] for r in line_rects),
                        )
                        if len(line_rects) == 1:
                            # Single line: x narrows to the proven chars; y/height
                            # stay the block's full line height (705318c contract).
                            rl, rw = crop_span[0], crop_span[1] - crop_span[0]
                    else:
                        line_rects = _charsless_block_line_rects(
                            block, block_text, visual_occurrence_start, visual_text, prepared_blocks
                        )
                        if line_rects is not None:
                            crop_span = (
                                min(r[0] for r in line_rects),
                                max(r[2] for r in line_rects),
                            )
                            if len(line_rects) == 1:
                                lx1, ly1, lx2, ly2 = line_rects[0]
                                rl, rt, rw, rh = lx1, ly1, lx2 - lx1, ly2 - ly1
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
                    region_source = (
                        entity_source
                        if entity_source in {"table_semantic", "form_field_ocr"}
                        else
                        "table_cell_match"
                        if is_table_virtual
                        else "text_match"
                    )
                    if line_rects is not None and len(line_rects) > 1:
                        # Cross-line entity in a merged multi-line block: the
                        # x-span union would cover the block's full width and
                        # height, so emit one tight region per text line.
                        for lx1, ly1, lx2, ly2 in line_rects:
                            entity_regions.append((
                                SensitiveRegion(
                                    text=visual_text,
                                    entity_type=contextual_type,
                                    left=lx1,
                                    top=ly1,
                                    width=lx2 - lx1,
                                    height=ly2 - ly1,
                                    confidence=1.0,
                                    source=region_source,
                                ),
                                has_position_evidence,
                                not has_position_evidence,
                            ))
                        logger.debug(
                            "MATCH '%s' in '%s...' across %d lines",
                            entity_text, block_text[:20], len(line_rects),
                        )
                    else:
                        entity_regions.append((
                            SensitiveRegion(
                                text=visual_text,
                                entity_type=contextual_type,
                                left=rl,
                                top=rt,
                                width=rw,
                                height=rh,
                                confidence=1.0,
                                source=region_source,
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
