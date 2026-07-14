"""签名抑制保覆盖: 仅当签名框(局部 pad 扩边副本)几何完全包含 PII 文本框才丢文本框.

现病灶: 一个小签名核落在大 PII 文本框内, 旧逻辑(中心互含)反而把大 PII 框丢了 = 漏遮。
新语义: 只有当 ocr_has 文本框 ⊆ 签名框(用 _SIGNATURE_REDACTION_PAD 扩边的副本, 即下游
最终签名遮盖的同一尺度)才丢——被丢文本必在最终签名遮盖内, 覆盖单调不减。宽 PII 框
仅与小签名核相交则两框都留。纯几何离线。
"""
from app.models.schemas import BoundingBox
from app.services.vision_service import VisionService


def _sig(x, y, w, h):
    return BoundingBox(id=f"sig_{x}_{y}", x=x, y=y, width=w, height=h, type="signature",
        text="signature", page=1, confidence=0.9, source="visual_features",
        source_detail="locate_anything:detect", evidence_source="visual_feature_model")


def _text(x, y, w, h, text="张三 4021198901031424"):
    return BoundingBox(id=f"txt_{x}_{y}", x=x, y=y, width=w, height=h, type="ID_CARD",
        text=text, page=1, confidence=0.95, source="ocr_has",
        source_detail="text_match", evidence_source="ocr_has")


def _suppress(boxes):
    return VisionService()._suppress_text_in_signature(boxes)


def test_wide_pii_with_embedded_signature_core_both_kept():
    # 宽 PII 文本框 + 内嵌小签名核(中心落其内) -> 两框都留(核不能吞大框)
    pii = _text(0.10, 0.50, 0.60, 0.05)          # wide PII text row
    sig_core = _sig(0.30, 0.505, 0.05, 0.04)     # small core, center inside pii
    out = _suppress([pii, sig_core])
    kept = {b.id for b in out}
    assert pii.id in kept and sig_core.id in kept


def test_colocated_same_size_text_absorbed():
    # 共位同尺寸: 文本框 == 签名框 -> 文本框 ⊆ 扩边签名副本 -> 吸收
    sig = _sig(0.30, 0.50, 0.10, 0.05)
    txt = _text(0.30, 0.50, 0.10, 0.05)
    out = _suppress([sig, txt])
    kept = {b.id for b in out}
    assert sig.id in kept and txt.id not in kept


def test_text_inside_padded_signature_dropped():
    # 文本框略小且落在签名框内 -> ⊆ 扩边副本 -> 丢文本框
    sig = _sig(0.30, 0.50, 0.12, 0.06)
    txt = _text(0.33, 0.52, 0.05, 0.02)
    out = _suppress([sig, txt])
    assert [b.id for b in out] == [sig.id]


def test_text_overhanging_signature_kept():
    # 文本框有一部分外露在签名(含 pad)之外 -> 两框都留(外露像素不能丢)
    sig = _sig(0.30, 0.50, 0.10, 0.05)
    txt = _text(0.30, 0.50, 0.40, 0.05)  # sticks far out to the right
    out = _suppress([sig, txt])
    assert len(out) == 2


def test_no_signature_returns_unchanged():
    txt = _text(0.30, 0.50, 0.10, 0.05)
    out = _suppress([txt])
    assert out == [txt]
