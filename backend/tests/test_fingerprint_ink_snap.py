"""指纹框 = 印泥实测范围 (snap-to-ink, 纯物理测量框).

红指印 = 红色印泥沉积; 可见沉积的范围是**测量**出来的(chroma>既有可见墨底噪
的未膨胀连通域 hull), 不是模型预测出来的。LA 框只做存在断言+归属判定(哪些
印泥属于这枚指印), 其几何被丢弃——实测它欠覆盖(0710 乙方框底 0.247 < 印泥底
0.259)、松紧随采样漂, 且 8 标签 A/B 证明换措辞救不了(最好 cov0.93, 中文标签
在 CT 负样本上全假阳)。物理测量就是 Tracy 要的"完美大小正好框住红色手指印"。
"""
from app.models.schemas import BoundingBox
from app.services.vision.locate_grounding import LocateAnythingGroundingService


def _box(btype: str, x: float, y: float, w: float, h: float) -> BoundingBox:
    return BoundingBox(
        id=f"g_{btype}_{x}", x=x, y=y, width=w, height=h, type=btype, text=btype,
        page=1, confidence=0.82, source="visual_features",
        source_detail="locate_anything:detect", evidence_source="visual_feature_model",
    )


def _snap(monkeypatch, boxes, comps):
    monkeypatch.setattr(
        "app.services.vision.locate_grounding.raw_colored_component_bboxes",
        lambda image_data: comps,
    )
    svc = LocateAnythingGroundingService()
    return svc._snap_fingerprints_to_ink(boxes, b"jpegbytes")


def test_box_becomes_exactly_the_ink_hull(monkeypatch):
    # the real 0710 geometry: LA box under-covers the ink bottom AND carries slack
    fp = _box("fingerprint", 0.297, 0.200, 0.097, 0.047)
    comps = [(0.306, 0.203, 0.056, 0.056)]
    out = _snap(monkeypatch, [fp], comps)
    b = out[0]
    assert (round(b.x, 3), round(b.y, 3), round(b.width, 3), round(b.height, 3)) == (0.306, 0.203, 0.056, 0.056)


def test_one_loose_box_over_two_prints_splits_per_deposit(monkeypatch):
    # 0710 农业合同: one LA box straddled both prints (and the signature
    # between them) — the union hull was the "刘悦上面那个指纹框太大" bug.
    # A connected component IS a separate deposit: one exact box per print.
    fp = _box("fingerprint", 0.275, 0.155, 0.150, 0.104)
    comps = [(0.350, 0.157, 0.059, 0.044), (0.306, 0.203, 0.056, 0.056)]
    out = _snap(monkeypatch, [fp], comps)
    assert len(out) == 2
    got = sorted((round(b.x, 3), round(b.y, 3), round(b.width, 3), round(b.height, 3)) for b in out)
    assert got == [(0.306, 0.203, 0.056, 0.056), (0.350, 0.157, 0.059, 0.044)]
    assert all(b.type == "fingerprint" for b in out)


def test_detached_ink_is_not_absorbed(monkeypatch):
    fp = _box("fingerprint", 0.30, 0.20, 0.09, 0.05)
    comps = [(0.70, 0.70, 0.10, 0.08)]
    out = _snap(monkeypatch, [fp], comps)
    assert (out[0].x, out[0].y, out[0].width) == (0.30, 0.20, 0.09)


def test_no_color_evidence_keeps_the_box(monkeypatch):
    fp = _box("fingerprint", 0.30, 0.20, 0.09, 0.05)
    out = _snap(monkeypatch, [fp], [])
    assert out[0].width == 0.09


def test_non_fingerprint_types_untouched(monkeypatch):
    sig = _box("signature", 0.30, 0.20, 0.09, 0.04)
    comps = [(0.30, 0.20, 0.12, 0.08)]
    out = _snap(monkeypatch, [sig], comps)
    assert (out[0].width, out[0].height) == (0.09, 0.04)


def test_analysis_failure_fails_open(monkeypatch):
    monkeypatch.setattr(
        "app.services.vision.locate_grounding.raw_colored_component_bboxes",
        lambda image_data: (_ for _ in ()).throw(RuntimeError("no cv")),
    )
    fp = _box("fingerprint", 0.30, 0.20, 0.09, 0.05)
    svc = LocateAnythingGroundingService()
    out = svc._snap_fingerprints_to_ink([fp], b"jpegbytes")
    assert out[0].width == 0.09
