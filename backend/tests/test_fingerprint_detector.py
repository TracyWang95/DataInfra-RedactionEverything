"""专用捺印检测器接入: 调 /detect(json image_base64)→ 归一化框, 替掉 LA/YOLO 指纹通道,
非指纹框保留; 无URL或出错则 fail-open 保留原框(漏印是泄漏)。"""
import asyncio
import httpx

from app.core.config import settings
from app.models.entity_schemas import BoundingBox
from app.services.vision_service import VisionService


def _box(id_, type_, src_detail, source="visual_features"):
    return BoundingBox(id=id_, x=0.1, y=0.1, width=0.1, height=0.06, type=type_, text=type_,
        page=1, confidence=0.7, source=source, source_detail=src_detail,
        evidence_source="visual_feature_model")


class _Resp:
    def __init__(self, boxes): self._b = boxes
    def raise_for_status(self): pass
    def json(self): return {"boxes": self._b, "mode": "yolo11_inkprint"}


class _Client:
    def __init__(self, boxes): self._b = boxes
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, json=None): return _Resp(self._b)


def _run(coro): return asyncio.run(coro)


def test_detector_replaces_la_fingerprints_keeps_others(monkeypatch):
    monkeypatch.setattr(settings, "FINGERPRINT_DETECTOR_URL", "http://x", raising=False)
    det_boxes = [{"x": 0.40, "y": 0.10, "width": 0.10, "height": 0.06, "confidence": 0.82}]
    monkeypatch.setattr(httpx, "AsyncClient", lambda **k: _Client(det_boxes))
    la_fp = _box("la1", "fingerprint", "locate_anything:detect")      # LA 指纹 → 应被替
    yolo_fp = _box("y1", "fingerprint", "has_image:yolo")             # YOLO 指纹 → 应被替
    seal = _box("s1", "official_seal", "has_image:yolo")             # 非指纹 → 保留
    out = _run(VisionService()._detect_fingerprints_via_detector([la_fp, yolo_fp, seal], b"img", 1))
    # 旧视觉指纹框全删
    assert not any(b.type == "fingerprint" and b.source_detail in ("locate_anything:detect", "has_image:yolo") for b in out)
    # 检测器指纹框加入
    fps = [b for b in out if b.type == "fingerprint"]
    assert len(fps) == 1 and fps[0].source_detail == "fingerprint_detector:yolo11"
    assert abs(fps[0].confidence - 0.82) < 1e-6
    # 非指纹保留
    assert any(b.type == "official_seal" for b in out)


def test_fails_open_when_no_url(monkeypatch):
    monkeypatch.setattr(settings, "FINGERPRINT_DETECTOR_URL", "", raising=False)
    la_fp = _box("la1", "fingerprint", "locate_anything:detect")
    out = _run(VisionService()._detect_fingerprints_via_detector([la_fp], b"img", 1))
    assert [b.id for b in out] == ["la1"]   # 原样保留


def test_fails_open_on_service_error(monkeypatch):
    monkeypatch.setattr(settings, "FINGERPRINT_DETECTOR_URL", "http://x", raising=False)

    class _Boom:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise RuntimeError("503")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **k: _Boom())
    la_fp = _box("la1", "fingerprint", "locate_anything:detect")
    out = _run(VisionService()._detect_fingerprints_via_detector([la_fp], b"img", 1))
    assert [b.id for b in out] == ["la1"]   # 出错保留旧框(漏印是泄漏)
