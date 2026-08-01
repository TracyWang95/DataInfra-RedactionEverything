"""prefer_vl_seals: PaddleOCR-VL 是公章权威, LA/YOLO 仅补充 (信任 VL, 无魔法阈值).

公章是视觉特征: 所有章都 source=visual_features, 靠 source_detail 区分引擎 ——
VL 章 detail 含 "paddleocr_vl"(绝不走 OCR+HaS 文本链路), LA/YOLO 为补充。
语义: VL 章恒保留为该印章的主框; 非 VL 章中心落在某个 VL 章框内 = 同一枚印章的
重复 -> 丢弃, 采用确定性 VL 框(否则更松、随机的 LA 框会在后续 shard 合并里胜出,
公章就时灵时不灵); 中心落在所有 VL 章之外 = VL 未检出的另一枚印章 -> 保留(召回不降)。
判据为无阈值的 center-inside identity, 纯几何离线。
"""
from app.models.schemas import BoundingBox
from app.services.vision_service import VisionService

VL = "paddleocr_vl:seal"
LA = "locate_anything:detect"
YOLO = "has_image:yolo"


def _seal(x, y, w, h, detail):
    return BoundingBox(id=f"seal_{detail}_{x}_{y}", x=x, y=y, width=w, height=h,
        type="official_seal", text="official_seal", page=1, confidence=0.9,
        source="visual_features", source_detail=detail, evidence_source="visual_feature_model")


def _prefer(boxes):
    return VisionService()._prefer_vl_seals(boxes)


def _details(out):
    return sorted(b.source_detail for b in out)


def test_la_duplicate_center_inside_vl_dropped():
    # LA 框比 VL 略大但中心几乎重合 = 同一枚章 -> 丢 LA, 采用 VL 框(确定性)。
    # 这正是线上回归: LA 框略大 -> 旧"全覆盖"判据丢不掉 -> 合并保了随机 LA -> 飘。
    vl = _seal(0.208, 0.247, 0.197, 0.137, VL)
    la = _seal(0.207, 0.243, 0.198, 0.142, LA)
    assert _details(_prefer([vl, la])) == [VL]


def test_yolo_duplicate_center_inside_vl_dropped():
    vl = _seal(0.927, 0.128, 0.072, 0.139, VL)
    yolo = _seal(0.919, 0.127, 0.081, 0.136, YOLO)
    assert _details(_prefer([vl, yolo])) == [VL]


def test_la_extra_stamp_center_outside_all_vl_kept():
    # LA 中心在所有 VL 章之外 = VL 漏检的另一枚章 -> 保留补充。
    vl = _seal(0.20, 0.20, 0.15, 0.15, VL)
    la_extra = _seal(0.70, 0.70, 0.15, 0.15, LA)
    assert {b.id for b in _prefer([vl, la_extra])} == {vl.id, la_extra.id}


def test_la_over_vl_missed_stamp_kept():
    # VL 只检出上方一枚章; LA 框在下方另一处(中心不在那枚 VL 章内)-> 保留, 0 漏。
    vl_top = _seal(0.40, 0.15, 0.18, 0.15, VL)
    la_low = _seal(0.40, 0.45, 0.18, 0.18, LA)
    assert {b.id for b in _prefer([vl_top, la_low])} == {vl_top.id, la_low.id}


def test_no_vl_seals_keeps_all_la():
    la1 = _seal(0.10, 0.10, 0.20, 0.20, LA)
    la2 = _seal(0.50, 0.50, 0.20, 0.20, LA)
    assert len(_prefer([la1, la2])) == 2
