"""同文本重叠框保留最紧 (图片_20260714 保姆合同: 身份证号码整行框 w=0.734).

手写身份证号被读乱, 字符对齐横跨了合并的两列 OCR 块, 于是同一个值 '4021198901031424'
同时产出正确紧框(右列 W=188)和错误满宽框(整行 W=587)。同类型+同文本+重叠 ⇒ 同一个
值的多次定位, 只保留最紧的(已覆盖其字形), 更宽的孪生框是溢到别列的冗余覆盖, 删。

泄露安全: 只合并"同文本且重叠"的框, 幸存的紧框覆盖本值字形, 别的字段各留其框;
页面别处重复出现的同值(不重叠)不受影响。真几何来自服务器复现 (页面 800px 宽)。
"""
from app.services.ocr_has_vision_service import SensitiveRegion
from app.services.vision.ocr_entity_match import _prune_looser_same_text_boxes


def _r(etype, left, top, width, height, text=""):
    return SensitiveRegion(
        text=text, entity_type=etype, left=left, top=top, width=width, height=height,
        confidence=1.0, source="text_match",
    )


def test_wide_same_text_twin_dropped():
    wide = _r("ID_CARD", 165, 201, 587, 41, "4021198901031424")   # 满宽整行
    tight = _r("ID_CARD", 575, 188, 188, 51, "4021198901031424")  # 右列紧框, 同文本
    out = _prune_looser_same_text_boxes([wide, tight])
    ids = [id(r) for r in out]
    assert id(tight) in ids and id(wide) not in ids


def test_different_text_same_type_both_kept():
    # 甲/乙两个不同身份证号, 即使重叠也各留(不同值)
    a = _r("ID_CARD", 286, 190, 148, 51, "20120198712071242")
    b = _r("ID_CARD", 165, 201, 587, 41, "4021198901031424")  # 宽, 但文本不同
    out = _prune_looser_same_text_boxes([a, b])
    assert len(out) == 2


def test_same_text_non_overlapping_both_kept():
    # 同一编号在页面两处出现(信用代码印两遍) — 不重叠, 都保留
    a = _r("CREDIT_CODE", 100, 100, 200, 40, "91310000MA1")
    b = _r("CREDIT_CODE", 100, 600, 260, 40, "91310000MA1")  # 远处, 更宽但不重叠
    out = _prune_looser_same_text_boxes([a, b])
    assert len(out) == 2


def test_keeps_single_tightest_among_three():
    big = _r("ID_CARD", 100, 100, 500, 40, "X123")
    mid = _r("ID_CARD", 120, 105, 200, 30, "X123")
    small = _r("ID_CARD", 130, 108, 90, 24, "X123")
    out = _prune_looser_same_text_boxes([big, mid, small])
    assert [id(r) for r in out] == [id(small)]


def test_blank_text_untouched():
    a = _r("signature", 100, 100, 400, 40, "")
    b = _r("signature", 120, 105, 100, 30, "")
    out = _prune_looser_same_text_boxes([a, b])
    assert len(out) == 2  # 无文本不参与同文本去重
