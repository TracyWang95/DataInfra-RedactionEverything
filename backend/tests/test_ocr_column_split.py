"""Pure-geometry column splitter for merged double-column OCR blocks.

On a phone photo PaddleOCR-VL sometimes MERGES two side-by-side columns into
one block: every char keeps its own x, but y is the whole block's range, so the
matcher's x-span union covers both columns (over-covers the gutter and pulls a
neighbouring column's value into the mask). The columns are separated by a
horizontal GUTTER — a blank wide enough to hold a full character slot — while
in-column chars sit an advance apart. This splitter self-calibrates that gutter
from the block's own glyph em (median single-CJK char WIDTH): an inter-char gap
>= one em is a deliberate column break; anything smaller is in-column spacing.

Every assertion is coverage-safe: the splitter only turns ONE candidate into
>= 1; the caller always unions the ORIGINAL block, so a mis-split can only
ADD coverage, never remove it. All pure geometry over synthetic char-box dicts,
offline, no GPU.
"""
from app.services.vision.ocr_cjk_geometry import (
    _column_split_char_boxes,
    _median_single_cjk_width,
)


def _c(ch: str, x1: int, x2: int, y1: int = 100, y2: int = 140) -> dict:
    """A char box with independent x and a shared (whole-block) y band."""
    return {"c": ch, "x1": x1, "y1": y1, "x2": x2, "y2": y2}


# --- gutter >= em splits, columns do not overlap in x ------------------------

def test_column_split_two_cjk_columns_by_em_gutter() -> None:
    # em (char width) = 20. Col-A three glyphs packed (gap 0); a 40px gutter
    # (>= em, holds >= one full char slot); Col-B three glyphs. Two groups whose
    # x-extents do not overlap — the "ID:A  gutter  ID:B" case.
    col_a = [_c(c, 100 + i * 20, 120 + i * 20) for i, c in enumerate("甲乙丙")]
    col_b = [_c(c, 220 + i * 20, 240 + i * 20) for i, c in enumerate("丁戊己")]
    groups = _column_split_char_boxes(col_a + col_b)
    assert len(groups) == 2
    a_right = max(b["x2"] for b in groups[0])
    b_left = min(b["x1"] for b in groups[1])
    assert a_right <= b_left  # x-extents disjoint


# --- normal single column: every gap < em, never split -----------------------

def test_column_split_single_column_not_split() -> None:
    # A normal long line: all inter-char gaps are 0 (< em 20). No em-wide blank,
    # so no gutter — one group.
    chars = [_c(c, 100 + i * 20, 120 + i * 20) for i, c in enumerate("甲乙丙丁戊己")]
    assert len(_column_split_char_boxes(chars)) == 1


# --- all-Latin: no CJK em to calibrate, fall back to whole block --------------

def test_column_split_all_latin_no_em_falls_back_whole_block() -> None:
    # No CJK glyph -> no measurable em -> the gutter cannot be self-calibrated,
    # so refuse to split even across a big blank (whole block over-covers, which
    # is leak-safe). Mirrors _median_single_cjk_width's charless-value contract.
    col_a = [_c(c, 100 + i * 20, 120 + i * 20) for i, c in enumerate("ID")]
    col_b = [_c(c, 300 + i * 20, 320 + i * 20) for i, c in enumerate("XY")]
    assert _median_single_cjk_width(col_a + col_b) is None
    assert len(_column_split_char_boxes(col_a + col_b)) == 1


# --- two gutters -> three columns --------------------------------------------

def test_column_split_double_gutter_three_columns() -> None:
    col_a = [_c(c, 100 + i * 20, 120 + i * 20) for i, c in enumerate("甲乙")]  # x2=140
    col_b = [_c(c, 200 + i * 20, 220 + i * 20) for i, c in enumerate("丙丁")]  # x1=200, gap 60
    col_c = [_c(c, 300 + i * 20, 320 + i * 20) for i, c in enumerate("戊己")]  # x1=300, gap 60
    assert len(_column_split_char_boxes(col_a + col_b + col_c)) == 3


# --- critical boundary: reproducible around the one-em gutter cutoff ----------

def test_column_split_critical_gutter_is_reproducible() -> None:
    # em = 20, in-column advance (列内字距) = 20 (packed). Gutter gap = 30 =
    # 1.5 × in-column advance, and 30 >= em -> a deliberate split. Deterministic
    # across repeated calls.
    col_a = [_c(c, 100 + i * 20, 120 + i * 20) for i, c in enumerate("甲乙")]  # x2=140
    col_b = [_c(c, 170 + i * 20, 190 + i * 20) for i, c in enumerate("丙丁")]  # x1=170, gap 30
    first = _column_split_char_boxes(col_a + col_b)
    second = _column_split_char_boxes(col_a + col_b)
    assert len(first) == len(second) == 2


def test_column_split_gap_just_below_em_keeps_one_column() -> None:
    # Gutter gap = 19 (< em 20): the blank cannot hold a full char slot, so it is
    # in-column spacing, not a gutter. One group.
    col_a = [_c(c, 100 + i * 20, 120 + i * 20) for i, c in enumerate("甲乙")]  # x2=140
    col_b = [_c(c, 159 + i * 20, 179 + i * 20) for i, c in enumerate("丙丁")]  # x1=159, gap 19
    assert len(_column_split_char_boxes(col_a + col_b)) == 1


def test_column_split_gap_at_em_boundary_splits() -> None:
    # Gutter gap = 20 == em: the inclusive ">= em" cutoff fires -> two groups.
    # Locks the exact, reproducible decision boundary.
    col_a = [_c(c, 100 + i * 20, 120 + i * 20) for i, c in enumerate("甲乙")]  # x2=140
    col_b = [_c(c, 160 + i * 20, 180 + i * 20) for i, c in enumerate("丙丁")]  # x1=160, gap 20
    assert len(_column_split_char_boxes(col_a + col_b)) == 2


# --- degenerate inputs are safe ----------------------------------------------

def test_column_split_empty_and_singleton() -> None:
    assert _column_split_char_boxes([]) == []
    one = [_c("甲", 100, 120)]
    assert _column_split_char_boxes(one) == [one]
