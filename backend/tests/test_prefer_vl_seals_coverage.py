"""prefer_vl_seals 保覆盖: 仅当相交 VL 印章的"真并集"完全覆盖 LA 框才丢 LA.

现病灶: LA 长条罩住两枚叠章, VL 只命中其中一枚, 旧逻辑(单枚中心互含)即丢 LA ->
漏掉 VL 未检出的那枚叠章。新语义: 与 LA 相交的 VL 印章框真并集(精确坐标压缩覆盖,
非阈值)完全覆盖 LA 才丢; 否则保留 LA(它可能是漏检叠章的唯一遮盖)。纯几何离线。
"""
from app.models.schemas import BoundingBox
from app.services.vision_service import VisionService


def _seal(x, y, w, h, source):
    return BoundingBox(id=f"seal_{source}_{x}_{y}", x=x, y=y, width=w, height=h,
        type="official_seal", text="official_seal", page=1, confidence=0.9,
        source=source, source_detail="seg", evidence_source="visual_feature_model")


def _prefer(boxes):
    return VisionService()._prefer_vl_seals(boxes)


def test_la_strip_over_two_stamps_one_vl_hit_keeps_la():
    # LA 长条 (罩两枚叠章) + 仅上半被一枚 VL 命中 -> 并集未覆盖满 LA -> 保留 LA
    la = _seal(0.40, 0.20, 0.20, 0.40, "visual_features")     # tall strip
    vl_top = _seal(0.40, 0.20, 0.20, 0.20, "ocr_has")         # only top half
    out = _prefer([la, vl_top])
    ids = {b.id for b in out}
    assert la.id in ids and vl_top.id in ids  # LA kept (bottom stamp still covered by it)


def test_la_strip_fully_covered_by_two_vl_union_dropped():
    # 两枚 VL 并集(上半+下半)覆盖满 LA -> 可丢 LA
    la = _seal(0.40, 0.20, 0.20, 0.40, "visual_features")
    vl_top = _seal(0.40, 0.20, 0.20, 0.20, "ocr_has")
    vl_bot = _seal(0.40, 0.40, 0.20, 0.20, "ocr_has")
    out = _prefer([la, vl_top, vl_bot])
    sources = sorted(b.source for b in out)
    assert sources == ["ocr_has", "ocr_has"]  # LA dropped, both VL kept


def test_la_seal_with_no_vl_counterpart_kept():
    la = _seal(0.10, 0.10, 0.20, 0.20, "visual_features")
    vl_far = _seal(0.70, 0.70, 0.20, 0.20, "ocr_has")  # disjoint
    out = _prefer([la, vl_far])
    assert {b.id for b in out} == {la.id, vl_far.id}


def test_no_vl_seals_keeps_all_la():
    la1 = _seal(0.10, 0.10, 0.20, 0.20, "visual_features")
    la2 = _seal(0.50, 0.50, 0.20, 0.20, "visual_features")
    out = _prefer([la1, la2])
    assert len(out) == 2
