# Copyright 2026 DataInfra-RedactionEverything Contributors

"""A seal that spans the whole page is degenerate and must never survive.

Belt-and-suspenders against any source (a stale cache, a detector regression)
painting the page as one 公章 — the old scene-flood / ink-snap failure mode.
"""

from app.models.schemas import BoundingBox
from app.services.vision_service import VisionService


def _seal(x, y, w, h):
    return BoundingBox(id="s", x=x, y=y, width=w, height=h, type="official_seal",
                       page=1, source="visual_features")


def test_full_page_seal_dropped():
    # 0.999 = LocateAnything's last coordinate cell (integer/1000) = the border
    boxes = [_seal(0.0, 0.0, 0.999, 0.999)]
    assert VisionService._drop_full_page_seals(boxes) == []


def test_real_stamp_kept():
    boxes = [_seal(0.20, 0.55, 0.20, 0.11)]
    assert len(VisionService._drop_full_page_seals(boxes)) == 1


def test_tall_edge_sliver_kept():
    # a binding sliver can be tall and edge-touching but is NOT full-page
    boxes = [_seal(0.94, 0.0, 0.05, 0.999)]
    assert len(VisionService._drop_full_page_seals(boxes)) == 1


def test_full_page_bank_card_dropped():
    # 银行卡: LA hallucinates the whole document as a card when a crop is upscaled
    b = BoundingBox(id="b", x=0.0, y=0.0, width=0.999, height=0.999,
                    type="bank_card", page=1, source="visual_features")
    assert VisionService._drop_full_page_seals([b]) == []


def test_full_page_text_box_untouched():
    # the guard is scoped to the visual channel; a text box is never page-sized,
    # and OCR/text boxes must pass through regardless
    b = BoundingBox(id="b", x=0.0, y=0.0, width=0.999, height=0.999,
                    type="INSTITUTION_NAME", page=1, source="ocr_has")
    assert VisionService._drop_full_page_seals([b]) == [b]
