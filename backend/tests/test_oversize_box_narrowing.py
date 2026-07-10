"""Oversize-box fixes: a matched value whose glyphs have no proven char boxes
must not be masked as the whole multi-line paragraph slab.

Real 5090 corpus (2026-07-10, three phone-photo contracts): handwritten values
live in a PaddleOCR-VL paragraph whose PP-Structure char boxes cover only the
printed lines — the value's own line carries zero proven boxes, every proof
path fails, and the region falls back to the full 2-3 row block box.

Three orthogonal fixes under test:
1. VL math markup ($ \\underline{...} $ / \\text{...}) is stripped from both
   the block's authoritative text and the entity text before matching;
2. char boxes recovered by the charless-block re-OCR are attached in reading
   order (the structure engine returns crop lines unordered);
3. a span with zero proven boxes narrows to the row band bounded by the
   nearest proven char boxes before/after it (reading order == physical
   order inside a block); x keeps the block's width — no estimation.
"""
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.has_text_payload import _strip_vl_math_markup
from app.services.vision.ocr_pipeline import match_entities_to_ocr


def _block(text: str, polygon: list, chars: list) -> OCRTextBlock:
    return OCRTextBlock(text=text, polygon=polygon, confidence=0.98, chars=chars)


def _row_chars(text: str, left: int, top: int, bottom: int, width: int = 19) -> list[dict]:
    boxes = []
    cursor = left
    for ch in text:
        boxes.append({"c": ch, "x1": cursor, "y1": top, "x2": cursor + width, "y2": bottom})
        cursor += width
    return boxes


# ---------------------------------------------------------------------------
# Fix 1: VL math markup stripping
# ---------------------------------------------------------------------------

def test_underline_wrapper_stripped() -> None:
    assert _strip_vl_math_markup("试用期 $ \\underline{6} $个月") == "试用期 6个月"


def test_nested_text_command_stripped() -> None:
    assert (
        _strip_vl_math_markup("位于 $ \\underline{\\text{河南新乡市}} $，暂估")
        == "位于 河南新乡市，暂估"
    )


def test_currency_dollar_segments_untouched() -> None:
    # $...$ pairs without a \command{} inside are real content, not markup.
    text = "押金 $100，尾款 $200 现金支付"
    assert _strip_vl_math_markup(text) == text


def test_text_without_dollar_unchanged() -> None:
    text = "本房屋坐落在北京市朝阳区，共18层。"
    assert _strip_vl_math_markup(text) is text


def test_latex_entity_matches_latex_block_text() -> None:
    """Case 3 (劳动合同17): both the HaS entity and the VL block text carry the
    markup; after both-side stripping the entity matches and crops to the
    proven chars instead of failing alignment into a whole-block slab."""
    text = "，自 $ \\underline{2025} $年 $ \\underline{5} $月 $ \\underline{10} $日起"
    chars = _row_chars("，自2025年5月10日起", 100, 500, 530)
    block = _block(text, [[95, 495], [500, 495], [500, 535], [95, 535]], chars)

    regions = match_entities_to_ocr(
        [block], [{"type": "DATE", "text": "$ \\underline{2025} $年 $ \\underline{5} $月"}]
    )

    assert len(regions) == 1
    region = regions[0]
    assert "underline" not in region.text and "$" not in region.text
    # cropped to the 2025年5月 glyphs (chars are proven), not the whole block
    assert region.left > 100 and region.width < 300


# ---------------------------------------------------------------------------
# Fix 3: row band for a span with zero proven char boxes
# ---------------------------------------------------------------------------

# Real block from the 农业种植合作合同书 dump: two-row VL paragraph, chars only
# for the printed glyphs (row 1 right part + row 2); the handwritten value
# 河南新乡市 sits on row 1 with no char boxes at all.
_FARM_BLOCK_TEXT = (
    "乙方用于投资入股的土地位于 $ \\underline{\\text{河南新乡市}} $，"
    "暂估面积100亩（以实际核定面积为准）。"
)
_FARM_BLOCK_POLYGON = [[92, 725], [759, 725], [759, 816], [92, 816]]
_FARM_BLOCK_CHARS = [
    {"c": "，", "x1": 639, "y1": 732, "x2": 644, "y2": 755},
    {"c": "暂", "x1": 651, "y1": 732, "x2": 670, "y2": 755},
    {"c": "估", "x1": 670, "y1": 732, "x2": 690, "y2": 755},
    {"c": "面", "x1": 690, "y1": 732, "x2": 709, "y2": 755},
    {"c": "积", "x1": 704, "y1": 732, "x2": 724, "y2": 755},
    {"c": "/∞", "x1": 731, "y1": 732, "x2": 755, "y2": 755},
    {"c": "亩", "x1": 99, "y1": 787, "x2": 118, "y2": 806},
    {"c": "（", "x1": 128, "y1": 787, "x2": 133, "y2": 806},
    {"c": "以", "x1": 134, "y1": 787, "x2": 152, "y2": 806},
    {"c": "实", "x1": 151, "y1": 787, "x2": 170, "y2": 806},
    {"c": "际", "x1": 173, "y1": 787, "x2": 192, "y2": 806},
    {"c": "核", "x1": 191, "y1": 787, "x2": 210, "y2": 806},
    {"c": "定", "x1": 208, "y1": 787, "x2": 227, "y2": 806},
    {"c": "面", "x1": 226, "y1": 787, "x2": 245, "y2": 806},
    {"c": "积", "x1": 247, "y1": 787, "x2": 266, "y2": 806},
    {"c": "为", "x1": 265, "y1": 787, "x2": 284, "y2": 806},
    {"c": "准", "x1": 282, "y1": 787, "x2": 301, "y2": 806},
    {"c": "）。", "x1": 303, "y1": 787, "x2": 316, "y2": 806},
]


def test_unproven_value_narrows_to_first_row_band() -> None:
    """Case 1 (农业合同): no proven box before the value, the after-anchor
    （'，' at y 732-755）is on row 1 — the region must cover row 1's whole
    writing zone (handwriting overshoots the printed 732-755 glyph band, the
    real photo's descenders reached ~775) and stop where row 2's ink starts.
    X stays the block's full width (no estimation)."""
    block = _block(_FARM_BLOCK_TEXT, _FARM_BLOCK_POLYGON, list(_FARM_BLOCK_CHARS))

    regions = match_entities_to_ocr([block], [{"type": "ADDRESS", "text": "河南新乡市"}])

    assert len(regions) == 1
    region = regions[0]
    assert region.left == 92 and region.width == 667  # x: full block width kept
    assert region.top == 725  # no before-anchor: band starts at block top
    # bottom = measured top edge of row 2 (787): the full inter-row writing
    # zone is covered (handwritten descenders included), row 2's ink is not.
    assert region.top + region.height == 787
    assert region.height < 91  # strictly narrower than the old slab


def test_unproven_value_between_anchors_stays_on_its_row() -> None:
    """A handwritten value between two proven printed runs on row 2 of a
    two-row block narrows to row 2 — the band is pinched by both anchors."""
    row1 = _row_chars("甲方按照本合同约定支付相关费用。", 100, 300, 330)
    # row 2: 备注： [handwritten 王五] 经手 — value glyphs carry no boxes
    row2_label = _row_chars("备注：", 100, 360, 390)
    row2_suffix = _row_chars("经手", 400, 360, 390)
    text = "甲方按照本合同约定支付相关费用。备注：王五经手"
    block = _block(
        text,
        [[95, 295], [720, 295], [720, 395], [95, 395]],
        row1 + row2_label + row2_suffix,
    )

    regions = match_entities_to_ocr([block], [{"type": "PERSON", "text": "王五"}])

    assert len(regions) == 1
    region = regions[0]
    assert region.top == 330  # band starts at row 1's measured ink bottom
    assert region.top + region.height >= 390  # covers row 2 ink
    assert region.height < 70  # not the two-row slab (~100px)


def test_charsless_block_keeps_whole_block_mask() -> None:
    """No chars at all -> no anchors -> the safe whole-block mask must stay."""
    block = _block(
        "本房屋坐落在北京市朝阳区立城苑小区共8层，现甲方将该房屋出售给乙方。",
        [[98, 673], [644, 673], [644, 794], [98, 794]],
        [],
    )

    regions = match_entities_to_ocr(
        [block], [{"type": "ADDRESS", "text": "北京市朝阳区立城苑小区共8层"}]
    )

    assert len(regions) == 1
    region = regions[0]
    assert (region.left, region.top, region.width, region.height) == (98, 673, 546, 121)


def test_proven_span_still_crops_tight() -> None:
    """Guard: values whose glyphs ARE proven keep the existing tight crop —
    the row-band fallback must not fire for them."""
    chars = _row_chars("联系人张三电话", 100, 300, 330)
    block = _block("联系人张三电话", [[95, 295], [250, 295], [250, 335], [95, 335]], chars)

    regions = match_entities_to_ocr([block], [{"type": "PERSON", "text": "张三"}])

    assert len(regions) == 1
    region = regions[0]
    assert region.width < 60  # tight x crop from the proven char boxes


def test_partially_proven_wrapped_value_gets_line_rect_plus_row_band() -> None:
    """劳动合同 wrapped date: 2025年5月 proven on row 1, the handwritten
    10日起至…止 continuation fills row 2 which the char engine missed entirely.
    The old behavior was a whole-block slab (or a stray full-width sliver
    straddling the row boundary). Now: a tight rect for the proven row-1 run
    (right edge extended to the wrap margin) plus a measured band covering
    row 2, stopping where row 3's ink starts."""
    row1 = _row_chars("合同期限6个月，自2025年5月", 100, 100, 130)
    row3 = _row_chars("其他条款如下。", 100, 200, 230)
    text = "合同期限6个月，自2025年5月10日起至2026年11月10日止。经协商，其他条款如下。"
    block = _block(text, [[95, 95], [700, 95], [700, 235], [95, 235]], row1 + row3)

    regions = match_entities_to_ocr(
        [block], [{"type": "DATE", "text": "2025年5月10日起至2026年11月10日止"}]
    )

    assert len(regions) == 2
    top_rect, band = sorted(regions, key=lambda r: r.top)
    # proven run: starts at the 2025 glyphs (x 100+8*19=252), wrap margin right
    assert top_rect.left > 200 and top_rect.left + top_rect.width == 700
    assert top_rect.top + top_rect.height <= band.top + 1  # contiguous, no gap
    # unproven continuation: full-width band over row 2's zone only
    assert (band.left, band.left + band.width) == (95, 700)
    assert band.top + band.height == 200  # stops at row 3's measured ink top
    # nothing regressed into a whole-block slab
    assert all(r.height < 105 for r in regions)


def test_row_band_survives_split_pass_without_cross_row_sliver() -> None:
    """Service composition (match + split_regions_across_lines), 劳动合同 case:
    the row band contains a sibling char-boxed line block AND its own paragraph
    block's center, so the split pass re-aligns the full value text — which
    used to re-derive the value's OTHER rows (already tightly boxed) and leave
    a full-width sliver straddling the row boundary, via a unique-glyph
    recovery pairing 2026's '6' with 试用期6个月's box one row up. The split
    must stay clipped inside the region and the cross-row mispairing must be
    dropped by the non-decreasing row-order rule."""
    from app.services.vision.ocr_entity_match import split_regions_across_lines

    para_row1 = _row_chars("试用期6个月，自2025年5月", 100, 100, 130)
    para_row3 = _row_chars("有关事项如下。", 100, 200, 230)
    para_text = "试用期6个月，自2025年5月10日起至2026年11月10日止。经协商，有关事项如下。"
    paragraph = _block(para_text, [[95, 95], [700, 95], [700, 235], [95, 235]],
                       para_row1 + para_row3)
    # sibling PP-native line block carrying row 2's chars (the wrap continuation)
    line2 = _block("10日起至2026年11月10日止。经协商，",
                   [[100, 150], [560, 150], [560, 180], [100, 180]],
                   _row_chars("10日起至2026年11月10日止。经协商，", 100, 150, 180))

    entity = {"type": "DATE", "text": "2025年5月10日起至2026年11月10日止"}
    regions = split_regions_across_lines(
        match_entities_to_ocr([paragraph, line2], [entity]),
        [paragraph, line2],
    )

    dates = [r for r in regions if r.entity_type == "DATE"]
    for region in dates:
        # no rect may straddle the row-1/row-2 boundary (the old sliver spanned
        # y~130-150 at full width); every rect hugs exactly one physical row zone
        assert not (region.top < 130 and region.top + region.height > 150) or (
            region.top >= 95 and region.height <= 55
        )
    # the row-2 zone stays covered (either by the band or a proven rect)
    assert any(r.top <= 150 and r.top + r.height >= 180 for r in dates)


# ---------------------------------------------------------------------------
# Fix 2: charless-block re-OCR attaches chars in reading order
# ---------------------------------------------------------------------------

def test_same_row_segments_with_tilt_jitter_keep_reading_order(monkeypatch) -> None:
    """A handwriting-gapped physical line comes back from the crop re-OCR as
    three segments whose integer tops differ by tilt pixels; a (round(top),
    left) sort shuffles them. Row grouping by y-overlap must restore x order."""
    from PIL import Image

    from app.services.vision import ocr_paddle_extract as ope

    left_seg = _block("甲方聘用", [[10, 21], [86, 21], [86, 41], [10, 41]],
                      _row_chars("甲方聘用", 10, 21, 41))
    mid_seg = _block("6个月，自", [[120, 20], [215, 20], [215, 40], [120, 40]],
                     _row_chars("6个月，自", 120, 20, 40))
    right_seg = _block("2025年", [[240, 19], [335, 19], [335, 39], [240, 39]],
                       _row_chars("2025年", 240, 19, 39))

    monkeypatch.setattr(
        ope,
        "_run_structure_service_with_visuals",
        lambda image, service: ([right_seg, left_seg, mid_seg], []),
    )

    charless = _block("甲方聘用6个月，自2025年", [[0, 0], [350, 0], [350, 60], [0, 60]], [])
    image = Image.new("RGB", (400, 100), "white")
    service = type("Svc", (), {"extract_structure_boxes": staticmethod(lambda *a, **k: None)})()

    [result] = ope._attach_chars_to_charless_blocks([charless], image, service)

    assert "".join(c["c"] for c in result.chars) == "甲方聘用6个月，自2025年"


def test_recovered_chars_attach_in_reading_order(monkeypatch) -> None:
    from PIL import Image

    from app.services.vision import ocr_paddle_extract as ope

    row1 = _block("甲方聘用乙方", [[10, 5], [130, 5], [130, 25], [10, 25]],
                  _row_chars("甲方聘用乙方", 10, 5, 25))
    row2 = _block("试用期6个月", [[10, 40], [130, 40], [130, 60], [10, 60]],
                  _row_chars("试用期6个月", 10, 40, 60))

    # The structure engine returns the crop's lines out of reading order.
    monkeypatch.setattr(
        ope, "_run_structure_service_with_visuals", lambda image, service: ([row2, row1], [])
    )

    charless = _block("甲方聘用乙方试用期6个月", [[0, 0], [140, 0], [140, 70], [0, 70]], [])
    image = Image.new("RGB", (200, 100), "white")
    service = type("Svc", (), {"extract_structure_boxes": staticmethod(lambda *a, **k: None)})()

    [result] = ope._attach_chars_to_charless_blocks([charless], image, service)

    assert "".join(c["c"] for c in result.chars) == "甲方聘用乙方试用期6个月"
