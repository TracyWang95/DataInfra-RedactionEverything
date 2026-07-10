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


# CJK body text is typeset at a line height of ~1.3x the glyph em (the standard
# full-width line-height ratio). On a phone photo EVERY vertical char-box signal
# is destroyed — the y-band collapses AND the centers pile into one line so the
# height, the position and even the tilt are all unrecoverable; only the x-extent
# survives. So the em (glyph width) is the one trustworthy size, and this ratio is
# the single unavoidable constant that turns it into the row height that covers
# the ink with its leading (the bare em alone leaves the feet poking out).
_CJK_LINE_HEIGHT_RATIO = 1.5


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


def _document_line_height(blocks: list[OCRTextBlock]) -> float | None:
    """Uniform text-row height for the whole page: the CJK glyph em scaled to the
    typeset line height.

    The em is the median WIDTH of single CJK glyph boxes (see
    _median_single_cjk_width). One page-level value → every box is the same
    height, immune to any single block's loose / tilted / multi-line polygon,
    which is what made the wrapped 云A856Z8号 and 日 tower while 小空山7号 read flat.
    """
    all_chars = [c for block in blocks for c in (getattr(block, "chars", None) or [])]
    em = _median_single_cjk_width(all_chars)
    return None if em is None else em * _CJK_LINE_HEIGHT_RATIO


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
        # This entity's own glyph size, so a large-font header/title (court name
        # 昆明市盘龙区人民法院, 民事判决书) is not flattened to the body line grid.
        # The em is the median WIDTH of THIS entity's single-CJK char boxes — the
        # same charless-safe signal as _document_line_height, just entity-local. A
        # no-CJK value (bank account, all Latin) has no em here and keeps the body
        # grid — byte-identical to before — which is what stops tall Latin glyphs
        # leaking (per-char sized them by width, and Latin width << Latin height).
        entity_em = _median_single_cjk_width(span_boxes)
        row_line_height = line_height
        if entity_em is not None:
            entity_line_height = entity_em * _CJK_LINE_HEIGHT_RATIO
            row_line_height = (
                entity_line_height
                if row_line_height is None
                else max(row_line_height, entity_line_height)
            )
        if row_line_height is not None and row_line_height > 0:
            # Document line grid, floored by THIS entity's own font: the page em
            # (see _document_line_height) is a floor for body & Latin, the entity
            # em lifts big headers. A single block's polygon cannot state its row
            # height reliably — loose, tilt-inflated, or (multi-line) the line
            # PITCH not the glyph height — which is why the wrapped 云A856Z8号 and
            # 日 towered while 小空山7号 read flat. Clamped to the block below.
            row_h = min(float(block_bottom - block_top), float(row_line_height))
        else:
            # No page grid (degenerate page with no adjacent CJK pair — never the
            # real pipeline, which always threads one in): full block polygon
            # height, grown but never trimmed, so coverage is never cut on a guess.
            row_h = float(block_bottom - block_top)
        if row_h > 0:
            grown: list[tuple[int, int, int, int]] = []
            for x1r, y1r, x2r, y2r in rects:
                # Grow the (often y-collapsed) char band up to the row height about
                # its center, but never shrink below the chars' own y-extent.
                cy = (y1r + y2r) / 2
                y1g = min(y1r, int(cy - row_h / 2))
                y2g = max(y2r, int(cy + row_h / 2))
                grown.append((x1r, max(block_top, y1g), x2r, min(block_bottom, y2g)))
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


def _char_rows(chars: list) -> list[list[dict]]:
    """Split a reading-ordered char stream into text rows.

    Same identity as _entity_char_box_line_rects: a row break is where reading
    order resets leftward (the next box STARTS left of the previous box's
    start). Holds on tilted photos where y tests would fuse adjacent rows.
    """
    rows: list[list[dict]] = []
    current: list[dict] = []
    previous_x1: float | None = None
    for box in chars:
        x1 = float(box["x1"])
        if current and previous_x1 is not None and x1 < previous_x1:
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
