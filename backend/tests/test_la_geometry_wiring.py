"""R7w: 把已提交的 leak-safe 纵向收紧核心 (_adopt_la_vertical_geometry) 接进管线。

本文件只测"接线胶水"是否正确, 不冒充真实 GPU/真实图像结果:
  - ground_handwriting: mock _post_detect -> 产出 type=handwriting 的 BoundingBox,
    且每个 query 都是"单类顺序"调用 (LA 共享提示塌召回 + 负载敏感, 必须顺序单类)。
  - _measure_ink_hulls: 合成 numpy 灰度图 (一行暗笔画 + 满宽下划线 + 相邻行墨迹) ->
    测出的 ink_hull 覆盖笔画、排除下划线、限制在 LA 行窗口内 (相邻行不混入)。
  - _tighten_la_vertical_geometry (接线集成): 过高框 + 匹配 LA + 墨迹 hull ->
    框收紧到 hull(LA∪墨迹) 且不低于墨迹; LA 空 / env 关 -> all_boxes 不变。

0 泄露: 收紧恒 = hull(LA∪实测墨迹), 永不缩到墨迹以下; 缺墨迹/LA/env关 -> 原过覆盖框。
"""
import asyncio
import io

import numpy as np
from PIL import Image

from app.core.config import settings
from app.models.schemas import BoundingBox
from app.services.vision.locate_grounding import (
    _HANDWRITING_GROUNDING_QUERIES,
    LocateAnythingGroundingService,
)
from app.services.vision_service import VisionService


def _run(coro):
    return asyncio.run(coro)


def _ocr(x, y, w, h, id_, text="v", type_="ID_CARD"):
    return BoundingBox(id=id_, x=x, y=y, width=w, height=h, type=type_,
                       text=text, page=1, confidence=0.9, source="ocr_has")


def _la(x, y, w, h):
    return BoundingBox(id=f"la{x}{y}", x=x, y=y, width=w, height=h, type="handwriting",
                       text="", page=1, confidence=0.82, source="visual_features")


# ---- (1) ground_handwriting -------------------------------------------------

def test_ground_handwriting_makes_handwriting_boxes_sequentially():
    svc = LocateAnythingGroundingService()
    calls = []

    async def fake_post_detect(image_data, categories):
        # record each call; assert single-category (no shared-prompt fan-in)
        calls.append(list(categories))
        return [{"x": 0.3, "y": 0.4, "width": 0.2, "height": 0.05, "confidence": 0.77}]

    svc._post_detect = fake_post_detect
    out = _run(svc.ground_handwriting(b"img", ["handwritten number", "handwritten name"], page=3))
    # one box per query, all tagged handwriting / visual_features, empty text
    assert len(out) == 2
    for b in out:
        assert b.type == "handwriting"
        assert b.source == "visual_features"
        assert b.text == ""
        assert b.page == 3
        assert abs(b.confidence - 0.77) < 1e-9
    # every call carried exactly ONE category (sequential single-class)
    assert calls == [["handwritten number"], ["handwritten name"]]


def test_ground_handwriting_defaults_to_constant_queries():
    svc = LocateAnythingGroundingService()
    seen = []

    async def fake_post_detect(image_data, categories):
        seen.append(categories[0])
        return []

    svc._post_detect = fake_post_detect
    _run(svc.ground_handwriting(b"img"))
    assert seen == list(_HANDWRITING_GROUNDING_QUERIES)


def test_ground_handwriting_swallows_one_query_failure():
    svc = LocateAnythingGroundingService()

    async def fake_post_detect(image_data, categories):
        if categories[0] == "boom":
            raise RuntimeError("GPU down")
        return [{"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.02}]

    svc._post_detect = fake_post_detect
    out = _run(svc.ground_handwriting(b"img", ["boom", "ok"]))
    assert len(out) == 1  # failed query skipped, other still produced a box


# ---- (2) _measure_ink_hulls -------------------------------------------------

def _synthetic_ink_page() -> Image.Image:
    """100x100 white page:
      - handwriting strokes at rows 42-46 (broken short runs, cols 32-40 & 48-58)
      - a FULL-WIDTH underline at row 60 (cols 30-60) -> must be excluded
      - neighbour-row ink at rows 10-14 (above the LA window) -> must NOT mix in
      - another row's ink at rows 74-76 (below the LA window) -> must NOT mix in
    """
    arr = np.full((100, 100, 3), 255, np.uint8)
    for r in range(42, 47):
        arr[r, 32:40] = 0
        arr[r, 48:58] = 0
    arr[60, 30:60] = 0            # full-width underline
    arr[10:15, 32:58] = 0         # neighbour row above window
    arr[74:77, 32:58] = 0         # neighbour row below window
    return Image.fromarray(arr, "RGB")


def test_measure_ink_hull_covers_stroke_excludes_underline_and_neighbours():
    svc = VisionService()
    img = _synthetic_ink_page()
    box = _ocr(0.30, 0.30, 0.30, 0.30, id_="v1")   # cols 30-60, cy=0.45
    la = _la(0.30, 0.40, 0.30, 0.10)               # [0.40,0.50] contains cy; window [0.30,0.70]
    hulls = svc._measure_ink_hulls(img, [box], [la])
    assert "v1" in hulls
    top, bottom = hulls["v1"]
    # strokes rows 42-46 -> [0.42, 0.47]; underline row 60 excluded; neighbours outside window
    assert abs(top - 0.42) < 1e-6
    assert abs(bottom - 0.47) < 1e-6


def test_measure_ink_hull_no_la_match_absent():
    svc = VisionService()
    img = _synthetic_ink_page()
    box = _ocr(0.30, 0.30, 0.30, 0.30, id_="v1")
    la_other_col = _la(0.75, 0.40, 0.20, 0.10)     # no x-overlap
    assert svc._measure_ink_hulls(img, [box], [la_other_col]) == {}


def test_measure_ink_hull_empty_when_no_la():
    svc = VisionService()
    img = _synthetic_ink_page()
    box = _ocr(0.30, 0.30, 0.30, 0.30, id_="v1")
    assert svc._measure_ink_hulls(img, [box], []) == {}


# ---- (3) _tighten_la_vertical_geometry: full wiring -------------------------

def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _wire_fixture(monkeypatch, la_boxes):
    """A VisionService whose grounding returns `la_boxes` and whose image is the
    synthetic ink page; several short normal boxes calibrate the line height."""
    svc = VisionService()
    img_bytes = _png_bytes(_synthetic_ink_page())

    async def get_image_data():
        return img_bytes

    async def fake_ground(image_data, queries=None, page=1):
        return list(la_boxes)

    monkeypatch.setattr(svc.visual_grounding, "ground_handwriting", fake_ground)
    # 3 short normal-height text boxes (line height ~0.03) + 1 over-tall value box
    boxes = [
        _ocr(0.10, 0.10, 0.20, 0.03, id_="n1", text="label"),
        _ocr(0.10, 0.20, 0.20, 0.03, id_="n2", text="label"),
        _ocr(0.10, 0.60, 0.20, 0.03, id_="n3", text="label"),
        _ocr(0.30, 0.30, 0.30, 0.30, id_="v1", text="张三"),   # cy=0.45, oversize
    ]
    return svc, boxes, get_image_data


def test_wire_tightens_oversize_box_to_hull_of_la_and_ink(monkeypatch):
    monkeypatch.setattr(settings, "VISION_LA_VERTICAL_TIGHTEN", True, raising=False)
    la = _la(0.30, 0.40, 0.30, 0.10)   # [0.40,0.50] contains cy 0.45
    svc, boxes, get_image_data = _wire_fixture(monkeypatch, [la])
    out = _run(svc._tighten_la_vertical_geometry(boxes, get_image_data, page=1))
    v1 = next(b for b in out if b.id == "v1")
    # hull(LA [0.40,0.50] ∪ ink [0.42,0.47]) = [0.40,0.50]
    assert abs(v1.y - 0.40) < 1e-6
    assert abs((v1.y + v1.height) - 0.50) < 1e-6
    # tightened well below the original 0.30, and never below the measured ink
    assert v1.height < 0.30 - 1e-9
    assert v1.y <= 0.42 + 1e-9 and (v1.y + v1.height) >= 0.47 - 1e-9
    # normal boxes untouched
    assert next(b for b in out if b.id == "n1").height == 0.03


def test_wire_env_off_returns_boxes_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "VISION_LA_VERTICAL_TIGHTEN", False, raising=False)
    la = _la(0.30, 0.40, 0.30, 0.10)
    svc, boxes, get_image_data = _wire_fixture(monkeypatch, [la])
    out = _run(svc._tighten_la_vertical_geometry(boxes, get_image_data, page=1))
    assert out is boxes  # identity: no work done, no image fetched


def test_wire_empty_la_keeps_original(monkeypatch):
    monkeypatch.setattr(settings, "VISION_LA_VERTICAL_TIGHTEN", True, raising=False)
    svc, boxes, get_image_data = _wire_fixture(monkeypatch, [])
    out = _run(svc._tighten_la_vertical_geometry(boxes, get_image_data, page=1))
    v1 = next(b for b in out if b.id == "v1")
    assert (v1.y, v1.height) == (0.30, 0.30)   # unchanged


def test_wire_no_matching_la_column_keeps_original(monkeypatch):
    monkeypatch.setattr(settings, "VISION_LA_VERTICAL_TIGHTEN", True, raising=False)
    la_other = _la(0.75, 0.40, 0.20, 0.10)     # different column
    svc, boxes, get_image_data = _wire_fixture(monkeypatch, [la_other])
    out = _run(svc._tighten_la_vertical_geometry(boxes, get_image_data, page=1))
    v1 = next(b for b in out if b.id == "v1")
    assert (v1.y, v1.height) == (0.30, 0.30)   # unchanged
