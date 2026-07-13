"""P0/P1 调度重排的输出恒等性 (tile/supplements 提前发射只改墙钟不改结果).

- speculative tile: 主检测空的可重试类目立即起 tile 任务, 但收编决策仍由
  retry 段对最终合并框重算 retry_slugs——supplement 补上的类目其 spec 结果
  必须被 await 后丢弃(恒等于今日语义), 绝不 cancel。
- kill switch: VISUAL_TILE_RETRY=False 时任何路径都不允许跑 tile
  (验证员抓的洞: 门控必须同时管投机发射与消费端兜底)。
"""
import asyncio

import pytest

from app.services.vision.locate_grounding import LocateAnythingGroundingService


class _Types:
    def __init__(self, ids):
        self.items = ids

    def __iter__(self):
        from types import SimpleNamespace

        return iter(SimpleNamespace(id=i, name=i, checklist=[], rules=[]) for i in self.items)


def _ptypes(ids):
    from types import SimpleNamespace

    return [SimpleNamespace(id=i, name=i, checklist=[], rules=[]) for i in ids]


@pytest.fixture()
def svc(monkeypatch):
    service = LocateAnythingGroundingService()
    # silence unrelated supplements/physical gates
    monkeypatch.setattr("app.services.vision.locate_grounding.settings.HAS_IMAGE_URL", "", raising=False)
    monkeypatch.setattr("app.services.vision.locate_grounding.settings.LA_SIGNATURE_URL", "", raising=False)
    monkeypatch.setattr("app.services.vision.locate_grounding.settings.VISUAL_SEAL_COLOR_CASCADE", False, raising=False)
    monkeypatch.setattr("app.services.vision.locate_grounding.settings.VISUAL_EDGE_SEAL_REFINE", False, raising=False)
    monkeypatch.setattr(
        LocateAnythingGroundingService,
        "_drop_solid_fill_seals",
        lambda self, boxes, image_data: boxes,
    )
    monkeypatch.setattr(
        LocateAnythingGroundingService,
        "_drop_skin_hue_fingerprints",
        lambda self, boxes, image_data: boxes,
    )
    monkeypatch.setattr(
        LocateAnythingGroundingService,
        "_snap_fingerprints_to_ink",
        staticmethod(lambda boxes, image_data: boxes),
    )
    return service


def test_spec_tile_result_joins_when_type_still_missing(svc, monkeypatch):
    tile_calls = []

    async def fake_detect(self, image_data, categories):
        return []  # main detect: nothing found

    async def fake_tiles(self, image_data, page, slugs, tiles_for=None, source_detail="", queries=None):
        tile_calls.append(list(slugs))
        return [_bb("fingerprint", 0.3, 0.2)]

    monkeypatch.setattr(LocateAnythingGroundingService, "_post_detect", fake_detect)
    monkeypatch.setattr(LocateAnythingGroundingService, "_detect_on_tiles", fake_tiles)
    boxes, _ = asyncio.run(svc.detect_categories(b"img", 1, _ptypes(["fingerprint"])))
    assert [b.type for b in boxes] == ["fingerprint"]
    assert tile_calls == [["fingerprint"]]  # fired exactly once (speculatively)


def test_spec_tile_overlapping_supplement_dropped_new_position_kept(svc, monkeypatch):
    """立案告知书门控放宽后的新契约: tile恒跑,同类gap-filter去重——与已有框
    相交的tile候选=zoom复述(丢),不相交的=全帧漏掉的新实例(收)。"""
    async def fake_detect(self, image_data, categories):
        return []

    async def fake_tiles(self, image_data, page, slugs, tiles_for=None, source_detail="", queries=None):
        return [
            _bb("official_seal", 0.1, 0.1),  # overlaps the YOLO box -> dropped
            _bb("official_seal", 0.5, 0.5),  # new position -> kept
        ]

    async def fake_yolo(self, base_url, image_data, page, slugs):
        return [_bb("official_seal", 0.1, 0.1)]

    monkeypatch.setattr("app.services.vision.locate_grounding.settings.HAS_IMAGE_URL", "http://x", raising=False)
    monkeypatch.setattr(LocateAnythingGroundingService, "_post_detect", fake_detect)
    monkeypatch.setattr(LocateAnythingGroundingService, "_detect_on_tiles", fake_tiles)
    monkeypatch.setattr(LocateAnythingGroundingService, "_detect_has_image", fake_yolo)
    boxes, _ = asyncio.run(svc.detect_categories(b"img", 1, _ptypes(["official_seal"])))
    xs = sorted(round(b.x, 2) for b in boxes if b.type == "official_seal")
    assert xs == [0.1, 0.5]


def test_kill_switch_blocks_every_tile_path(svc, monkeypatch):
    tile_calls = []

    async def fake_detect(self, image_data, categories):
        return []

    async def fake_tiles(self, image_data, page, slugs, tiles_for=None, source_detail="", queries=None):
        tile_calls.append(list(slugs))
        return [_bb("fingerprint", 0.3, 0.2)]

    monkeypatch.setattr("app.services.vision.locate_grounding.settings.VISUAL_TILE_RETRY", False, raising=False)
    monkeypatch.setattr(LocateAnythingGroundingService, "_post_detect", fake_detect)
    monkeypatch.setattr(LocateAnythingGroundingService, "_detect_on_tiles", fake_tiles)
    boxes, _ = asyncio.run(svc.detect_categories(b"img", 1, _ptypes(["fingerprint"])))
    assert boxes == []
    assert tile_calls == []  # zero tile invocations anywhere with the flag off


def _bb(btype, x, y):
    from app.models.schemas import BoundingBox

    return BoundingBox(
        id=f"t_{btype}_{x}", x=x, y=y, width=0.1, height=0.05, type=btype, text=btype,
        page=1, confidence=0.82, source="visual_features",
        source_detail="locate_anything:tile_retry", evidence_source="visual_feature_model",
    )
