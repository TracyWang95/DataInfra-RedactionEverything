"""R8: self-calibrated line-height ratio (#7), block-local em floor (F3),
height-evidence collapse detection (F5), and the sub-em line-break threshold
(F6). Every assertion is a coverage-monotone one: the calibrated ratio only
ever RAISES the row height above the current 1.5 floor, block-local em only
lifts, and the wrap threshold only MERGES sub-em jitter (never under-covers a
real wrap). Pure geometry, offline.
"""
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.ocr_cjk_geometry import (
    _CJK_LINE_HEIGHT_RATIO,
    _char_rows,
    _document_line_height,
    _median_single_cjk_width,
)
from app.services.vision.ocr_entity_match import match_entities_to_ocr


def _multirow_cjk_block(pitch: int, em: int = 20, n_rows: int = 3, top: int = 100) -> OCRTextBlock:
    """A block of n_rows identical CJK rows whose baseline pitch (center-to-center
    spacing) is `pitch` and whose glyph em (box width) is `em`."""
    chars = []
    for r in range(n_rows):
        y1 = top + r * pitch
        for i, c in enumerate("甲乙丙"):
            chars.append({"c": c, "x1": 100 + i * em, "y1": y1, "x2": 100 + i * em + em, "y2": y1 + em})
    bottom = top + (n_rows - 1) * pitch + em
    poly = [[100, top], [100 + 3 * em, top], [100 + 3 * em, bottom], [100, bottom]]
    return OCRTextBlock(text="甲乙丙" * n_rows, polygon=poly, confidence=0.9, chars=chars)


# --------------------------------------------------------------------------- #
# #7 — the 1.5 constant becomes a self-calibrated, floor-clamped ratio
# --------------------------------------------------------------------------- #

def test_ocr_line_height_ratio_floors_when_real_pitch_below_1_5() -> None:
    # Real un-collapsed rows measure a tight pitch/em = 1.2. The calibrated
    # ratio must NOT drop to 1.2 (that would under-cover collapsed rows vs the
    # current 1.5 floor); it is clamped up to the 1.5 floor.
    block = _multirow_cjk_block(pitch=24, em=20)  # 24/20 = 1.2
    height = _document_line_height([block])
    assert height == 20 * _CJK_LINE_HEIGHT_RATIO == 30.0
    assert height != 24.0  # never the raw sub-floor measurement


def test_ocr_line_height_ratio_raises_when_real_pitch_above_1_5() -> None:
    # Real rows measure pitch/em = 1.8. Calibration RAISES coverage above the
    # 1.5 floor so collapsed rows on this page grow to the real line height.
    block = _multirow_cjk_block(pitch=36, em=20)  # 36/20 = 1.8
    height = _document_line_height([block])
    assert height == 36.0  # 20 * 1.8, not the old constant 20 * 1.5 = 30


def test_ocr_fully_collapsed_page_falls_back_to_floor_ratio() -> None:
    # Every row piled onto one baseline (pitch 0). No real pitch is measurable,
    # so the collapsed (sub-em) spacings must NOT drag the ratio below the
    # floor — the page falls back to the larger 1.5 floor.
    block = _multirow_cjk_block(pitch=0, em=20)  # all rows share one center
    height = _document_line_height([block])
    assert height == 20 * _CJK_LINE_HEIGHT_RATIO == 30.0


def test_ocr_calibrated_ratio_grows_collapsed_nonchar_row_end_to_end() -> None:
    # End-to-end: a page whose real CJK rows measure pitch/em = 1.8, plus a
    # separate collapsed all-DIGIT value (no CJK em of its own, so it depends
    # purely on the page grid). The value's row must grow to the calibrated
    # 1.8 line height, not the old 1.5 floor.
    context = _multirow_cjk_block(pitch=36, em=20)  # calibrates ratio to 1.8
    digits = "1234567890"
    value = OCRTextBlock(
        text=digits,
        polygon=[[100, 380], [320, 380], [320, 440], [100, 440]],
        confidence=0.95,
        # collapsed 3px band, centered in the 60px block
        chars=[{"c": d, "x1": 100 + i * 20, "y1": 408, "x2": 120 + i * 20, "y2": 411}
               for i, d in enumerate(digits)],
    )
    regions = match_entities_to_ocr([context, value], [{"type": "ID_CARD", "text": digits}])
    hit = [r for r in regions if r.text == digits]
    assert len(hit) == 1
    # 20 * 1.8 = 36; the old 1.5 floor would give only 30
    assert hit[0].height >= 35, f"calibrated grid not applied: height={hit[0].height}"


# --------------------------------------------------------------------------- #
# F3 — block-local em lifts a non-CJK value's row to its label's font size
# --------------------------------------------------------------------------- #

def test_ocr_block_local_em_lifts_pure_digit_value_row() -> None:
    # A block carries a BIG-font CJK label (编号, em=40) and a pure-digit value.
    # The digit span has no CJK em of its own, and the page grid is set by the
    # small body text — but the value is rendered at the label's big size, so
    # its row must grow to the block-local em, not the small page grid.
    body = OCRTextBlock(
        text="一二三四五六七八九十",
        polygon=[[100, 300], [300, 300], [300, 320], [100, 320]],
        confidence=0.95,
        chars=[{"c": c, "x1": 100 + i * 20, "y1": 300, "x2": 120 + i * 20, "y2": 320}
               for i, c in enumerate("一二三四五六七八九十")],
    )
    digits = "1234567890"
    label_chars = [
        {"c": "编", "x1": 100, "y1": 100, "x2": 140, "y2": 140},
        {"c": "号", "x1": 140, "y1": 100, "x2": 180, "y2": 140},
    ]
    # digits rendered big too, but their char band collapsed to a 3px sliver
    digit_chars = [{"c": d, "x1": 180 + i * 20, "y1": 118, "x2": 200 + i * 20, "y2": 121}
                   for i, d in enumerate(digits)]
    label = OCRTextBlock(
        text="编号" + digits,
        polygon=[[100, 90], [380, 90], [380, 165], [100, 165]],
        confidence=0.95,
        chars=label_chars + digit_chars,
    )
    regions = match_entities_to_ocr([body, label], [{"type": "ID_CARD", "text": digits}])
    hit = [r for r in regions if r.text == digits]
    assert len(hit) == 1
    # block-local em 40 -> 40*1.5 = 60; the small page grid (20*1.5=30) must NOT
    # win. Old code (no block em) would clamp the digit row to the page grid.
    assert hit[0].height >= 55, f"block-local em not applied: height={hit[0].height}"


# --------------------------------------------------------------------------- #
# F6 — a real wrap resets by >= one em; sub-em jitter stays one row
# --------------------------------------------------------------------------- #

def test_ocr_char_rows_splits_real_wrap_by_full_em_reset() -> None:
    # Reading order resets leftward by 40px (>= em 20): a genuine line break.
    chars = [{"c": c, "x1": x, "y1": 10, "x2": x + 20, "y2": 30}
             for c, x in [("甲", 100), ("乙", 120), ("丙", 140), ("丁", 100)]]
    assert len(_char_rows(chars)) == 2


def test_ocr_char_rows_keeps_subem_jitter_on_one_row() -> None:
    # The last box steps back 2px (< em 20): in-row jitter, NOT a wrap. The old
    # any-reset rule split it into two rows; F6 keeps it one row so the row rect
    # is the tight union of all four glyphs (covers every glyph, no full-width
    # wrap-fill over the neighbouring column).
    chars = [{"c": c, "x1": x, "y1": 10, "x2": x + 20, "y2": 30}
             for c, x in [("甲", 100), ("乙", 120), ("丙", 140), ("丁", 138)]]
    assert len(_char_rows(chars)) == 1


def test_ocr_char_rows_no_em_falls_back_to_any_reset_split() -> None:
    # No CJK glyph -> no measurable em -> keep the current "any reset splits"
    # behaviour (more splits = over-coverage safe). Latin boxes, 2px reset.
    chars = [{"c": c, "x1": x, "y1": 10, "x2": x + 20, "y2": 30}
             for c, x in [("A", 100), ("B", 120), ("C", 140), ("D", 138)]]
    assert _median_single_cjk_width(chars) is None
    assert len(_char_rows(chars)) == 2


# --------------------------------------------------------------------------- #
# F5 — collapse is judged by band height, not y-variance; a tilted sliver grows
# --------------------------------------------------------------------------- #

def test_ocr_tilted_collapsed_sliver_still_grows_to_row_height() -> None:
    # A tilted collapsed band: each glyph sits on a slightly different y (real
    # y-VARIANCE), but every band is a 3px sliver (band << em*ratio). A
    # variance-based collapse test would wrongly conclude "not collapsed" and
    # skip the grow, leaking a readable sliver. Height evidence must still grow.
    text = "甲乙丙丁"
    chars = [{"c": c, "x1": 100 + i * 20, "y1": 100 + i, "x2": 120 + i * 20, "y2": 103 + i}
             for i, c in enumerate(text)]
    block = OCRTextBlock(
        text=text,
        polygon=[[100, 90], [180, 90], [180, 150], [100, 150]],
        confidence=0.95,
        chars=chars,
    )
    regions = match_entities_to_ocr([block], [{"type": "PERSON", "text": text}])
    assert len(regions) == 1
    # em 20 -> row height 30; the 3px sliver must be grown well past it
    assert regions[0].height >= 25, f"tilted sliver not grown: height={regions[0].height}"
