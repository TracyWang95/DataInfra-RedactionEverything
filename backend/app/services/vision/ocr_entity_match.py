"""Entity-to-OCR matching: attach detected values to OCR boxes.

Split out of ocr_pipeline.py (which stays the public facade): visual match
span selection, char-box-proven value crops, chars-less paragraph narrowing,
strict/isolated-token rules, fuzzy and table fallbacks, and spatial region
dedupe.
"""
from __future__ import annotations

import logging
import os
from difflib import SequenceMatcher

from app.services.ocr_has_vision_service import OCRTextBlock, SensitiveRegion
from app.services.vision.has_text_payload import (
    _canonical_image_text_type,
    _compact_text,
    _strip_vl_math_markup,
)

# Geometry cluster: parent uses these + re-exports the rest for the public API.
from app.services.vision.ocr_cjk_geometry import (
    _CJK_LINE_HEIGHT_RATIO,
    _column_split_char_boxes,
    _document_line_height,
    _entity_char_box_line_rects,
    _entity_span_char_boxes,  # noqa: F401
    _fold_glyph,  # noqa: F401
    _glyph_alignment,
    _leading_label_trimmed_start,
    _median_single_cjk_width,  # noqa: F401
    _region_cjk_em,
    _span_rects_with_row_bands,
)
from app.services.vision.ocr_table_semantics import (
    _amount_digit_signature,
    _amount_value_signature,
    _block_search_text,
)
from app.services.vision.ocr_tuning import (
    _FUZZY_MATCH_BLOCK_LEN_FLOOR,
    _FUZZY_MATCH_BLOCK_LEN_MULT,
    _FUZZY_MATCH_CONFIDENCE,
    _FUZZY_MATCH_MIN_ENTITY_LEN,
    _FUZZY_MATCH_RATIO,
    _NER_DEFAULT_MIN_LEN,
    _NER_MIN_LEN_BY_TYPE,
)

logger = logging.getLogger(__name__)


def _column_split_enabled() -> bool:
    """Whether to feed merged double-column blocks downstream as per-column
    sub-blocks (``REDACT_OCR_COLUMN_SPLIT``). Defaults OFF for a safe gray-launch
    — read fresh each call so operators can flip it without a restart, and so the
    shipped (un-split) behaviour is byte-identical until it is turned on."""
    return os.getenv("REDACT_OCR_COLUMN_SPLIT", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _column_split_sub_blocks(block: OCRTextBlock) -> list[OCRTextBlock]:
    """Per-column sub-blocks for a block whose chars form >= 2 em-gutter columns.

    PaddleOCR-VL sometimes MERGES two side-by-side columns into one block; each
    char keeps its own x but y collapses to the whole block's range, so a value
    that lives in one column can align across the gutter and be masked as the
    full-width slab. _column_split_char_boxes (self-calibrated em-gutter, no
    hardcoded pixel threshold) splits the chars into per-column groups; each
    group becomes a sub-block whose text is the group's chars, whose chars ARE
    the group, and whose polygon is the group's x-union at the ORIGINAL block's
    y range — the split only ever touches x, never y (vertical extent stays the
    merged band, tightening is R7c's job).

    Returns [] when the block has no chars or forms a single column, so the
    caller adds nothing and behaviour is unchanged. LEAK-SAFETY: the caller
    ALWAYS keeps the original block too, so a sub-block only ADDS a tighter
    per-column candidate; a value that genuinely spans both columns matches
    NEITHER sub-block (its glyphs are split) and stays covered by the original.
    """
    chars = getattr(block, "chars", None) or []
    if not chars:
        return []
    groups = _column_split_char_boxes(chars)
    if len(groups) <= 1:
        return []
    top = block.top
    bottom = block.top + block.height
    sub_blocks: list[OCRTextBlock] = []
    for group in groups:
        left = min(float(c["x1"]) for c in group)
        right = max(float(c["x2"]) for c in group)
        text = "".join(str(c.get("c", "")) for c in group)
        polygon = [[left, top], [right, top], [right, bottom], [left, bottom]]
        sub_blocks.append(
            OCRTextBlock(text=text, polygon=polygon, confidence=block.confidence, chars=group)
        )
    return sub_blocks


def _is_low_signal_vision_entity(entity_type: str, entity_text: str) -> bool:
    compact = _compact_text(entity_text)
    if not compact:
        return True
    return False


def _entity_type_from_block_context(entity_type: str, entity_text: str, block_text: str) -> str | None:
    return _canonical_image_text_type(entity_type)


def _dedupe_ocr_regions(regions: list[SensitiveRegion]) -> list[SensitiveRegion]:
    """Drop OCR regions whose pixels are already covered (same pixels).

    A single containment pass with no type/text/source/ranking rules: a region is
    dropped only when its box is swallowed whole by the union of the kept
    (larger-or-equal) boxes — any exposed pixel keeps it. Two real PII values on
    different parts of the page — e.g. the same date in three table rows, or a
    name in the 姓名 cell and again in a signature — never nest, so they are
    always kept. The old bucket-key + same-line + startswith heuristics each
    risked dropping a distinct value (a missed redaction); a partial-overlap twin
    that sticks out is no longer dropped either (the old IoU>=0.5 pass would have
    uncovered its exposed strip).

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

    # Containment dedup runs PER entity_type: a region is dropped only when
    # SAME-type kept regions already cover its pixels. Cross-type coverage is NOT a
    # duplicate — a real DATE fully inside a (PaddleOCR-VL pseudo-table) PERSON box
    # is a different entity, and the old type-agnostic pass silently swallowed it (a
    # missed redaction). Grouping by type keeps the coverage-preserving within-type
    # merge while never letting a larger box of one type eat a smaller box of another.
    from itertools import groupby

    deduped: list = []
    for _etype, group in groupby(
        sorted(tightest, key=lambda r: str(r.entity_type)),
        key=lambda r: str(r.entity_type),
    ):
        deduped.extend(
            deduplicate_by_iou(
                list(group),
                lambda r: (r.left, r.top, r.width, r.height),
                mode="containment",
            )
        )
    return deduped


def _regions_overlap(a: SensitiveRegion, b: SensitiveRegion) -> bool:
    """The two regions share any pixels (topological, no thresholds)."""
    return (
        a.left < b.left + b.width
        and b.left < a.left + a.width
        and a.top < b.top + b.height
        and b.top < a.top + a.height
    )


def _prune_looser_same_text_boxes(
    regions: list[SensitiveRegion],
    span_proven_ids: set[int] | None = None,
) -> list[SensitiveRegion]:
    """Keep the tightest box among same-type, same-text, overlapping regions.

    One value can be localized more than once: a garbled handwritten ID matches
    both its own right-column glyphs (tight) AND — because the char alignment
    strays across a merged two-column OCR block — the whole row (拍照保姆合同:
    身份证号码 0.734 page-wide). Same text ⇒ same value, so the tighter box may
    already cover its glyphs; the wider twin is then redundant over-coverage that
    bleeds onto the other column's field and labels.

    Coverage precondition: the wider box is dropped ONLY when the tighter twin is
    a COMPLETE-span proof — its box is the union of the value's char boxes with
    the span's first AND last glyph proven (``span_proven_ids``, computed by the
    caller from ``_entity_span_char_boxes``). Char boxes run in reading order, so
    a proven first+last glyph means the tight box spans every glyph of the value:
    dropping the wider twin cannot uncover a glyph. A tighter box from an argmax
    PARTIAL match (it may cover only "123" of "X12345") is NOT a proof — the
    wider box is kept so the tail glyphs stay masked.

    Leak-safe: only boxes that share the SAME text AND overlap are collapsed, and
    only against a proven-full-span twin; every other field keeps its own box, a
    value repeated elsewhere (non-overlapping) is untouched.
    """
    if len(regions) <= 1:
        return regions
    proven = span_proven_ids or set()
    drop_ids: set[int] = set()
    for region in regions:
        r_text = (region.text or "").strip()
        if not r_text:
            continue
        r_area = region.width * region.height
        for other in regions:
            if other is region or id(other) in drop_ids:
                continue
            if (
                other.entity_type == region.entity_type
                and (other.text or "").strip() == r_text
                and other.width * other.height < r_area
                and _regions_overlap(region, other)
                and id(other) in proven
            ):
                drop_ids.add(id(region))
                logger.debug(
                    "Dropped looser same-text box for '%s' (w=%d) — proven tighter twin (w=%d) covers it",
                    r_text, region.width, other.width,
                )
                break
    return [r for r in regions if id(r) not in drop_ids]


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


def _whitespace_insensitive_value_spans(entity_text: str, block_text: str) -> list[tuple[int, int]]:
    """[start, end) spans in block_text whose NON-whitespace glyphs spell entity_text.

    A grouped number renders the value the NER returns compacted: the block reads
    "帐号：0383 2700 0400 3104 0", the NER tags "03832700040031040". The grouping
    spaces are display formatting, not content, so an exact substring test misses
    the match; matching glyph-by-glyph while skipping whitespace recovers it and
    returns the FULL span (spaces included) so the downstream char-box crop covers
    every rendered glyph. Non-overlapping, left to right.
    """
    target = "".join(entity_text.split())
    if not target:
        return []
    spans: list[tuple[int, int]] = []
    n = len(block_text)
    i = 0
    while i < n:
        if block_text[i].isspace() or block_text[i] != target[0]:
            i += 1
            continue
        j, k, last = i, 0, i
        while j < n and k < len(target):
            if block_text[j].isspace():
                j += 1
                continue
            if block_text[j] != target[k]:
                break
            k += 1
            j += 1
            last = j
        if k == len(target):
            spans.append((i, last))
            i = last
        else:
            i += 1
    return spans


def _value_occurrence_spans(
    entity_text: str, block_text: str, strict_value: bool
) -> list[tuple[int, int]]:
    """Occurrence spans [start, end) of the value inside block_text.

    Exact substring occurrences first. When none exist and the value is not a
    strict short token, fall back to a whitespace-insensitive span so a grouped
    number matches its compacted NER value (the grouping spaces are formatting).
    A strict short value must still be an isolated token — never a bare substring,
    and never the whitespace fallback (a 1-2 char token would match stray glyphs).
    """
    spans: list[tuple[int, int]] = []
    if entity_text in block_text:
        search_from = 0
        while True:
            start = block_text.find(entity_text, search_from)
            if start < 0:
                break
            end = start + len(entity_text)
            if not strict_value or _is_isolated_token_occurrence(block_text, start, end):
                spans.append((start, end))
            search_from = start + max(1, len(entity_text))
        return spans
    if strict_value:
        return []
    compact_entity = _compact_text(entity_text)
    if not compact_entity or compact_entity not in _compact_text(block_text):
        return []
    return _whitespace_insensitive_value_spans(entity_text, block_text)


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


# Measurement / counter units that are NOT money — an area, a count, a date part.
# A number directly followed by one of these is that quantity, not a currency amount:
# 100亩 (area) is not 100元 (money), 2016年 (a year) is not the amount 2016. Deliberately
# excludes the money units/magnitudes (元圆角分厘块万千百十亿…) so a real amount still
# matches; excludes ambiguous 分/厘 (also money) so those never falsely reject.
_NON_MONEY_UNITS = frozenset("亩顷㎡平方米里人位名户岁天次件套台辆吨%％度年月日时号")

# Arabic-digit OR Chinese-numeral content is what makes a value an amount at all.
_CJK_NUMERALS = frozenset("零〇一二三四五六七八九十百千万亿两壹贰叁肆伍陆柒捌玖拾佰仟萬億兆")


def _is_same_amount_value_block(entity_text: str, block_text: str) -> bool:
    """Same amount value in a different display form (￥1431400.00元 vs 1431400，00).

    Digit-sequence identity over the block's digit content — two renderings of one
    number share it whatever the grouping/currency decoration, and a bare running-text
    mention of the amount ('合同总金额…1431400相关') is still covered (over-mask). But the
    digit signature alone ignored the trailing CONTEXT: it read 100 in '暂估面积100亩' as
    the amount '100元' and whole-masked the sentence, though 亩 is an AREA unit, not money.
    So reject when the block's number is directly followed by a non-money unit — the one
    signal that tells 100元 (money) from 100亩 (area) apart, exactly as the reviewer noted.
    Over-mask, never uncover: a real amount inside prose still matches via this path (no
    contradicting unit) and via the exact per-occurrence path.
    """
    entity_signature = _amount_value_signature(entity_text)
    if not entity_signature:
        return False
    compact = _compact_text(block_text)
    if _amount_value_signature(compact) != entity_signature:
        return False
    last_digit = max((i for i, ch in enumerate(compact) if ch.isdigit()), default=-1)
    if 0 <= last_digit < len(compact) - 1 and compact[last_digit + 1] in _NON_MONEY_UNITS:
        return False
    return True


def _extend_amount_left_over_numerals(block, left: int, width: int, top: int, height: int) -> tuple[int, int]:
    """Grow an AMOUNT box LEFT over an adjacent Chinese-numeral char box.

    The char engine reads the handwritten 壹 of '壹拾万元' as a stray glyph the block
    TEXT calls something non-numeric (票), so HaS's amount begins at 拾 and the crop
    stops one numeral short — 壹 is left unmasked. The char BOXES still carry the numeral
    glyph, so extend the left edge over any char box that IS a numeral, sits just left of
    the current edge (within one em, same text row) — never over a non-numeral, never
    rightward. Pure char-box geometry, no estimation; only ever adds cover.
    """
    chars = getattr(block, "chars", None) or []
    right = left + width
    y1b, y2b = top, top + height
    cur = left
    extended = True
    while extended:
        extended = False
        candidates: list[int] = []
        for c in chars:
            try:
                cx1, cx2, cy1, cy2 = int(c["x1"]), int(c["x2"]), int(c["y1"]), int(c["y2"])
            except (KeyError, TypeError, ValueError):
                continue
            if str(c.get("c", "")) not in _CJK_NUMERALS:
                continue
            if not (y1b <= (cy1 + cy2) / 2 <= y2b):
                continue
            if cx2 <= cur and cx1 < cur and (cur - cx2) <= max(1, cx2 - cx1):
                candidates.append(cx1)
        if candidates and min(candidates) < cur:
            cur = min(candidates)
            extended = True
    return cur, right - cur


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


def _own_chars_own_span(
    block: OCRTextBlock,
    block_text: str,
    occurrence_start: int,
    occurrence_text: str,
) -> bool:
    """Whether the block's OWN chars are authoritative for this span.

    They are only when they carry at least one proven glyph for it. A block
    whose attached chars cover other rows but prove NOTHING about the span
    (the crop re-OCR missed the value's line — the 房屋 paragraph's chars
    start at row 2 while the address sits on row 1) must not monopolize the
    span: a sibling PP-native line block with real char boxes for that row
    is strictly better evidence than a full-width row band."""
    if not (getattr(block, "chars", None) or []):
        return False
    alignment = _glyph_alignment(
        block, block_text, occurrence_start, occurrence_start + len(occurrence_text)
    )
    if alignment is None:
        return False
    box_by_glyph, span_glyph_start, span_glyph_end = alignment
    return any(box is not None for box in box_by_glyph[span_glyph_start:span_glyph_end])


def _charsless_block_line_rects(
    block: OCRTextBlock,
    block_text: str,
    occurrence_start: int,
    occurrence_text: str,
    prepared_blocks: list,
    line_height: float | None = None,
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
    if _own_chars_own_span(block, block_text, occurrence_start, occurrence_text):
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
        line_height,
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
    document_line_height = _document_line_height(ocr_blocks)
    out: list[SensitiveRegion] = []
    # Whether each `out` region is a single text row (safe to height-normalize) or
    # a genuine multi-line slab that stays as-is (shrinking it would uncover ink).
    single_row: list[bool] = []
    for region in regions:
        rl, rt = region.left, region.top
        rr, rb = region.left + region.width, region.top + region.height
        contained = [
            b for b in line_blocks
            if rl <= b.left + b.width / 2.0 <= rr and rt <= b.top + b.height / 2.0 <= rb
        ]
        if len(contained) < 2:
            out.append(region)
            single_row.append(True)
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
            _SynthCharsBlock(synthesized, poly), text, 0, len(text), document_line_height
        )
        # A split PARTITIONS the region: alignment evidence outside the
        # region's own box belongs to other regions, not to this one (a
        # partial-proof row band contains a sibling line block, and aligning
        # the full value text onto it re-derives the value's OTHER rows —
        # rows that already carry their own tight rect). Clip each rect to
        # the region; a genuine slab contains its rows, so this is a no-op
        # for the original slab-splitting behavior.
        if rects:
            rects = [
                (cx1, cy1, cx2, cy2)
                for lx1, ly1, lx2, ly2 in rects
                for cx1, cy1, cx2, cy2 in [
                    (max(lx1, int(rl)), max(ly1, int(rt)), min(lx2, int(rr)), min(ly2, int(rb)))
                ]
                if cx2 > cx1 and cy2 > cy1
            ]
        if not rects or len(rects) < 2:
            out.append(region)
            single_row.append(False)  # unprovable multi-line slab: never trim
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
            single_row.append(True)
    # Trim over-tall single rows to the page's median single-row height — but
    # never below the row's OWN font. The median is self-calibrating (measured
    # from the boxes we just produced) and trims real outliers: a DATE's
    # un-collapsed digit boxes, the wrapped 日 a grow-only step preserved. Yet a
    # genuinely large-font row (a title/header) is legitimately taller than the
    # body grid — flattening it to the median UNCOVERS its glyphs (the court name
    # 昆明市盘龙区人民法院 read flat). The two are told apart with no threshold by
    # the same em that sized the row upstream: its own median single-CJK char
    # WIDTH. A large font is wide AND tall (em row height clears the median →
    # kept); a body-grid outlier is merely tall (normal/absent CJK em → trimmed).
    # No CJK em (an all-Latin value) keeps the body grid. Only single rows, only
    # downward: a real glyph is <= its row height so this never uncovers ink,
    # collapsed rows that grew UP stay put, multi-line slabs are left whole.
    row_heights = sorted(r.height for r, one in zip(out, single_row, strict=True) if one)
    if row_heights:
        median_row = row_heights[len(row_heights) // 2]
        for region, one in zip(out, single_row, strict=True):
            if not one or region.height <= median_row:
                continue
            em = _region_cjk_em(region, line_blocks)
            ceiling = median_row if em is None else max(median_row, int(em * _CJK_LINE_HEIGHT_RATIO))
            if region.height > ceiling:
                center_y = region.top + region.height / 2.0
                region.top = int(center_y - ceiling / 2.0)
                region.height = int(ceiling)
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
    if _own_chars_own_span(block, block_text, occurrence_start, occurrence_text):
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
    line_height: float | None = None,
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
                block, block_text, start, start + len(segment), line_height
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
                # Inherit the recognised line's own score instead of asserting a
                # flat 1.0: a region is only as certain as the text it was matched
                # against. (The classic OCR path now supplies a real rec_score;
                # the VL path still hands over a placeholder.)
                confidence=getattr(block, "confidence", None),
                source="text_match",
            ))
    return out


def _match_cross_block_split(
    entity_text: str,
    entity_type: str,
    prepared_blocks: list[tuple[OCRTextBlock, str, bool]],
    line_height: float | None = None,
) -> list[SensitiveRegion]:
    """Anchor a clean (no-newline) value that wrapped across two adjacent blocks.

    HaS sometimes hands back a wrapped value with the line break REMOVED —
    '2076年4月8日' from '…起至2076年' + '4月8日止', or '2016年1月7日' from '…2016年1月7'
    + '日公开…' — so it sits in no single block and the newline anchor never fires.
    Try each interior split: a head that is some block's SUFFIX plus a tail that is
    the very NEXT block's PREFIX. The head must be >= 2 chars (a lone shared glyph
    can't fabricate a match) and the whole value >= 4, but the tail may be a single
    glyph — a date routinely wraps its trailing 日/号 alone. Positional and
    adjacent-only; once the split is found, reuse the newline anchor for the regions.
    """
    compact = entity_text.strip()
    if "\n" in compact or len(compact) < 4:
        return []
    direct = [
        block_text
        for _block, block_text, is_table_virtual in prepared_blocks
        if not is_table_virtual and not block_text.startswith("<table")
    ]
    for i in range(len(direct) - 1):
        head_block, tail_block = direct[i], direct[i + 1]
        for k in range(2, len(compact)):
            head, tail = compact[:k], compact[k:]
            if head_block.endswith(head) and tail_block.startswith(tail):
                return _match_cross_block_entity(
                    head + "\n" + tail, entity_type, prepared_blocks, line_height
                )
    return []


# Entity propagation: the company-specific HEAD of an org name, before the first
# generic tail marker (地名括号 / 有限公司 / 集团 …). "信尔胜机械（江苏）有限公司" ->
# "信尔胜机械". This head survives a seal-garbled second occurrence and is specific
# enough that any block carrying it IS that org.
_ORG_GENERIC_MARKERS = ("（", "(", "有限", "股份", "责任", "集团", "总公司", "分公司")
_ORG_CORE_MIN_LEN = 4
_ORG_CORE_PROPAGATION_CONFIDENCE = 0.6


def _org_distinctive_core(name: str) -> str:
    cut = len(name)
    for marker in _ORG_GENERIC_MARKERS:
        idx = name.find(marker)
        if 0 <= idx < cut:
            cut = idx
    return name[:cut].strip()


def match_entities_to_ocr(
    ocr_blocks: list[OCRTextBlock],
    entities: list[dict[str, str]],
    _digit_retry: bool = False,
) -> list[SensitiveRegion]:
    """
    Match HaS-detected entities to OCR text blocks using text matching to get
    precise bounding boxes.  Supports sub-word positioning, HTML table expansion,
    and fuzzy matching.
    """
    regions: list[SensitiveRegion] = []
    digit_retry_entities: list[dict[str, str]] = []
    # Region ids whose box is a COMPLETE-span char-box proof (first+last glyph
    # of the value aligned). _prune_looser_same_text_boxes may only drop a wider
    # same-text twin against one of these — an argmax/partial box is not a proof.
    span_proven_region_ids: set[int] = set()

    # A PaddleOCR-VL <table> block carries the table's STRUCTURE (which cell holds
    # what text) but NO per-cell pixel geometry — extract_table_cells could only
    # ESTIMATE cell boxes by a uniform row/col grid (block.height/num_rows), which
    # misplaces every value onto the wrong row the moment rows differ in height (a
    # 10-line spec row beside a 1-line total row — every real contract). Worse, VL
    # sometimes wraps a NON-table page into a pseudo <table>, boxing whole paragraphs
    # as giant cells whose boxes then swallow the real entities nested in them. The
    # line-OCR (PP-StructureV3) already detects every printed cell's text at its TRUE
    # box, so entity geometry comes from those real blocks and the <table> block is
    # dropped from position matching. Its structure still reaches the NER through the
    # separate _expand_table_blocks pass, so table recall is unaffected. Model-centric:
    # geometry from detection, never from a grid estimate — no threshold, no magic.
    expanded_blocks: list[OCRTextBlock] = [
        block
        for block in ocr_blocks
        if not (block.text.startswith("<table") and "</table>" in block.text)
    ]
    table_virtual_block_ids: set[int] = set()

    # Merged double-column split (gated, default OFF). PaddleOCR-VL can merge two
    # side-by-side columns into one block; a per-column value then aligns across
    # the gutter and over-covers the full width. Feed each column group
    # downstream as its own sub-block so the value matches its own column's tight
    # char boxes; the ORIGINAL block is always kept (already appended above), so
    # this only ADDS a tighter candidate and the existing prune/dedupe collapses
    # the full-width twin — strictly coverage-preserving. Table-virtual cells
    # already carry precise per-cell boxes, so they are skipped.
    if _column_split_enabled():
        column_sub_blocks: list[OCRTextBlock] = []
        for block in expanded_blocks:
            if id(block) in table_virtual_block_ids or block.text.startswith("<table"):
                continue
            column_sub_blocks.extend(_column_split_sub_blocks(block))
        if column_sub_blocks:
            logger.debug("Column-split emitted %d sub-blocks", len(column_sub_blocks))
            expanded_blocks.extend(column_sub_blocks)
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
    document_line_height = _document_line_height([block for block, _text, _is_tv in prepared_blocks])

    for entity in entities:
        # Same VL math-markup strip as _block_search_text: HaS tags entities on
        # the raw VL text, so both sides must normalize identically to match.
        entity_text = _strip_vl_math_markup(entity.get("text", "")).strip()
        entity_type = entity.get("type", "UNKNOWN")
        entity_source = str(entity.get("source") or "").strip()

        if not entity_text:
            continue

        # Tag-by-request: entity types arrive as the checked item's id (the
        # HaS bucket map is built purely from the request) — no Chinese-label
        # translation table. Unknown open-vocabulary labels pass through as
        # their own type (识别出来是啥就是啥).
        normalized_type = _canonical_image_text_type(entity_type)

        if _is_low_signal_vision_entity(normalized_type, entity_text):
            logger.debug("HaS skipped low-signal vision entity: '%s' (%s)", entity_text, normalized_type)
            continue

        # An AMOUNT is by definition a number: HaS sometimes tags a whole fill-in clause
        # ('乙方用于投资入股的土地位于河南新乡市，暂估面积') as 金额 with no digit or numeral
        # in it at all, which text_match then masks as a giant false amount. A value that
        # carries no Arabic digit and no Chinese numeral is not an amount — drop it.
        if normalized_type == "AMOUNT" and not any(
            c.isdigit() or c in _CJK_NUMERALS for c in entity_text
        ):
            logger.debug("HaS skipped numberless AMOUNT value: '%s'", entity_text)
            continue

        matched = False
        strict_value = _is_strict_match_entity(normalized_type, entity_text)

        if "\n" in entity_text:
            # A value that wraps across OCR blocks arrives with the line break
            # inside it (HaS tags '刘中\n琦' from the joined page text; the
            # date backstop scans the joined text the same way). No single
            # block contains that string — anchor it as consecutive
            # suffix/whole/prefix runs over adjacent blocks instead.
            cross_regions = _match_cross_block_entity(
                entity_text, normalized_type, prepared_blocks, document_line_height
            )
            if cross_regions:
                regions.extend(cross_regions)
                continue

        # This entity's matches, with the evidence they carry: whether the
        # region pins the value's position (the block IS the value, or the
        # char-aligned crop located its glyphs) versus an uncropped
        # whole-block containment claim (no position evidence at all).
        entity_regions: list[tuple[SensitiveRegion, bool, bool]] = []
        for block, block_text, is_table_virtual in prepared_blocks:
            if block_text.startswith("<table"):
                continue

            # Containment match against the authoritative text. Blocks whose char
            # boxes disprove their text label never reach here with the lying label
            # (_block_search_text), so a value is only ever attached to a box that
            # actually contains it. Occurrences are exact substrings, or — when the
            # value is not a strict short token — a whitespace-insensitive span: a
            # grouped number ("帐号：0383 2700 0400 3104 0") renders the very value
            # the NER returned compacted ("03832700040031040"); the grouping spaces
            # are display formatting, not content, and must not block the match.
            occurrences = _value_occurrence_spans(entity_text, block_text, strict_value)
            if occurrences:
                contextual_type = _entity_type_from_block_context(normalized_type, entity_text, block_text)
                if contextual_type is None:
                    continue
                for occurrence_start, occurrence_end in occurrences:
                    # 100 in an AREA (…面积100亩) or a year (2016年) shares its digits with
                    # a money amount, so HaS sometimes tags the clause as 金额; the unit
                    # right after the number tells them apart (the reviewer's 100元 vs
                    # 100亩 point). Skip an AMOUNT occurrence whose number is directly
                    # followed by a non-money unit — it is that quantity, not money.
                    if normalized_type == "AMOUNT":
                        tail = block_text[occurrence_end:].lstrip()
                        if tail and tail[0] in _NON_MONEY_UNITS:
                            continue
                    # If the NER returned the value WITH its leading form-field label
                    # (甲方：中海油…, 开户行：农行…), hug the value not the label: push the
                    # start past a gutter-terminated colon label (pure geometry, no
                    # wordlist). No-op when the span is already label-free.
                    occurrence_start = _leading_label_trimmed_start(
                        block, block_text, occurrence_start, occurrence_end
                    )
                    # The matched span IS the visual span (the exact substring, or
                    # the whitespace-spanning run of a grouped number). The old
                    # 大写/小写 pair word-lookup is gone: the main HaS query's dual
                    # labels (金额+大写金额) tag both renderings of a paired amount
                    # independently, so each side carries its own box, no lookback.
                    visual_text = block_text[occurrence_start:occurrence_end]
                    visual_occurrence_start = occurrence_start
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
                        document_line_height,
                    )
                    crop_span = None
                    # Whether this region's box is a complete-span glyph proof
                    # (both _entity_char_box_line_rects and _charsless_block_line_rects
                    # go through _entity_span_char_boxes' first+last-glyph guard).
                    # The argmax narrow and the row-band mixed path are NOT proofs.
                    span_proven = False
                    if line_rects is not None:
                        span_proven = True
                        crop_span = (
                            min(r[0] for r in line_rects),
                            max(r[2] for r in line_rects),
                        )
                        if len(line_rects) == 1:
                            # Single line: crop to the proven line rect — x from the
                            # chars, y/height its grown ROW height. The row-height
                            # grow already yields one text row even when the char
                            # y-band collapsed, so a one-line value in a multi-line
                            # block (a re-OCR'd charless paragraph) no longer inherits
                            # the whole block's vertical extent. For a genuine
                            # single-line block the row IS the block, so the old
                            # full-height contract is unchanged.
                            lx1, ly1, lx2, ly2 = line_rects[0]
                            rl, rt, rw, rh = lx1, ly1, lx2 - lx1, ly2 - ly1
                    else:
                        line_rects = _charsless_block_line_rects(
                            block, block_text, visual_occurrence_start, visual_text, prepared_blocks, document_line_height
                        )
                        if line_rects is not None:
                            span_proven = True
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
                            else:
                                # Last narrowing before the whole-block slab:
                                # tight rects for the span's proven glyph runs
                                # plus measured row bands for the unproven
                                # remainder (a handwritten fill on a line the
                                # char engine skipped, bounded by the nearest
                                # proven boxes around it). No x-crop evidence
                                # is claimed (crop_span stays None).
                                mixed_rects = _span_rects_with_row_bands(
                                    block,
                                    block_text,
                                    visual_occurrence_start,
                                    visual_occurrence_start + len(visual_text),
                                    document_line_height,
                                )
                                if mixed_rects is not None:
                                    line_rects = mixed_rects
                                    if len(mixed_rects) == 1:
                                        lx1, ly1, lx2, ly2 = mixed_rects[0]
                                        rl, rt, rw, rh = lx1, ly1, lx2 - lx1, ly2 - ly1
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
                            sub_region = SensitiveRegion(
                                text=visual_text,
                                entity_type=contextual_type,
                                left=lx1,
                                top=ly1,
                                width=lx2 - lx1,
                                height=ly2 - ly1,
                                confidence=getattr(block, "confidence", None),
                                source=region_source,
                            )
                            if span_proven:
                                span_proven_region_ids.add(id(sub_region))
                            entity_regions.append((
                                sub_region,
                                has_position_evidence,
                                not has_position_evidence,
                            ))
                        logger.debug(
                            "MATCH '%s' in '%s...' across %d lines",
                            entity_text, block_text[:20], len(line_rects),
                        )
                    else:
                        # A whole-block fallback inherits the block polygon's height; on a
                        # tilted scan that polygon can collapse to a sliver (the date
                        # 2016年12月20号 came back 4px tall) and then mask only a fraction of
                        # the glyphs — a partial-coverage LEAK. A text row is never shorter
                        # than the page's line grid, so a fallback height below it cannot be
                        # covering the line: grow to the document row height about the box's
                        # y-center. Only the unproven fallback (span_proven is False); a
                        # proven char-box rect already carries its own grown row height.
                        if (
                            not span_proven
                            and document_line_height
                            and rh < document_line_height
                        ):
                            _cy = rt + rh / 2
                            rt = int(_cy - document_line_height / 2)
                            rh = int(document_line_height)
                        # An amount's numeral run must not be cut: grow the box left over
                        # an adjacent numeral char box the block text misread (壹 of 壹拾万元
                        # read as 票, so HaS began at 拾). Only a char-box-proven crop.
                        if normalized_type == "AMOUNT" and crop_span is not None:
                            rl, rw = _extend_amount_left_over_numerals(block, rl, rw, rt, rh)
                        single_region = SensitiveRegion(
                            text=visual_text,
                            entity_type=contextual_type,
                            left=rl,
                            top=rt,
                            width=rw,
                            height=rh,
                            confidence=getattr(block, "confidence", None),
                            source=region_source,
                        )
                        if span_proven:
                            span_proven_region_ids.add(id(single_region))
                        entity_regions.append((
                            single_region,
                            has_position_evidence,
                            not has_position_evidence,
                        ))
                        logger.debug(
                            "MATCH '%s' in '%s...' @ (%d, %d, %d, %d)",
                            entity_text, block_text[:20], rl, rt, rw, rh,
                        )
                matched = True
                continue

            # Same amount value in a different display form — full/half-width
            # currency and separator variants (￥1431400.00元 vs 1431400，00). Never on a
            # RE-DERIVED line (recovered=True): HaS did not tag it an amount, so a digit
            # coincidence must not whole-mask a '暂估面积100' area line as the money 100元.
            if (
                normalized_type == "AMOUNT"
                and not getattr(block, "recovered", False)
                and _is_same_amount_value_block(entity_text, block_text)
            ):
                entity_regions.append((
                    SensitiveRegion(
                        text=block_text.strip() or entity_text,
                        entity_type=normalized_type,
                        left=block.left,
                        top=block.top,
                        width=block.width,
                        height=block.height,
                        confidence=getattr(block, "confidence", None),
                        source=(
                            entity_source
                            if entity_source in {"table_semantic", "form_field_ocr"}
                            else
                            "table_cell_match"
                            if is_table_virtual
                            else "text_match"
                        ),
                    ),
                    # Reviewer-mandated: this whole-block recall is NOT position
                    # evidence — an evidenced flag would let it kill overlapping
                    # positionless claims (a missed-redaction path).
                    False,
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

        # Line-wrap recall for any type: HaS can hand back a wrapped value with the
        # newline removed ('2076年4月8日' from '…2076年' + '4月8日止'), so it is in no
        # single block and the '\n' anchor above never fired. Anchor it by split point.
        if not matched:
            cross_split = _match_cross_block_split(
                entity_text, normalized_type, prepared_blocks, document_line_height
            )
            if cross_split:
                regions.extend(cross_split)
                matched = True

        # Fallback: search in original (unexpanded) blocks
        if not matched and normalized_type == "AMOUNT" and not _digit_retry:
            # Line-wrap recall: the value's tail glyph wrapped to the next OCR
            # line ('…(￥360000' / '元)…', 0712 房屋合同), so the full entity
            # text exists in no single block. An AMOUNT's sensitive payload IS
            # its digit sequence (W3 identity: same digits = same value, cover
            # it); retry the whole precise-match pipeline with the digit
            # payload as the target. len > 2 is the W3 structural guard — a
            # 1-2 digit payload would match any stray numeral.
            digit_payload = _amount_digit_signature(entity_text)
            if len(digit_payload) > 2 and digit_payload != entity_text:
                digit_retry_entities.append({"type": "AMOUNT", "text": digit_payload})

        # (Removed the <table>-block fallback: it boxed the ENTIRE PaddleOCR-VL table
        # region for any value the real blocks did not match — always a whole-table
        # giant box, and it fired on VL-only misreads that PP-Structure read correctly
        # elsewhere (彭鬓 vs the line-OCR's 彭聪, already boxed). Consistent with dropping
        # the <table> block from position matching: geometry is line-OCR only.)

    if digit_retry_entities:
        # Bare-digit amount recall runs on the CONFIDENT blocks only — a re-derived line
        # (recovered=True) must not have its area/count digit re-matched as money.
        regions.extend(
            match_entities_to_ocr(
                [b for b in ocr_blocks if not getattr(b, "recovered", False)],
                digit_retry_entities,
                _digit_retry=True,
            )
        )

    # Org-name propagation to seal-garbled occurrences. The NER tags the clean
    # copy ("信尔胜机械（江苏）有限公司"); a copy read THROUGH a red 公章 comes back
    # corrupted ("信尔胜机械汽承合同特限公") — same firm, past the fuzzy ratio, and
    # skipped once the clean copy matched. Its DISTINCTIVE CORE ("信尔胜机械")
    # survives the garble and is specific enough that a block carrying it IS that
    # org. Propagate the model-detected org type onto every block holding the
    # core. Anchored on the NER's own detection — no new model, no embedding, no
    # magic threshold (containment of a company's proper name). Dedup collapses
    # the clean copy's duplicate; the garbled block gains its box.
    # (full_name, core) for orgs whose name has a strippable generic tail — a
    # proper "distinctive head + 地名/公司-type suffix" (信尔胜机械 | （江苏）有限
    # 公司). A name with no such tail (a bare mark like "NVIDIA"/"FIADOR" where
    # core==full) is NOT propagated: its clean occurrences are already matched
    # exactly, and propagating a short generic string would flood the page.
    propagate: list[tuple[str, str]] = []
    for entity in entities:
        etext = _strip_vl_math_markup(entity.get("text", "")).strip()
        if not etext or _canonical_image_text_type(entity.get("type", "UNKNOWN")) != "INSTITUTION_NAME":
            continue
        core = _org_distinctive_core(etext)
        if len(core) >= _ORG_CORE_MIN_LEN and core != etext:
            propagate.append((etext, core))
    for full_name, core in propagate:
        for block, block_text, _is_table_virtual in prepared_blocks:
            # Only the GARBLED/partial occurrence: a block that carries the core
            # but not the full name (a copy the exact match already covered still
            # holds the full name — skip it, dedup would only re-add a twin).
            if block_text.startswith("<table") or core not in block_text or full_name in block_text:
                continue
            # Crop to the core's own glyphs when the block has char boxes. A block read
            # WITH char boxes (乙方：信尔胜机械（江苏）有限公 — missing 司, so it fails the
            # full_name test above and reaches here) would otherwise mask its WHOLE
            # width and pull the 乙方：field label into the box. Only a truly charless
            # stamp-garbled block (no glyph geometry) falls back to whole-block, where
            # masking all of it is exactly right. Same char-box geometry as main match.
            core_start = block_text.find(core)
            rects = _entity_char_box_line_rects(
                block, block_text, core_start, core_start + len(core)
            )
            spans = (
                [(rx1, ry1, rx2 - rx1, ry2 - ry1) for (rx1, ry1, rx2, ry2) in rects]
                if rects
                else [(block.left, block.top, block.width, block.height)]
            )
            for left, top, width, height in spans:
                regions.append(SensitiveRegion(
                    text=core,
                    entity_type="INSTITUTION_NAME",
                    left=left,
                    top=top,
                    width=width,
                    height=height,
                    confidence=_ORG_CORE_PROPAGATION_CONFIDENCE,
                    source="org_core_propagation",
                ))
            logger.debug("PROPAGATE org core '%s' -> block '%s...'", core, block_text[:20])

    regions = _prune_looser_same_text_boxes(regions, span_proven_region_ids)

    deduped_regions = _dedupe_ocr_regions(regions)
    logger.info("Matched %d entities to OCR blocks (%d after dedupe)", len(regions), len(deduped_regions))
    return deduped_regions
