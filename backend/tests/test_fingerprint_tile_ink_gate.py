"""tile指纹候选的印泥内部性闸 (CT报告实证: 相交判定被整tile大框击穿).

红指印=红色印泥沉积→候选框自己的像素里必须有彩色墨(chroma>既有可见墨底噪)。
旧"与任一红色连通域相交"版被巨型幻觉框击穿(X光tile框大到碰到页面红章即过闸,
CT基准7假阳)。内部性=直接量测候选crop。主检测框不过此闸(灰度扫描件真指印
由主检测保留);分析失败fail-open。
"""
import io

import numpy as np
from PIL import Image

from app.models.schemas import BoundingBox
from app.services.vision.locate_grounding import LocateAnythingGroundingService


def _tile_box(btype, x, y, w=0.2, h=0.15):
    return BoundingBox(
        id=f"t_{btype}_{x}", x=x, y=y, width=w, height=h, type=btype, text=btype,
        page=1, confidence=0.82, source="visual_features",
        source_detail="locate_anything:tile_retry", evidence_source="visual_feature_model",
    )


def _page(red_at=None) -> bytes:
    arr = np.full((500, 400, 3), 255, dtype=np.uint8)
    # grey X-ray-ish texture upper half (no chroma)
    arr[50:200, 50:350] = 120
    if red_at:
        rx, ry = red_at
        arr[ry:ry + 40, rx:rx + 40] = (200, 30, 30)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _gate(boxes, page):
    return LocateAnythingGroundingService._verify_fingerprint_tile_boxes(boxes, page)


def test_greyscale_hallucination_dropped():
    # candidate over the grey texture, page HAS red elsewhere (the stamp)
    page = _page(red_at=(100, 400))
    fp = _tile_box("fingerprint", 0.15, 0.1)  # grey zone only
    assert _gate([fp], page) == []


def test_candidate_containing_ink_survives():
    page = _page(red_at=(100, 400))
    fp = _tile_box("fingerprint", 0.2, 0.75, 0.2, 0.15)  # covers the red patch
    assert len(_gate([fp], page)) == 1


def test_giant_box_touching_remote_stamp_still_needs_interior_ink():
    # the defeat case: a huge box whose interior includes the red patch DOES
    # pass (interior evidence), but one that stops short of it does not
    page = _page(red_at=(100, 400))
    short = _tile_box("fingerprint", 0.1, 0.05, 0.7, 0.6)  # big but grey-only
    assert _gate([short], page) == []


def test_non_fingerprint_passes_through():
    sig = _tile_box("signature", 0.15, 0.1)
    assert _gate([sig], _page()) == [sig]


def test_broken_image_fails_open():
    fp = _tile_box("fingerprint", 0.15, 0.1)
    assert _gate([fp], b"not an image") == [fp]
