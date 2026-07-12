"""tile指纹候选的印泥存在性闸 (CT报告X光片tile幻觉实证,基线3个假阳→投机tile下放大到8个).

与机器码解码闸完全同构: 红指印的定义=红色印泥沉积; tile裁剪失去页面上下文,
把X光片黑白纹理幻觉成"指纹"。tile候选必须与红色连通域相交(印泥存在性证明)
才收编; 主检测框(全图上下文可信)不过此闸——灰度扫描件真指印仍由主检测保留。
失效方向: tile兜底收窄=回到主检测水平,不比无tile更漏。
"""
from app.models.schemas import BoundingBox
from app.services.vision.locate_grounding import LocateAnythingGroundingService


def _tile_box(btype, x, y):
    return BoundingBox(
        id=f"t_{btype}_{x}", x=x, y=y, width=0.1, height=0.08, type=btype, text=btype,
        page=1, confidence=0.82, source="visual_features",
        source_detail="locate_anything:tile_retry", evidence_source="visual_feature_model",
    )


def _gate(monkeypatch, boxes, comps):
    monkeypatch.setattr(
        "app.services.vision.locate_grounding.raw_colored_component_bboxes",
        lambda image_data: comps,
    )
    svc = LocateAnythingGroundingService()
    return svc._verify_fingerprint_tile_boxes(boxes, b"jpeg")


def test_xray_hallucination_without_ink_is_dropped(monkeypatch):
    kept = _gate(monkeypatch, [_tile_box("fingerprint", 0.3, 0.4)], [])
    assert kept == []


def test_candidate_intersecting_ink_survives(monkeypatch):
    kept = _gate(monkeypatch, [_tile_box("fingerprint", 0.3, 0.4)], [(0.32, 0.42, 0.05, 0.05)])
    assert len(kept) == 1


def test_detached_ink_does_not_rescue(monkeypatch):
    kept = _gate(monkeypatch, [_tile_box("fingerprint", 0.3, 0.4)], [(0.8, 0.8, 0.05, 0.05)])
    assert kept == []


def test_non_fingerprint_candidates_pass_through(monkeypatch):
    sig = _tile_box("signature", 0.3, 0.4)
    kept = _gate(monkeypatch, [sig], [])
    assert kept == [sig]


def test_analysis_failure_fails_open(monkeypatch):
    monkeypatch.setattr(
        "app.services.vision.locate_grounding.raw_colored_component_bboxes",
        lambda image_data: (_ for _ in ()).throw(RuntimeError("no cv")),
    )
    svc = LocateAnythingGroundingService()
    fp = _tile_box("fingerprint", 0.3, 0.4)
    assert svc._verify_fingerprint_tile_boxes([fp], b"jpeg") == [fp]
