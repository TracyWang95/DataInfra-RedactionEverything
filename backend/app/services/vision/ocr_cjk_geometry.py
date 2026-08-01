"""CJK / char-box geometry for OCR↔entity matching.

Pure coordinate/width geometry split out of ocr_entity_match.py (which
re-exports these names and stays the matching facade): glyph width-folding,
the single-CJK em width, the page / entity line-height grid, proven char-box
span recovery, per-line char-box rects, and the region em measurement. No
matching rules or thresholds live here — only geometry over OCR char boxes.
"""
from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

from app.services.ocr_has_vision_service import OCRTextBlock, SensitiveRegion
from app.services.vision.has_text_payload import _compact_text


def _fold_glyph(glyph: str) -> str:
    """Width-fold one glyph (NFKC), kept only when it stays a single glyph."""
    folded = unicodedata.normalize("NFKC", glyph)
    return folded if len(folded) == 1 else glyph


# CJK body text is typeset at a line height of ~1.3-1.5x the glyph em. On a phone
# photo EVERY vertical char-box signal is destroyed — the y-band collapses AND the
# centers pile into one line so the height, the position and even the tilt are all
# unrecoverable; only the x-extent survives. So the em (glyph width) is the one
# trustworthy size, and a line-height ratio turns it into the row height that
# covers the ink with its leading (the bare em alone leaves the feet poking out).
#
# This is the FLOOR ratio, not a fixed constant: _document_line_height calibrates
# the real ratio per document from the un-collapsed rows' measured baseline pitch
# and only ever CLAMPS UP to this floor (calibration may raise coverage, never
# lower it). A fully-collapsed page — no measurable pitch — falls back to this
# floor, byte-identical to the old constant, so coverage is never cut on a guess.
_CJK_LINE_HEIGHT_RATIO = 1.5


def _row_break(x1: float, previous_x1: float | None, em: float | None) -> bool:
    """Whether a char box starting at x1 opens a new text row after previous_x1.

    A real line wrap resets reading order leftward by ~a full line width — always
    at least one glyph em. Sub-em leftward steps are in-row jitter (a tilted photo,
    the word engine emitting a wide glyph's box a hair left of its neighbour) and
    must NOT split the row, or the row rect fragments and each fragment gets the
    multi-line wrap-fill to the block edge (over-cover onto the next column). When
    no em is measurable (an all-Latin/digit row) the threshold is unknown, so fall
    back to the old "any leftward reset splits" rule — more splits over-cover, the
    safe direction. Shared by _char_rows and _line_rects_from_span_boxes so the two
    stay in lockstep.
    """
    if previous_x1 is None:
        return False
    if em is None:
        return x1 < previous_x1
    return x1 <= previous_x1 - em


def _median_single_cjk_width(char_boxes) -> float | None:
    """Median WIDTH of single-CJK glyph boxes — the one char-box dimension that
    survives a phone photo (the whole y-band collapses, x stays). Narrow
    punctuation, thin digits and multi-char token boxes are excluded so they
    cannot skew it. None when the sequence carries no measurable CJK glyph (an
    all-Latin value), which callers read as "keep the body grid, don't size by
    width" — Latin glyphs are tall-narrow, so their width is never a height."""
    widths: list[float] = []
    for c in char_boxes:
        if not c:
            continue
        ch = str(c.get("c", ""))
        if not (len(ch) == 1 and "一" <= ch <= "鿿"):
            continue
        x1, x2 = c.get("x1"), c.get("x2")
        if x1 is not None and x2 is not None and x2 > x1:
            widths.append(float(x2 - x1))
    if not widths:
        return None
    widths.sort()
    return widths[len(widths) // 2]


def _calibrated_line_height_ratio(blocks: list[OCRTextBlock], em: float) -> float:
    """The document's real line-height ratio, measured from un-collapsed rows.

    The em (glyph width) survives a phone photo but the leading (line height /
    em) is document-specific — a dense form sits near 1.2, an airy contract near
    1.8. Measure it from the one signal that IS trustworthy on un-collapsed
    pages: the baseline PITCH (adjacent row center-to-center distance), not the
    single-glyph height. Per block, split its chars into rows (_char_rows), take
    the pitches between adjacent row centers, drop collapsed pairs (pitch < em,
    rows piled onto one baseline), and keep the block's MINIMUM real pitch — the
    tightest adjacent spacing IS one line height; anything larger is a paragraph
    gap or a skipped (chars-less) middle row. A block is trusted only when it has
    at least two such spacings, so a lone gap cannot masquerade as the line
    height. Across the trusted blocks take a high quantile (P75, the
    over-coverage direction) and divide by em.

    Clamped to the floor: calibration may only RAISE the ratio above 1.5, never
    lower it, so collapsed rows are never grown to less than the current floor.
    No measurable pitch (a fully-collapsed page) → the floor.
    """
    line_heights: list[float] = []
    for block in blocks:
        chars = getattr(block, "chars", None) or []
        centers: list[float] = []
        for row in _char_rows(chars):
            ys = [
                (float(b["y1"]) + float(b["y2"])) / 2.0
                for b in row
                if b.get("y1") is not None and b.get("y2") is not None
            ]
            if ys:
                centers.append(sum(ys) / len(ys))
        centers.sort()
        pitches = [b - a for a, b in zip(centers, centers[1:], strict=False) if b - a >= em]
        if len(pitches) >= 2:
            line_heights.append(min(pitches))
    if not line_heights:
        return _CJK_LINE_HEIGHT_RATIO
    line_heights.sort()
    p75 = line_heights[min(len(line_heights) - 1, (len(line_heights) * 3) // 4)]
    return max(_CJK_LINE_HEIGHT_RATIO, p75 / em)


def _document_line_height(blocks: list[OCRTextBlock]) -> float | None:
    """Uniform text-row height for the whole page: the CJK glyph em scaled to the
    document's calibrated line-height ratio.

    The em is the median WIDTH of single CJK glyph boxes (see
    _median_single_cjk_width). One page-level value → every box is the same
    height, immune to any single block's loose / tilted / multi-line polygon,
    which is what made the wrapped 云A856Z8号 and 日 tower while 小空山7号 read flat.
    The ratio is calibrated from the real baseline pitch (see
    _calibrated_line_height_ratio), clamped up to the 1.5 floor.
    """
    all_chars = [c for block in blocks for c in (getattr(block, "chars", None) or [])]
    em = _median_single_cjk_width(all_chars)
    if em is None:
        return None
    return em * _calibrated_line_height_ratio(blocks, em)


_FIELD_LABEL_SEPARATORS = ("：", ":")  # full/half-width colon: label→value separator punctuation


def _leading_label_trimmed_start(block, search_text: str, span_start: int, span_end: int) -> int:
    """If a matched span begins with a form field LABEL ("甲方：中海油…"), return the
    text index of the first VALUE glyph so the redaction box hugs the value, not the
    label. A field label is detected purely by geometry: a colon whose right edge is
    followed by a >= one-glyph-em horizontal gutter before the next glyph — the same
    self-calibrated gap rule the column splitter uses. The colon is a separator
    punctuation, NOT a value wordlist. Whether the NER returned the value with or
    without its label prefix is an unstable, payload-drifting property of a 0.6B open-
    vocab model; anchoring the value's left edge to the document's own label/value gap
    decouples the box from that drift. Leak-safe: the start is only pushed RIGHT, past
    a gutter-terminated leading label, never past any value glyph. No char boxes / no
    colon / no gutter after the colon -> returns span_start unchanged (byte-identical).
    """
    chars = getattr(block, "chars", None) or []
    if not chars:
        return span_start
    em = _median_single_cjk_width(chars)
    if em is None:
        return span_start
    alignment = _glyph_alignment(block, search_text, span_start, span_end)
    if alignment is None:
        return span_start
    box_by_glyph, span_glyph_start, span_glyph_end = alignment
    text_index_of_glyph = [i for i, ch in enumerate(search_text) if not ch.isspace()]
    for g in range(span_glyph_start, span_glyph_end - 1):
        if search_text[text_index_of_glyph[g]] not in _FIELD_LABEL_SEPARATORS:
            continue
        colon_box, next_box = box_by_glyph[g], box_by_glyph[g + 1]
        if colon_box is None or next_box is None:
            continue
        if float(next_box["x1"]) - float(colon_box["x2"]) >= em:
            return text_index_of_glyph[g + 1]
    return span_start


def _glyph_alignment(
    block: OCRTextBlock,
    search_text: str,
    span_start: int,
    span_end: int,
) -> tuple[list[dict | None], int, int] | None:
    """Monotone glyph alignment of search_text onto the block's char boxes.

    Returns (box_by_glyph, span_glyph_start, span_glyph_end): one entry per
    non-whitespace glyph of search_text, holding that glyph's proven char box
    or None, plus the span's bounds mapped onto glyph indexes. None when the
    block has no chars or the span maps to no glyphs.
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
    return box_by_glyph, span_glyph_start, span_glyph_end


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
    alignment = _glyph_alignment(block, search_text, span_start, span_end)
    if alignment is None:
        return None
    box_by_glyph, span_glyph_start, span_glyph_end = alignment

    span_boxes = box_by_glyph[span_glyph_start:span_glyph_end]
    # The unique-glyph recovery pairs by identity alone, so a span glyph can
    # grab a box from a DIFFERENT text row (2026's '6' paired with 试用期6个月's
    # box one row up when the span text lacks that context). Char boxes run in
    # reading order — a span's boxes must sit on a non-decreasing row sequence
    # — so keep the longest such subsequence and drop the violators. Same-row
    # out-of-order recoveries (the '27岁' word-engine case the recovery exists
    # for) share a row index and always survive. Identity-based, no thresholds.
    indexed = []
    row_of: dict[int, int] = {}
    for row_index, row in enumerate(_char_rows(getattr(block, "chars", None) or [])):
        for box in row:
            row_of[id(box)] = row_index
    for position, box in enumerate(span_boxes):
        if box is not None and id(box) in row_of:
            indexed.append((position, row_of[id(box)]))
    if any(b[1] < a[1] for a, b in zip(indexed, indexed[1:], strict=False)):
        span_boxes = list(span_boxes)
        length = [1] * len(indexed)
        parent = [-1] * len(indexed)
        for j in range(len(indexed)):
            for k in range(j):
                if indexed[k][1] <= indexed[j][1] and length[k] + 1 > length[j]:
                    length[j] = length[k] + 1
                    parent[j] = k
        cursor = max(range(len(indexed)), key=lambda j: length[j])
        keep: set[int] = set()
        while cursor != -1:
            keep.add(indexed[cursor][0])
            cursor = parent[cursor]
        for position, _row in indexed:
            if position not in keep:
                span_boxes[position] = None

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
    line_height: float | None = None,
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
    return _line_rects_from_span_boxes(block, span_boxes, line_height)


def _line_rects_from_span_boxes(
    block: OCRTextBlock,
    span_boxes: list,
    line_height: float | None = None,
) -> list[tuple[int, int, int, int]] | None:
    """Per-text-line rects built from a span's (possibly gappy) char boxes —
    the geometry half of _entity_char_box_line_rects, shared with the
    partial-proof path (_span_rects_with_row_bands)."""
    # Block em — the wrap threshold shared with _char_rows: a real line break
    # resets leftward by >= one em, sub-em steps are in-row jitter (F6).
    block_em = _median_single_cjk_width(getattr(block, "chars", None) or [])
    rects: list[tuple[int, int, int, int]] = []
    current: tuple[int, int, int, int] | None = None
    previous_x1: float | None = None
    for box in span_boxes:
        if box is None:
            continue
        x1, y1 = float(box["x1"]), float(box["y1"])
        x2, y2 = float(box["x2"]), float(box["y2"])
        if current is not None and _row_break(x1, previous_x1, block_em):
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
        # This entity's own glyph size, so a large-font header/title (court name
        # 昆明市盘龙区人民法院, 民事判决书) is not flattened to the body line grid.
        # The em is the median WIDTH of THIS entity's single-CJK char boxes — the
        # same charless-safe signal as _document_line_height, just entity-local. A
        # no-CJK value (bank account, all Latin) has no em here and keeps the body
        # grid — byte-identical to before — which is what stops tall Latin glyphs
        # leaking (per-char sized them by width, and Latin width << Latin height).
        entity_em = _median_single_cjk_width(span_boxes)
        # F3 — row height is the MAX of every measured floor, adjusted only
        # upward (never below the page grid): the page em grid (line_height),
        # the block-local em (a pure-digit value inside a big-font labelled
        # block inherits the label's font size, which its own charless span
        # cannot state), this entity's own em (lifts a big header off the body
        # grid), and the value's real ink band (never shrink below the glyphs).
        floors = [f for f in (line_height,) if f is not None and f > 0]
        if block_em is not None:
            floors.append(block_em * _CJK_LINE_HEIGHT_RATIO)
        if entity_em is not None:
            floors.append(entity_em * _CJK_LINE_HEIGHT_RATIO)
        ink_band = max(
            (float(b["y2"]) - float(b["y1"]) for b in span_boxes if b is not None),
            default=0.0,
        )
        if ink_band > 0:
            floors.append(ink_band)
        if floors:
            # Grown to the tallest floor and clamped to the block polygon by the
            # per-rect grow below — a single block's polygon cannot state its row
            # height reliably (loose, tilt-inflated, or the multi-line line PITCH),
            # which is why the wrapped 云A856Z8号 and 日 towered while 小空山7号 read
            # flat, so the polygon caps but never sets the row height.
            row_h = max(floors)
        else:
            # No page grid (degenerate page with no adjacent CJK pair — never the
            # real pipeline, which always threads one in): full block polygon
            # height, grown but never trimmed, so coverage is never cut on a guess.
            row_h = float(block_bottom - block_top)
        if row_h > 0:
            # A block polygon shorter than a single glyph is physically impossible for a
            # text line (CJK glyphs are ~square, so a line is at least one em tall) — it
            # is a collapsed read, the date 2016年12月20号 came back as a ~4px sliver, not
            # a trustworthy vertical cap: clamping the grown rect back to it re-flattens
            # the box we just grew. Only then widen the cap to one row about the block's
            # y-center. A plausibly-tall polygon (>= its own em) caps exactly as before,
            # so a block barely shorter than the inflated row estimate is untouched.
            if block_em is not None and (block_bottom - block_top) < block_em:
                _bcy = (block_top + block_bottom) / 2
                cap_top, cap_bottom = int(_bcy - row_h / 2), int(_bcy + row_h / 2)
            else:
                cap_top, cap_bottom = block_top, block_bottom
            grown: list[tuple[int, int, int, int]] = []
            for x1r, y1r, x2r, y2r in rects:
                # F5 — collapse is judged by HEIGHT evidence, not y-variance: a
                # tilted collapsed band has a non-zero y-variance yet its band is
                # a sliver, so it must still grow, while a band that already spans
                # the typeset row height (band >= row_h) has proven its ink covers
                # the line and is left as-is. Grow-only about the chars' own
                # y-center, never shrinking below the band, clamped to the block.
                if y2r - y1r >= row_h:
                    grown.append((x1r, max(cap_top, y1r), x2r, min(cap_bottom, y2r)))
                    continue
                cy = (y1r + y2r) / 2
                y1g = min(y1r, int(cy - row_h / 2))
                y2g = max(y2r, int(cy + row_h / 2))
                grown.append((x1r, max(cap_top, y1g), x2r, min(cap_bottom, y2g)))
            rects = [r for r in grown if r[2] > r[0] and r[3] > r[1]]
    # A wrapped value fills each spanned line to the wrap margin: it broke onto
    # the next line BECAUSE line 1 reached the block's right edge, so line 1 runs
    # from the value start to that right edge, the last line from the left edge
    # to the value end, middle lines the full width. Extend every non-last line
    # rect's right and every non-first line rect's left to the block's own
    # x-range accordingly. This also covers a boundary glyph whose ink overruns
    # its tight OCR char box — the wrapped 2016年1月7日 left its trailing 7 poking
    # past the char-box right edge once the old blunt x-pad was gone.
    if len(rects) > 1 and polygon:
        xs = [int(pt[0]) for pt in polygon if isinstance(pt, (list, tuple)) and len(pt) >= 2]
        if xs:
            block_left_x, block_right_x = min(xs), max(xs)
            rects = [
                (
                    block_left_x if idx > 0 else r[0],
                    r[1],
                    block_right_x if idx < len(rects) - 1 else r[2],
                    r[3],
                )
                for idx, r in enumerate(rects)
            ]
    # Final guard: any rect the grow could not give real height (missing
    # polygon) is dropped so the caller safely masks the whole block rather
    # than emit a zero-height crop.
    return [r for r in rects if r[3] > r[1]] or None


def _column_split_char_boxes(char_boxes: list) -> list[list[dict]]:
    """Split one block's char boxes into columns by the horizontal gutter.

    PaddleOCR-VL sometimes MERGES two side-by-side columns into one block: each
    char keeps its own x, but y collapses to the whole block's range, so a
    matcher's x-span union covers the gutter AND the neighbouring column. The
    columns are separated by a GUTTER — a blank wide enough to hold a full glyph
    slot — while in-column chars sit an advance apart (real photo: gutter 34-41px
    vs in-column advance ~19px). This finds the gutter WITHOUT any hardcoded
    pixel threshold or magic multiplier: the block's own glyph em (the median
    single-CJK char WIDTH, _median_single_cjk_width) is the scale, and an
    inter-char gap >= one em means "the blank can hold >= one full character
    slot" == a deliberate column break. Every gap smaller than an em is
    in-column spacing and stays one column. Multiple em-wide gaps -> multiple
    columns.

    No em (an all-Latin / all-digit block, Latin width is not a typographic em)
    -> return the whole block as one group: the gutter cannot be self-calibrated,
    so the safe move is to over-cover, not to guess a split.

    LEAK-SAFETY: this only ever turns ONE input group into >= 1 output groups;
    it drops no box and shrinks no y (it does not touch y at all). The caller
    ALWAYS unions the original block into the mask, so a mis-split can only ADD
    coverage (each half-value gets its own covered sub-block), never remove it —
    strictly leak-safe, zero under-coverage.

    Boxes are grouped by x position (columns partition x-space), so the input
    order does not matter; groups come out left-to-right. Interior boxes that
    overlap in x (same column, different photo rows) never open a gutter because
    the gap is measured from the current column's running right edge.

     TODO(接线, human main-loop, needs GPU/real docs): call this in the NER
    payload build / matcher BEFORE the x-span union so a merged double-column
    block is fed downstream as per-column sub-blocks (each unioned separately).
    Also verify whether region_detection already emits column-granular blocks —
    if so it is the stronger evidence source and this becomes a fallback only.
    """
    boxes = [
        c for c in char_boxes
        if c and c.get("x1") is not None and c.get("x2") is not None
    ]
    if len(boxes) <= 1:
        return [boxes] if boxes else []
    em = _median_single_cjk_width(boxes)
    if em is None:
        return [boxes]  # no CJK scale -> cannot self-calibrate a gutter; keep whole block
    ordered = sorted(boxes, key=lambda c: float(c["x1"]))
    groups: list[list[dict]] = [[ordered[0]]]
    column_right = float(ordered[0]["x2"])
    for box in ordered[1:]:
        gap = float(box["x1"]) - column_right
        if gap >= em:  # a blank wide enough to hold >= one full glyph slot
            groups.append([box])
            column_right = float(box["x2"])
        else:
            groups[-1].append(box)
            column_right = max(column_right, float(box["x2"]))
    return groups


def _char_rows(chars: list) -> list[list[dict]]:
    """Split a reading-ordered char stream into text rows.

    Same identity as _entity_char_box_line_rects: a row break is where reading
    order resets leftward by at least one glyph em (_row_break) — a full-width
    wrap, not sub-em in-row jitter. Holds on tilted photos where y tests would
    fuse adjacent rows.
    """
    em = _median_single_cjk_width(chars)
    rows: list[list[dict]] = []
    current: list[dict] = []
    previous_x1: float | None = None
    for box in chars:
        x1 = float(box["x1"])
        if current and _row_break(x1, previous_x1, em):
            rows.append(current)
            current = []
        current.append(box)
        previous_x1 = x1
    if current:
        rows.append(current)
    return rows


def _unproven_span_row_band(
    block: OCRTextBlock,
    search_text: str,
    span_start: int,
    span_end: int,
) -> tuple[int, int] | None:
    """Row band (top, bottom) bounding a span NONE of whose glyphs aligned to
    a char box (a handwritten fill on a line the char engine skipped).

    Char boxes run in reading order, which is physical order inside a block —
    the span's ink lies after the nearest proven box BEFORE it and before the
    nearest proven box AFTER it. Bounds are measured neighbour-row edges, not
    grown estimates: the span can extend through its anchor's whole writing
    zone (handwritten fills overshoot the printed glyph band — the 河南新乡市
    descenders poked out below an anchor-height band), and that zone ends
    exactly where the next physical row's ink starts. So band bottom is the
    lowest top edge of the row BELOW the after-anchor's row (block bottom when
    it is the last row), band top the highest bottom edge of the row ABOVE the
    before-anchor's row (block top when it is the first) — the conservative
    end of each measured edge, tilt shifts row edges across x. Both bounds are
    kept outside the anchor's own row ink so the band never shaves it. X
    carries no evidence on the value's own line, so the caller keeps the
    block's x-extent. None without at least one anchor or a real polygon: the
    caller keeps the whole-block mask.
    """
    polygon = getattr(block, "polygon", None) or []
    ys = [int(pt[1]) for pt in polygon if isinstance(pt, (list, tuple)) and len(pt) >= 2]
    if not ys:
        return None
    block_top, block_bottom = min(ys), max(ys)
    alignment = _glyph_alignment(block, search_text, span_start, span_end)
    if alignment is None:
        return None
    box_by_glyph, span_glyph_start, span_glyph_end = alignment
    if any(box is not None for box in box_by_glyph[span_glyph_start:span_glyph_end]):
        return None  # proven glyphs: the crop paths own this span
    before = next(
        (box for box in reversed(box_by_glyph[:span_glyph_start]) if box is not None), None
    )
    after = next((box for box in box_by_glyph[span_glyph_end:] if box is not None), None)
    if before is None and after is None:
        return None
    rows = _char_rows(getattr(block, "chars", None) or [])
    row_of = {id(box): index for index, row in enumerate(rows) for box in row}

    top = float(block_top)
    if before is not None:
        row_index = row_of[id(before)]
        if row_index > 0:
            previous_row = rows[row_index - 1]
            row_ink_top = min(float(box["y1"]) for box in rows[row_index])
            top = max(top, min(min(float(box["y2"]) for box in previous_row), row_ink_top))
    bottom = float(block_bottom)
    if after is not None:
        row_index = row_of[id(after)]
        if row_index < len(rows) - 1:
            next_row = rows[row_index + 1]
            row_ink_bottom = max(float(box["y2"]) for box in rows[row_index])
            bottom = min(
                bottom, max(max(float(box["y1"]) for box in next_row), row_ink_bottom)
            )
    if bottom <= top:
        return None
    return int(top), int(bottom)


def _span_rects_with_row_bands(
    block: OCRTextBlock,
    search_text: str,
    span_start: int,
    span_end: int,
    line_height: float | None,
) -> list[tuple[int, int, int, int]] | None:
    """Rects for a span the proven-crop path rejected (an edge glyph unproven).

    Every span glyph falls in one of two evidence classes: a PROVEN run (its
    char boxes aligned) keeps the ordinary tight line rects; an UNPROVEN
    prefix/suffix run gets a measured row band — its ink lies between the
    adjacent proven glyph inside the span and the nearest proven neighbour
    outside it (reading order == physical order). A run whose two anchors sit
    on one row is pinched by their x edges on that row; otherwise the run may
    continue past the wrap margin, so its row rect runs to the block edge and
    the rows in between, bounded by the anchors' measured row edges, are
    covered by a full-width band (the 试用期 date: 2025年5月 proven on line 1,
    the handwritten 10日起至…止 continuation on line 2 has no char boxes at
    all — line 1 gets its tight rect, line 2 its measured band). All bounds
    are measured char/row coordinates — no estimation, no thresholds. None
    when the block carries no usable evidence; the caller keeps the
    whole-block mask.
    """
    polygon = getattr(block, "polygon", None) or []
    xs = [int(pt[0]) for pt in polygon if isinstance(pt, (list, tuple)) and len(pt) >= 2]
    ys = [int(pt[1]) for pt in polygon if isinstance(pt, (list, tuple)) and len(pt) >= 2]
    if not xs or not ys:
        return None
    block_left, block_right = min(xs), max(xs)
    block_top, block_bottom = min(ys), max(ys)
    alignment = _glyph_alignment(block, search_text, span_start, span_end)
    if alignment is None:
        return None
    box_by_glyph, span_glyph_start, span_glyph_end = alignment
    span = box_by_glyph[span_glyph_start:span_glyph_end]
    if not span:
        return None
    proven = [box for box in span if box is not None]
    if not proven:
        band = _unproven_span_row_band(block, search_text, span_start, span_end)
        if band is None:
            return None
        return [(block_left, band[0], block_right, band[1])]
    rects = _line_rects_from_span_boxes(block, proven, line_height)
    if not rects:
        return None
    rows = _char_rows(getattr(block, "chars", None) or [])
    row_of = {id(box): index for index, row in enumerate(rows) for box in row}
    out = list(rects)

    if span[-1] is None:
        # Unproven suffix: after the last proven span glyph, before the nearest
        # proven neighbour following the span.
        last = next(box for box in reversed(span) if box is not None)
        last_row = row_of.get(id(last))
        after = next((box for box in box_by_glyph[span_glyph_end:] if box is not None), None)
        after_row = row_of.get(id(after)) if after is not None else None
        x1, y1, x2, y2 = out[-1]
        if after is not None and after_row == last_row:
            # Confined to one row between the two anchors: pinch by their x.
            out[-1] = (x1, y1, max(x2, int(float(after["x1"]))), y2)
        else:
            # May continue past the wrap margin onto following rows.
            out[-1] = (x1, y1, block_right, y2)
            band_bottom = float(block_bottom)
            if after_row is not None and last_row is not None and after_row > last_row:
                band_bottom = min(
                    band_bottom, max(float(box["y1"]) for box in rows[after_row])
                )
            if band_bottom > y2:
                out.append((block_left, y2, block_right, int(band_bottom)))

    if span[0] is None:
        # Unproven prefix, mirror of the suffix case.
        first = next(box for box in span if box is not None)
        first_row = row_of.get(id(first))
        before = next(
            (box for box in reversed(box_by_glyph[:span_glyph_start]) if box is not None),
            None,
        )
        before_row = row_of.get(id(before)) if before is not None else None
        x1, y1, x2, y2 = out[0]
        if before is not None and before_row == first_row:
            out[0] = (min(x1, int(float(before["x2"]))), y1, x2, y2)
        else:
            out[0] = (block_left, y1, x2, y2)
            band_top = float(block_top)
            if before_row is not None and first_row is not None and before_row < first_row:
                band_top = max(
                    band_top, min(float(box["y2"]) for box in rows[before_row])
                )
            if y1 > band_top:
                out.insert(0, (block_left, int(band_top), block_right, y1))

    return out


def _region_cjk_em(region: SensitiveRegion, line_blocks: list[OCRTextBlock]) -> float | None:
    """The font em (median single-CJK char WIDTH) of the glyphs under a region —
    its own type size. Used to tell a genuinely large-font row (a title/header,
    wide AND tall) from a body-grid row that is merely tall (a DATE's un-collapsed
    digit boxes): the former's em row height clears the page median, the latter's
    does not. None for an all-Latin value (no CJK glyph to measure)."""
    rl, rt = region.left, region.top
    rr, rb = region.left + region.width, region.top + region.height
    inside = []
    for b in line_blocks:
        for c in (getattr(b, "chars", None) or []):
            x1, x2 = c.get("x1"), c.get("x2")
            y1, y2 = c.get("y1"), c.get("y2")
            if x1 is None or x2 is None or y1 is None or y2 is None:
                continue
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            if rl <= cx <= rr and rt <= cy <= rb:
                inside.append(c)
    return _median_single_cjk_width(inside)
