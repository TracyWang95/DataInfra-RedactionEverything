"""Tile-retry machine-code existence identity (0712 医院CT报告单 real case).

A bottom-tile crop loses page context and the grounding model hallucinated the
NetEase watermark logo as a qr_code (and one tile returned itself as one giant
code). A QR/barcode IS machine-decodable by definition, so a tile-retry
candidate of a machine-code type is kept only where the deterministic decoder
proves a code exists. An undecodable "code" carries no extractable payload, so
dropping it cannot leak information — the failure direction is safe by the
definition of the object itself.
"""
import io

import cv2
import numpy as np
import pytest
from PIL import Image

from app.models.schemas import BoundingBox
from app.services.vision.locate_grounding import LocateAnythingGroundingService


def _box(btype: str, x: float, y: float, w: float, h: float) -> BoundingBox:
    return BoundingBox(
        id=f"t_{btype}_{x}", x=x, y=y, width=w, height=h, type=btype, text=btype,
        page=1, confidence=0.82, source="visual_features",
        source_detail="locate_anything:tile_retry", evidence_source="visual_feature_model",
    )


def _page_bytes(with_qr: bool) -> bytes:
    """A white page; optionally with a real decodable QR at the bottom-right."""
    page = np.full((1174, 660, 3), 255, dtype=np.uint8)
    if with_qr:
        qr = cv2.QRCodeEncoder.create().encode("https://example.com/x")
        qr = cv2.resize(qr, (120, 120), interpolation=cv2.INTER_NEAREST)
        qr = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
        page[1000:1120, 480:600] = qr
    else:
        # a round dark watermark logo (the NetEase-style false-positive shape)
        cv2.circle(page, (490, 1150), 12, (40, 40, 40), -1)
    buf = io.BytesIO()
    Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2RGB)).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@pytest.fixture()
def svc() -> LocateAnythingGroundingService:
    return LocateAnythingGroundingService()


def test_undecodable_qr_tile_candidate_is_dropped(svc):
    # candidate points at the watermark logo — no decodable code anywhere
    tile_boxes = [_box("qr_code", 0.72, 0.97, 0.03, 0.02)]
    kept = svc._verify_machine_code_tile_boxes(tile_boxes, _page_bytes(with_qr=False))
    assert kept == []


def test_decodable_qr_keeps_the_intersecting_candidate(svc):
    # real QR at px (480..600, 1000..1120) -> normalized (~0.73..0.91, ~0.85..0.95)
    tile_boxes = [_box("qr_code", 0.74, 0.86, 0.15, 0.08)]
    kept = svc._verify_machine_code_tile_boxes(tile_boxes, _page_bytes(with_qr=True))
    assert len(kept) == 1


def test_candidate_far_from_the_decoded_code_is_dropped(svc):
    # page HAS a real QR, but the candidate points elsewhere (tile hallucination)
    tile_boxes = [_box("qr_code", 0.05, 0.05, 0.05, 0.04)]
    kept = svc._verify_machine_code_tile_boxes(tile_boxes, _page_bytes(with_qr=True))
    assert kept == []


def test_non_code_types_pass_through_untouched(svc):
    tile_boxes = [_box("official_seal", 0.1, 0.1, 0.2, 0.1), _box("fingerprint", 0.5, 0.5, 0.1, 0.08)]
    kept = svc._verify_machine_code_tile_boxes(tile_boxes, _page_bytes(with_qr=False))
    assert kept == tile_boxes


def test_decoder_failure_fails_open_keeps_candidates(svc, monkeypatch):
    # over-mask direction: if the identity check itself breaks, keep the boxes
    monkeypatch.setattr(
        "app.services.vision.locate_grounding.detect_machine_code_regions",
        lambda img: (_ for _ in ()).throw(RuntimeError("cv2 gone")),
    )
    tile_boxes = [_box("qr_code", 0.72, 0.97, 0.03, 0.02)]
    kept = svc._verify_machine_code_tile_boxes(tile_boxes, _page_bytes(with_qr=False))
    assert kept == tile_boxes
