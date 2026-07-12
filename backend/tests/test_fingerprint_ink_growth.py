"""指纹框贴合印泥物理范围 (0710 农业合同实证: 乙方指印底部漏一截).

红指印的定义 = 红色印泥沉积。LA 的指纹框实测盖不全印泥(乙方框下缘 0.247 <
印泥 comp 下缘 0.259, 底部漏 ~14px), 且框形态随采样漂。修法是物理恒等式:
与指纹框相交的未膨胀红色连通域(raw_colored_component_bboxes, 岳阳桥接教训
已内置)就是这枚指印自己的印泥, 框 grow 到 hull——只长不缩, 失效方向=多遮。
无相交 comp(灰度扫描件无色彩证据)保守不动。
"""
from app.models.schemas import BoundingBox
from app.services.vision.locate_grounding import LocateAnythingGroundingService


def _box(btype: str, x: float, y: float, w: float, h: float) -> BoundingBox:
    return BoundingBox(
        id=f"g_{btype}_{x}", x=x, y=y, width=w, height=h, type=btype, text=btype,
        page=1, confidence=0.82, source="visual_features",
        source_detail="locate_anything:detect", evidence_source="visual_feature_model",
    )


def _grow(monkeypatch, boxes, comps):
    monkeypatch.setattr(
        "app.services.vision.locate_grounding.raw_colored_component_bboxes",
        lambda image_data: comps,
    )
    svc = LocateAnythingGroundingService()
    return svc._grow_fingerprints_to_ink(boxes, b"jpegbytes")


def test_partial_coverage_grows_to_the_ink_hull(monkeypatch):
    # the real 0710 geometry: box bottom 0.247 < ink bottom 0.259
    fp = _box("fingerprint", 0.297, 0.200, 0.097, 0.047)
    comps = [(0.306, 0.203, 0.056, 0.056)]
    out = _grow(monkeypatch, [fp], comps)
    grown = out[0]
    assert grown.y + grown.height >= 0.259 - 1e-9  # covers the ink bottom
    assert grown.x <= 0.297 + 1e-9 and grown.y <= 0.200 + 1e-9  # grow-only


def test_full_coverage_stays_unchanged(monkeypatch):
    fp = _box("fingerprint", 0.344, 0.151, 0.085, 0.050)
    comps = [(0.350, 0.157, 0.059, 0.044)]  # entirely inside the box
    out = _grow(monkeypatch, [fp], comps)
    assert (out[0].x, out[0].y, out[0].width, out[0].height) == (0.344, 0.151, 0.085, 0.050)


def test_detached_ink_is_not_absorbed(monkeypatch):
    # a red seal elsewhere on the page must not stretch the fingerprint box
    fp = _box("fingerprint", 0.30, 0.20, 0.09, 0.05)
    comps = [(0.70, 0.70, 0.10, 0.08)]
    out = _grow(monkeypatch, [fp], comps)
    assert (out[0].x, out[0].y) == (0.30, 0.20) and out[0].width == 0.09


def test_no_color_evidence_keeps_the_box(monkeypatch):
    fp = _box("fingerprint", 0.30, 0.20, 0.09, 0.05)
    out = _grow(monkeypatch, [fp], [])
    assert out[0].width == 0.09


def test_non_fingerprint_types_untouched(monkeypatch):
    sig = _box("signature", 0.30, 0.20, 0.09, 0.04)
    comps = [(0.30, 0.20, 0.12, 0.08)]
    out = _grow(monkeypatch, [sig], comps)
    assert (out[0].width, out[0].height) == (0.09, 0.04)


def test_analysis_failure_fails_open(monkeypatch):
    monkeypatch.setattr(
        "app.services.vision.locate_grounding.raw_colored_component_bboxes",
        lambda image_data: (_ for _ in ()).throw(RuntimeError("no cv")),
    )
    fp = _box("fingerprint", 0.30, 0.20, 0.09, 0.05)
    svc = LocateAnythingGroundingService()
    out = svc._grow_fingerprints_to_ink([fp], b"jpegbytes")
    assert out[0].width == 0.09
