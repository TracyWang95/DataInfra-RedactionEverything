"""同文本重叠框: 仅当"更紧的孪生框是完整span证明"才丢更宽的 (保覆盖新语义).

手写身份证号被读乱, 字符对齐横跨了合并的两列 OCR 块, 于是同一个值 '4021198901031424'
同时产出正确紧框(右列 W=188)和错误满宽框(整行 W=587)。同类型+同文本+重叠 ⇒ 同一个
值的多次定位。但只有当紧框来自「首末glyph都证明」的完整span证明(span_proven_ids)时,
才敢丢更宽的孪生框——紧框已覆盖该值全部字形, 丢宽框不会露出尾字。

若紧框只是 argmax 部分匹配(可能只盖了 'X12345' 的 '123'), 它不是证明, 宽框必须保留,
否则尾字漏遮。泄露安全: 只对"同文本+重叠+紧框完整证明"三条同时成立才合并。真几何来自
服务器复现 (页面 800px 宽)。
"""
from app.services.ocr_has_vision_service import SensitiveRegion
from app.services.vision.ocr_entity_match import _prune_looser_same_text_boxes


def _r(etype, left, top, width, height, text=""):
    return SensitiveRegion(
        text=text, entity_type=etype, left=left, top=top, width=width, height=height,
        confidence=1.0, source="text_match",
    )


def test_wide_same_text_twin_dropped_when_tight_is_span_proven():
    wide = _r("ID_CARD", 165, 201, 587, 41, "4021198901031424")   # 满宽整行
    tight = _r("ID_CARD", 575, 188, 188, 51, "4021198901031424")  # 右列紧框, 完整span证明
    out = _prune_looser_same_text_boxes([wide, tight], span_proven_ids={id(tight)})
    ids = [id(r) for r in out]
    assert id(tight) in ids and id(wide) not in ids


def test_argmax_partial_tight_keeps_wide():
    # 整行框 "X12345" + argmax 紧框只盖 "123" (不是完整span证明) -> 保留整行框
    wide = _r("ID_CARD", 100, 100, 500, 40, "X12345")
    tight = _r("ID_CARD", 110, 105, 120, 30, "X12345")  # argmax 部分匹配, 未证明首末
    out = _prune_looser_same_text_boxes([wide, tight], span_proven_ids=set())
    assert len(out) == 2  # 尾字可能在紧框外, 宽框必须留


def test_complete_span_proof_drops_wide():
    # 同上几何, 但紧框来自完整span证明 -> 丢整行框
    wide = _r("ID_CARD", 100, 100, 500, 40, "X12345")
    tight = _r("ID_CARD", 110, 105, 120, 30, "X12345")
    out = _prune_looser_same_text_boxes([wide, tight], span_proven_ids={id(tight)})
    assert [id(r) for r in out] == [id(tight)]


def test_different_text_same_type_both_kept():
    # 甲/乙两个不同身份证号, 即使重叠也各留(不同值), 与证明无关
    a = _r("ID_CARD", 286, 190, 148, 51, "20120198712071242")
    b = _r("ID_CARD", 165, 201, 587, 41, "4021198901031424")  # 宽, 但文本不同
    out = _prune_looser_same_text_boxes([a, b], span_proven_ids={id(a), id(b)})
    assert len(out) == 2


def test_same_text_non_overlapping_both_kept():
    # 同一编号在页面两处出现(信用代码印两遍) — 不重叠, 都保留(即便都证明)
    a = _r("CREDIT_CODE", 100, 100, 200, 40, "91310000MA1")
    b = _r("CREDIT_CODE", 100, 600, 260, 40, "91310000MA1")  # 远处, 更宽但不重叠
    out = _prune_looser_same_text_boxes([a, b], span_proven_ids={id(a), id(b)})
    assert len(out) == 2


def test_keeps_single_tightest_among_three_when_proven():
    big = _r("ID_CARD", 100, 100, 500, 40, "X123")
    mid = _r("ID_CARD", 120, 105, 200, 30, "X123")
    small = _r("ID_CARD", 130, 108, 90, 24, "X123")
    out = _prune_looser_same_text_boxes([big, mid, small], span_proven_ids={id(mid), id(small)})
    assert [id(r) for r in out] == [id(small)]


def test_unproven_tight_keeps_all_three():
    # 无任何完整span证明 -> 三个框全留(尾字可能在最紧框外)
    big = _r("ID_CARD", 100, 100, 500, 40, "X123")
    mid = _r("ID_CARD", 120, 105, 200, 30, "X123")
    small = _r("ID_CARD", 130, 108, 90, 24, "X123")
    out = _prune_looser_same_text_boxes([big, mid, small], span_proven_ids=set())
    assert len(out) == 3


def test_blank_text_untouched():
    a = _r("signature", 100, 100, 400, 40, "")
    b = _r("signature", 120, 105, 100, 30, "")
    out = _prune_looser_same_text_boxes([a, b], span_proven_ids={id(b)})
    assert len(out) == 2  # 无文本不参与同文本去重
