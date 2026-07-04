"""Entity-to-OCR matching: attach detected values to OCR boxes.

Split out of ocr_pipeline.py (which stays the public facade): visual match
span selection (amount pairs, document-title suffixes), char-box-proven value
crops, chars-less paragraph narrowing, strict/isolated-token rules, fuzzy and
table fallbacks, and spatial region dedupe.
"""
from __future__ import annotations

import logging
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
