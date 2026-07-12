"""换行截断金额的召回 (0712 房屋合同实证: ￥360000元 的"元"被换行).

病理链: OCR 行块断在 '…人民币陆7元整(￥360000'("元)"在下一行); HaS 从拼接
文本正确识别出 '人民币陆7元整(￥360000元)'; 数值二次查询稳定返回两个值
['7元整','￥360000元'](双数字表述各一)——但 narrow 只认单值, 多值直接放弃,
整串又跨行匹配不上, 360000 就漏了。

修法两刀(恒等式):
1. narrow 多值拆分: 模型说实体里有 N 个值就拆成 N 个 AMOUNT 实体各自找框。
2. 数字载荷重试: AMOUNT 的敏感载荷是数字序列; 实体精确匹配失败后, 其数字串
   (>2 位结构守卫)在块内连续出现即按精确管线框之——同数字=同值该遮(W3 既定
   恒等式), 多遮方向安全。
"""
import asyncio

from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.has_text_analysis import _narrow_amount_entities
from app.services.vision.ocr_entity_match import match_entities_to_ocr


class _FakeHaS:
    def __init__(self, mapping):
        self.mapping = mapping

    def ner(self, text, labels):
        return {labels[0]: self.mapping.get(text, [])}


def _block(text: str, left: int, top: int, width: int = 500, height: int = 30) -> OCRTextBlock:
    return OCRTextBlock(
        text=text,
        polygon=[[left, top], [left + width, top], [left + width, top + height], [left, top + height]],
        confidence=0.98,
    )


def test_narrow_splits_dual_numeral_entity():
    entities = [{"type": "AMOUNT", "text": "人民币陆7元整(￥360000元)"}]
    fake = _FakeHaS({"人民币陆7元整(￥360000元)": ["7元整", "￥360000元"]})
    asyncio.run(_narrow_amount_entities(entities, fake))
    texts = sorted(e["text"] for e in entities)
    assert texts == ["7元整", "￥360000元"]
    assert all(e["type"] == "AMOUNT" for e in entities)


def test_narrow_single_value_behavior_unchanged():
    entities = [{"type": "AMOUNT", "text": "人民币每亩每年100元"}]
    fake = _FakeHaS({"人民币每亩每年100元": ["100元"]})
    asyncio.run(_narrow_amount_entities(entities, fake))
    assert [e["text"] for e in entities] == ["100元"]


def test_linewrapped_amount_recalled_by_digit_payload():
    # the real 0712 geometry: the value's 元 wrapped to the next line
    head = _block("售给乙方，出售房屋(建筑面积共120平方米)以人民币陆7元整(￥360000", 101, 697)
    tail = _block("元)的价款出售给乙方，包括但不限于维修基金", 98, 737)
    regions = match_entities_to_ocr([head, tail], [{"type": "AMOUNT", "text": "￥360000元"}])
    assert regions, "line-wrapped amount must be recalled"
    assert any("360000" in str(r.text) for r in regions)


def test_digit_retry_needs_structural_length():
    # digits '7' (<=2) must NOT fire the retry — any stray 7 would match
    block = _block("共 7 层，电话 137", 100, 100)
    regions = match_entities_to_ocr([block], [{"type": "AMOUNT", "text": "柒元整"}])
    # 柒元整 has digit payload '' -> no retry, no exact hit -> nothing
    assert regions == []


def test_no_digit_occurrence_no_region():
    block = _block("与本合同无关的一行文字", 100, 100)
    regions = match_entities_to_ocr([block], [{"type": "AMOUNT", "text": "￥360000元"}])
    assert regions == []
