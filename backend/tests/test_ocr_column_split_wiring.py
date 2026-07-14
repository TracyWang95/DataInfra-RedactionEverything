"""Wiring of the merged double-column splitter into the entity↔OCR matcher.

PaddleOCR-VL sometimes MERGES two side-by-side columns into ONE block: every
char keeps its own x, but y collapses to the whole block's range, and the VL
text label can even list the two columns' groups in an order that disagrees
with the char boxes' left→right x-order. A value that lives entirely in one
column then aligns across the gutter and gets masked as the FULL-WIDTH slab —
covering the neighbouring column's field/label.

The offline core ``_column_split_char_boxes`` already splits a block's chars
into per-column groups by the self-calibrated em-gutter (see
test_ocr_column_split.py). Here we test the WIRING: match_entities_to_ocr, when
the ``REDACT_OCR_COLUMN_SPLIT`` gate is on, feeds each column group downstream
as its own sub-block (original block always kept), so a per-column value matches
its own column's tight char boxes and the full-width twin is dropped by the
existing prune/dedupe.

Pure geometry over synthetic char-box dicts, offline, no GPU. The gate defaults
OFF, so the un-split baseline (asserted first) is the shipped behaviour.
"""
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.ocr_entity_match import _column_split_sub_blocks
from app.services.vision.ocr_pipeline import match_entities_to_ocr


def _c(ch: str, x1: int, x2: int, y1: int = 100, y2: int = 140) -> dict:
    """A char box with its own x and the shared (merged-block) y band."""
    return {"c": ch, "x1": x1, "y1": y1, "x2": x2, "y2": y2}


def _col(text: str, x0: int, width: int = 20) -> list[dict]:
    boxes = []
    x = x0
    for ch in text:
        boxes.append(_c(ch, x, x + width))
        x += width
    return boxes


def _merged_double_column_block() -> tuple[OCRTextBlock, list[dict]]:
    """A merged 2-column block: col A '号3377' @x100.., col B '号5588' after a
    wide gutter. The VL text label lists the columns in the REVERSED order
    (col B group before col A group) — a real merge pathology — so col A's
    value '3377' aligns across the gutter and over-covers without a split."""
    col_a = _col("号3377", 100)          # x 100..200 (值 3377 @ 120..200)
    col_b = _col("号5588", 100 + 5 * 20 + 160)  # gutter 160 px >> em 20
    chars = col_a + col_b
    xs = [x for c in chars for x in (c["x1"], c["x2"])]
    polygon = [[min(xs), 100], [max(xs), 100], [max(xs), 140], [min(xs), 140]]
    # Label lists col B's group first, then col A's — disagrees with x-order.
    label = "号5588号3377"
    return OCRTextBlock(text=label, polygon=polygon, confidence=0.98, chars=chars), chars


# --- baseline: the un-split matcher over-covers one column's value -----------

def test_baseline_merged_column_value_overcovers_full_width() -> None:
    """Without the split (gate default OFF), col A's value '3377' is masked as a
    full-width slab spanning the gutter onto col B — the bug the wiring fixes."""
    block, _chars = _merged_double_column_block()
    regions = match_entities_to_ocr([block], [{"type": "ID_CARD", "text": "3377"}])
    assert len(regions) == 1
    # Full block width (100..380 = 280 px) — over-covers the gutter + col B.
    assert regions[0].width > 200


# --- wired: each column's value gets its own tight per-column box -------------

def test_column_split_gives_each_value_its_own_tight_box(monkeypatch) -> None:
    monkeypatch.setenv("REDACT_OCR_COLUMN_SPLIT", "1")
    block, _chars = _merged_double_column_block()
    regions = match_entities_to_ocr(
        [block],
        [{"type": "ID_CARD", "text": "3377"}, {"type": "ID_CARD", "text": "5588"}],
    )
    by_text = {}
    for r in regions:
        by_text.setdefault(r.text, []).append(r)
    assert "3377" in by_text and "5588" in by_text
    # Each value keeps exactly one box after prune/dedupe, tight to its own
    # column (value is 4 glyphs × 20 px = 80 px), NOT the full-width slab.
    box_a = min(by_text["3377"], key=lambda r: r.width)
    box_b = min(by_text["5588"], key=lambda r: r.width)
    assert box_a.width <= 100  # col A tight, no gutter bleed
    assert box_b.width <= 100  # col B tight
    # The two columns' boxes are disjoint in x (each stays in its own column).
    assert box_a.left + box_a.width <= box_b.left


# --- single-column block is untouched by the wiring --------------------------

def test_single_column_block_unaffected_by_split(monkeypatch) -> None:
    monkeypatch.setenv("REDACT_OCR_COLUMN_SPLIT", "1")
    chars = _col("号3377", 100)
    xs = [x for c in chars for x in (c["x1"], c["x2"])]
    block = OCRTextBlock(
        text="号3377",
        polygon=[[min(xs), 100], [max(xs), 100], [max(xs), 140], [min(xs), 140]],
        confidence=0.98,
        chars=chars,
    )
    # No em-wide gutter -> one column -> no sub-blocks emitted.
    assert _column_split_sub_blocks(block) == []
    regions = match_entities_to_ocr([block], [{"type": "ID_CARD", "text": "3377"}])
    assert len(regions) == 1
    assert regions[0].width <= 100


# --- the sub-block helper: geometry contract ---------------------------------

def test_sub_blocks_keep_original_y_and_split_x(monkeypatch) -> None:
    block, _chars = _merged_double_column_block()
    subs = _column_split_sub_blocks(block)
    assert len(subs) == 2
    # y range is the ORIGINAL block's (split only touches x — no y produced).
    for sub in subs:
        assert sub.top == block.top
        assert sub.height == block.height
    # x-extents are disjoint and ordered left→right; text is the group's chars.
    left_sub, right_sub = sorted(subs, key=lambda b: b.left)
    assert left_sub.left + left_sub.width <= right_sub.left
    assert left_sub.text == "号3377"
    assert right_sub.text == "号5588"
