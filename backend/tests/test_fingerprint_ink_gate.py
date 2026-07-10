"""Fingerprint skin-hue gate: a 'fingerprint' box on the photographer's REAL
thumb (holding the page) must be dropped; boxes on crimson stamp-pad ink must
survive.

Physics (measured on the five-contract 5090 corpus, 2026-07-10): stamp-pad
ink absorbs BOTH green and blue — inside a real print the colored pixels have
G≈B, hue ratio (G-B)/(R-G) ≤ 0.12 on all 7 measured prints. Skin is orange —
G runs well above B, ratio ≥ 0.57 on both measured thumbs. Naive redness
(R-G) does NOT separate them (thumb 47-53 vs print 55-76, overlapping): warm
phone lighting makes skin "red". The gate lives at the same spot as the
solid-fill seal arbitration and never drops a box without colored-pixel
evidence (a faint print measuring no ink is KEPT — missing PII outranks a
false box).
"""
import io

import numpy as np
from PIL import Image

from app.models.schemas import BoundingBox
from app.services.vision.locate_grounding import LocateAnythingGroundingService


def _image_bytes(array: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(array.astype(np.uint8), "RGB").save(buf, format="PNG")
    return buf.getvalue()


def _page_with_patch(patch_rgb: tuple[int, int, int], sparse: bool = False) -> bytes:
    """A white page (100x100) with a colored patch in its center (30..70)."""
    page = np.full((100, 100, 3), 245, dtype=np.int16)
    patch = np.full((40, 40, 3), 245, dtype=np.int16)
    if sparse:
        # stamp impression: ink dots with paper showing through
        patch[::2, ::2] = patch_rgb
    else:
        patch[:, :] = patch_rgb
    page[30:70, 30:70] = patch
    return _image_bytes(page)


def _fp_box(box_id: str = "fp1") -> BoundingBox:
    return BoundingBox(
        id=box_id, x=0.3, y=0.3, width=0.4, height=0.4,
        type="fingerprint", text="指纹", page=1, confidence=0.8,
        source="visual_features", source_detail="locate_anything:tile_retry",
    )


def _gate(image_data: bytes, boxes: list[BoundingBox]) -> list[BoundingBox]:
    return LocateAnythingGroundingService()._drop_skin_hue_fingerprints(boxes, image_data)


def test_crimson_print_survives() -> None:
    # stamp-pad crimson: R high, G and B both absorbed (G≈B)
    kept = _gate(_page_with_patch((185, 45, 55), sparse=True), [_fp_box()])
    assert len(kept) == 1


def test_skin_thumb_dropped() -> None:
    # skin: orange — G well above B
    kept = _gate(_page_with_patch((210, 160, 110)), [_fp_box()])
    assert kept == []


def test_no_colored_pixels_keeps_box() -> None:
    # a faint print with no measurable ink: no evidence -> never drop PII
    kept = _gate(_page_with_patch((240, 240, 240)), [_fp_box()])
    assert len(kept) == 1


def test_gate_scoped_to_fingerprint_type() -> None:
    seal = BoundingBox(
        id="seal1", x=0.3, y=0.3, width=0.4, height=0.4,
        type="official_seal", text="公章", page=1, confidence=0.8,
        source="visual_features", source_detail="locate_anything:detect",
    )
    kept = _gate(_page_with_patch((210, 160, 110)), [seal])
    assert len(kept) == 1  # non-fingerprint boxes are untouched


def test_env_switch_disables_gate(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "VISUAL_FINGERPRINT_INK_GATE", False, raising=False)
    kept = _gate(_page_with_patch((210, 160, 110)), [_fp_box()])
    assert len(kept) == 1
