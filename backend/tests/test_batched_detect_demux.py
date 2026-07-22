"""批式 /detect 的按请求解复用 (vLLM prompt-embeds 模式, MoonViT 编码一次).

- demux 键 = _normalize_detect_tag(镜像服务器 _normalize_slug 逐字), 中文查询词
  原样通过; 解不出的 category 大声告警丢弃, 绝不静默改标。
- 开关关 (默认) / 单请求时行为与 fan-out 完全一致。
- 批请求失败回退 fan-out (可用性不降级)。
"""
import asyncio

import pytest

from app.models.schemas import BoundingBox  # noqa: F401  (type context)
from app.services.vision.locate_grounding import (
    LocateAnythingGroundingService,
    _normalize_detect_tag,
)


def _ptypes(ids):
    from types import SimpleNamespace

    return [SimpleNamespace(id=i, name=i, checklist=[], rules=[]) for i in ids]


@pytest.fixture()
def svc(monkeypatch):
    service = LocateAnythingGroundingService()
    monkeypatch.setattr("app.services.vision.locate_grounding.settings.HAS_IMAGE_URL", "", raising=False)
    monkeypatch.setattr("app.services.vision.locate_grounding.settings.LA_SIGNATURE_URL", "", raising=False)
    monkeypatch.setattr("app.services.vision.locate_grounding.settings.VISUAL_TILE_RETRY", False, raising=False)
    monkeypatch.setattr("app.services.vision.locate_grounding.settings.VISUAL_DETECT_BATCH_CATEGORIES", True, raising=False)
    async def _verify_noop(self, boxes, image_data, reground_queries):
        return boxes
    monkeypatch.setattr(LocateAnythingGroundingService, "_verify_grounded_candidates", _verify_noop)
    return service


def test_mirror_fold_matches_server():
    assert _normalize_detect_tag(" Red-Inked Mark ") == "red_inked mark"
    assert _normalize_detect_tag("红手印") == "红手印"  # CJK untouched


def test_batched_request_demuxes_by_requested_category(svc, monkeypatch):
    sent = []

    async def fake_detect(self, image_data, categories):
        sent.append(list(categories))
        # real server contract: each box's category is the NORMALIZED requested
        # tag (the grounding query wording), not the slug
        return [
            {"category": _normalize_detect_tag(categories[0]), "x": 0.1, "y": 0.1, "width": 0.1, "height": 0.05, "confidence": 0.82},
            {"category": _normalize_detect_tag(categories[1]), "x": 0.3, "y": 0.3, "width": 0.1, "height": 0.05, "confidence": 0.82},
        ]

    monkeypatch.setattr(LocateAnythingGroundingService, "_post_detect", fake_detect)
    boxes, _ = asyncio.run(svc.detect_categories(b"img", 1, _ptypes(["signature", "fingerprint"])))
    assert len(sent) == 1 and len(sent[0]) == 2  # ONE request carried both
    assert {b.type for b in boxes} == {"signature", "fingerprint"}


def test_unmappable_category_dropped_loudly_not_retagged(svc, monkeypatch):
    async def fake_detect(self, image_data, categories):
        return [{"category": "mystery", "x": 0.1, "y": 0.1, "width": 0.1, "height": 0.05, "confidence": 0.82}]

    monkeypatch.setattr(LocateAnythingGroundingService, "_post_detect", fake_detect)
    boxes, _ = asyncio.run(svc.detect_categories(b"img", 1, _ptypes(["signature", "fingerprint"])))
    assert boxes == []  # never silently retagged onto a requested type


def test_batch_failure_falls_back_to_fanout(svc, monkeypatch):
    calls = []

    async def fake_detect(self, image_data, categories):
        calls.append(list(categories))
        if len(categories) > 1:
            raise RuntimeError("batch endpoint down")
        return [{"category": categories[0], "x": 0.1, "y": 0.1, "width": 0.1, "height": 0.05, "confidence": 0.82}]

    monkeypatch.setattr(LocateAnythingGroundingService, "_post_detect", fake_detect)
    boxes, _ = asyncio.run(svc.detect_categories(b"img", 1, _ptypes(["signature", "fingerprint"])))
    assert {b.type for b in boxes} == {"signature", "fingerprint"}
    assert len(calls) == 3  # 1 failed batch + 2 fan-out


def test_switch_off_keeps_fanout(monkeypatch, svc):
    monkeypatch.setattr("app.services.vision.locate_grounding.settings.VISUAL_DETECT_BATCH_CATEGORIES", False, raising=False)
    sent = []

    async def fake_detect(self, image_data, categories):
        sent.append(list(categories))
        return []

    monkeypatch.setattr(LocateAnythingGroundingService, "_post_detect", fake_detect)
    asyncio.run(svc.detect_categories(b"img", 1, _ptypes(["signature", "fingerprint"])))
    assert len(sent) == 2 and all(len(c) == 1 for c in sent)
