"""Entity-to-OCR matching: attach detected values to OCR boxes.

Split out of ocr_pipeline.py (which stays the public facade): visual match
span selection, char-box-proven value crops, chars-less paragraph narrowing,
strict/isolated-token rules, fuzzy and table fallbacks, and spatial region
dedupe.
"""
from __future__ import annotations

import logging
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
    _document_line_height,
    _entity_char_box_line_rects,
    _entity_span_char_boxes,  # noqa: F401
    _fold_glyph,  # noqa: F401
    _glyph_alignment,
    _median_single_cjk_width,  # noqa: F401
    _region_cjk_em,
    _span_rects_with_row_bands,
)
from app.services.vision.ocr_table_semantics import (
    _amount_digit_signature,
    _amount_value_signature,
    _block_search_text,
    extract_table_cells,
)
from app.services.vision.ocr_tuning import (
    _FUZZY_MATCH_BLOCK_LEN_FLOOR,
    _FUZZY_MATCH_BLOCK_LEN_MULT,
    _FUZZY_MATCH_CONFIDENCE,
    _FUZZY_MATCH_MIN_ENTITY_LEN,
    _FUZZY_MATCH_RATIO,
    _NER_DEFAULT_MIN_LEN,
    _NER_MIN_LEN_BY_TYPE,
    _TABLE_FALLBACK_CONFIDENCE,
)

logger = logging.getLogger(__name__)


def _is_low_signal_vision_entity(entity_type: str, entity_text: str) -> bool:
    compact = _compact_text(entity_text)
    if not compact:
        return True
    return False


def _entity_type_from_block_context(entity_type: str, entity_text: str, block_text: str) -> str | None:
    return _canonical_image_text_type(entity_type)


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
) -> list[SensitiveRegion]:
    """Keep the tightest box among same-type, same-text, overlapping regions.

    One value can be localized more than once: a garbled handwritten ID matches
    both its own right-column glyphs (tight) AND — because the char alignment
    strays across a merged two-column OCR block — the whole row (拍照保姆合同:
    身份证号码 0.734 page-wide). Same text ⇒ same value, so the tightest box
    already covers its glyphs; the wider twin is redundant over-coverage that
    bleeds onto the other column's field and labels. Drop it.

    Leak-safe: only boxes that share the SAME text AND overlap are collapsed, so
    the surviving tight box covers this value's glyphs; every other field keeps
    its own box. A value repeated elsewhere on the page (non-overlapping) is
    untouched.
    """
    if len(regions) <= 1:
        return regions
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
            ):
                drop_ids.add(id(region))
                logger.debug(
                    "Dropped looser same-text box for '%s' (w=%d) — tighter twin (w=%d) covers it",
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


def _is_same_amount_value_block(entity_text: str, block_text: str) -> bool:
    """Same amount value in a different display form (￥1431400.00元 vs 1431400，00).

    Pure digit-sequence identity over the block's ENTIRE digit content: the
    block renders exactly the number the entity carries, with divergent
    grouping/currency/unit decoration. No format charset, no digit-count
    window — digits that coincide with a detected amount ARE that number on
    the page, so matching can only add cover (over-mask), never uncover.
    Blocks mixing other digits (running text with several numbers) never
    match: their digit sequence differs.
    """
    entity_signature = _amount_value_signature(entity_text)
    if not entity_signature:
        return False
    return _amount_value_signature(block_text) == entity_signature


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
                confidence=1.0,
                source="text_match",
            ))
    return out


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
                    # The matched span IS the visual span. The old 大写/小写
                    # pair word-lookup is gone: the main HaS query's dual
                    # labels (金额+大写金额) tag both renderings of a paired
                    # amount independently (5 layout variants x2 runs, 100%),
                    # so each side carries its own box with no lookback rule.
                    visual_text, visual_occurrence_start = entity_text, occurrence_start
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
                    if line_rects is not None:
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

    if digit_retry_entities:
        regions.extend(
            match_entities_to_ocr(ocr_blocks, digit_retry_entities, _digit_retry=True)
        )

    regions = _prune_looser_same_text_boxes(regions)

    deduped_regions = _dedupe_ocr_regions(regions)
    logger.info("Matched %d entities to OCR blocks (%d after dedupe)", len(regions), len(deduped_regions))
    return deduped_regions
