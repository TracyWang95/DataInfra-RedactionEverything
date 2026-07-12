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


def test_tile_gap_filter_is_type_scoped():
    """A fingerprint tile candidate overlapping an existing SIGNATURE box is a
    different entity, not the zoom second-guessing the page-scale call — it
    must be kept. Same-type overlap is still discarded (that IS the retry
    re-finding what the full frame already found)."""
    from app.services.vision.locate_grounding import LocateAnythingGroundingService

    svc = LocateAnythingGroundingService()
    existing = [_box("signature", 0.30, 0.20, 0.10, 0.05)]
    fp_tile = _box("fingerprint", 0.30, 0.20, 0.09, 0.05)
    fp_tile = fp_tile.model_copy(update={"source_detail": "locate_anything:tile_retry"})
    sig_tile = _box("signature", 0.30, 0.20, 0.09, 0.05)
    sig_tile = sig_tile.model_copy(update={"source_detail": "locate_anything:tile_retry"})
    kept = svc._filter_tile_candidates([fp_tile, sig_tile], existing)
    assert kept == [fp_tile]
