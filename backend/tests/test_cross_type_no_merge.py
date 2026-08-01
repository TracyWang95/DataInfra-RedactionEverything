"""跨类型框永不 IoU 合并 (0710 农业合同实证: 指印按在签名正上方).

"去重"的恒等式 = 同一物体被检测两次。类型断言不同 = 模型断言两个不同实体 =
不是重复: 同像素跨类型是"指印盖在签名上"的真实世界叠放, type-blind IoU 合并
把甲方行的指纹、乙方行的签字各吃掉一个(同勾签字+指纹时 4 框→2 框)。类型相等
是合并的必要条件——字符串相等判定, 自定义实体(custom_*)开放词汇天然支持。
"""
from app.models.schemas import BoundingBox
from app.services.vision_service import VisionService


def _box(btype: str, x: float, y: float, w: float = 0.1, h: float = 0.05) -> BoundingBox:
    return BoundingBox(
        id=f"b_{btype}_{x}_{y}", x=x, y=y, width=w, height=h, type=btype, text=btype,
        page=1, confidence=0.82, source="visual_features",
        source_detail="locate_anything:detect", evidence_source="visual_feature_model",
    )


def test_fingerprint_over_signature_both_survive():
    # the real geometry from the 0710 contract: same pixels, two entities
    sig = _box("signature", 0.297, 0.202, 0.096, 0.041)
    fp = _box("fingerprint", 0.297, 0.200, 0.097, 0.047)
    kept = VisionService()._deduplicate_boxes([sig, fp])
    assert {b.type for b in kept} == {"signature", "fingerprint"}


def test_same_type_near_duplicates_still_merge():
    a = _box("signature", 0.30, 0.20, 0.10, 0.05)
    b = _box("signature", 0.301, 0.201, 0.10, 0.05)
    kept = VisionService()._deduplicate_boxes([a, b])
    assert len(kept) == 1


def test_custom_type_overlapping_builtin_survives():
    # open vocabulary: a user-defined type is its own entity assertion
    sig = _box("signature", 0.30, 0.20, 0.10, 0.05)
    custom = _box("custom_visual_features_红手印", 0.30, 0.20, 0.10, 0.05)
    kept = VisionService()._deduplicate_boxes([sig, custom])
    assert {b.type for b in kept} == {"signature", "custom_visual_features_红手印"}


def test_different_pages_never_merge():
    a = _box("signature", 0.30, 0.20, 0.10, 0.05)
    b = _box("signature", 0.30, 0.20, 0.10, 0.05)
    b = b.model_copy(update={"page": 2})
    kept = VisionService()._deduplicate_boxes([a, b])
    assert len(kept) == 2


def test_fingerprint_inside_seal_absorbed_into_hull():
    """章内'指纹'=章自己的红墨误读(0713 contract19 电子章出4个tile指纹):
    中心在章内的 fingerprint 并入章 hull——章全遮像素不变,冗余错误标注消失。
    章外真指印(农业合同)不受影响(中心不在章内)。"""
    from app.services.vision_service import VisionService

    seal = _box("official_seal", 0.48, 0.30, 0.30, 0.19)
    fp_inside = _box("fingerprint", 0.57, 0.37, 0.05, 0.04)
    fp_outside = _box("fingerprint", 0.30, 0.86, 0.06, 0.05)
    out = VisionService()._absorb_signatures_in_seals([seal, fp_inside, fp_outside])
    types = [b.type for b in out]
    assert types.count("fingerprint") == 1  # only the outside one survives
    assert types.count("official_seal") == 1
