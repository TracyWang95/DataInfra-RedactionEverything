"""AMOUNT visual span narrows to the currency value token.

HaS returns amounts with surrounding business context（人民币每亩每年100元 /
保底十万元/每年左右）. The sensitive ink on the page is the value token
itself — same rule the percent amounts already follow ("contract amount 40%"
boxes just 40%). Token scanning is regex-free over closed character classes
(digits / CJK numerals / currency units), the same family as the percent
scanner's '%'.

Also: the HaS INPUT text is stripped of VL math markup（$ \\underline{...} $）
— the wrapper noise made HaS tag the 保底十万元 fill only intermittently.
"""
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.has_text_payload import _iter_payload_texts
from app.services.vision.ocr_pipeline import match_entities_to_ocr
from app.services.vision.ocr_visual_span import _visual_match_text_for_entity


def test_arabic_amount_narrows_to_value_token() -> None:
    assert _visual_match_text_for_entity("AMOUNT", "人民币每亩每年100元") == "100元"


def test_cjk_amount_narrows_to_value_token() -> None:
    assert _visual_match_text_for_entity("AMOUNT", "保底十万元/每年左右") == "十万元"


def test_pure_value_amounts_stay_whole() -> None:
    # already the bare value (token == whole text): nothing to narrow
    assert _visual_match_text_for_entity("AMOUNT", "壹拾万圆整") == "壹拾万圆整"
    assert _visual_match_text_for_entity("AMOUNT", "￥3600000元") == "￥3600000元"
    assert _visual_match_text_for_entity("AMOUNT", "100000元") == "100000元"


def test_percent_precedent_unchanged() -> None:
    assert _visual_match_text_for_entity("AMOUNT", "合同金额的40%") == "40%"


def test_non_amount_types_untouched() -> None:
    assert _visual_match_text_for_entity("ADDRESS", "位于河南新乡市100号") == "位于河南新乡市100号"


def test_amount_without_any_value_token_stays_whole() -> None:
    assert _visual_match_text_for_entity("AMOUNT", "按市场价结算") == "按市场价结算"


def test_region_crops_to_value_token_glyphs() -> None:
    """农业合同 block: the printed label 人民币每亩每年 must stay outside the
    box — only the value token's glyphs are masked."""
    text = "乙方按项目建设投产壹年内按人民币每亩每年100元的标准进行"
    chars = []
    cursor = 134
    for ch in text:
        chars.append({"c": ch, "x1": cursor, "y1": 885, "x2": cursor + 19, "y2": 916})
        cursor += 19
    block = OCRTextBlock(
        text=text,
        polygon=[[134, 880], [cursor, 880], [cursor, 925], [134, 925]],
        confidence=0.98,
        chars=chars,
    )

    regions = match_entities_to_ocr(
        [block], [{"type": "AMOUNT", "text": "人民币每亩每年100元"}]
    )

    assert len(regions) == 1
    region = regions[0]
    assert region.text == "100元"
    # 100元 starts at glyph index 13 of the entity, i.e. text index 13+13=26?
    # -> the box must start well past the printed label (134 + 20*19 = 514)
    assert region.left > 480
    assert region.width < 120  # 4 glyphs' span, not the 19-glyph phrase


def test_has_input_text_is_markup_free() -> None:
    texts = _iter_payload_texts(
        "甲方保证以销售完成的 $ \\underline{\\text{保底十万元/每年左右}} $给予乙方分红。"
    )
    joined = "".join(texts)
    assert "underline" not in joined and "$" not in joined
    assert "保底十万元/每年左右" in joined
