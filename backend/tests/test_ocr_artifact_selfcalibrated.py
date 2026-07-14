"""Self-calibrated OCR-artifact filtering (R9).

Replaces the magic-number arbiters in ocr_artifact_filter with document-scale
signals, WITHOUT ever shrinking PII coverage:

  * page-edge artifact: judged against the OCR body-text hull (+ a CJK-em
    self-calibrated margin), not a fixed normalized pixel offset. Two scans of
    the same page at different DPI reach the SAME verdict, where a fixed 0.015
    offset flips.
  * ink gate: an Otsu leak-guard sits in front of the delete branch so a
    low-contrast light-ink signature (that the fixed luminance-185 cut reads as
    blank) is KEPT; a weak/unavailable bimodality also KEEPS (fail toward
    over-coverage).

All fixtures are synthetic numpy grayscale arrays — offline, no GPU/network.
"""
import numpy as np
from PIL import Image

from app.services.vision.ocr_artifact_filter import (
    _INK_DARK_MAX,
    _LEFT_EDGE_MAX_X,
    is_page_edge_ocr_artifact,
    region_has_visible_ink,
    text_evidence_hull,
)


# --------------------------------------------------------------------------- #
# page-edge artifact — OCR-hull self-calibration
# --------------------------------------------------------------------------- #

def test_fixed_offset_flips_but_hull_verdict_is_resolution_invariant() -> None:
    # A fixed-absolute left scanner strip (8px in, 80px wide, sitting in the
    # vertical middle so no corner/top/bottom rule applies) textless, on the
    # SAME page scanned at two DPIs where the body content occupies more pixels
    # at higher DPI.
    #
    # Fixed 0.015 offset: at 500px the strip's x = 8/500 = 0.016 (> 0.015) so the
    # left-edge rule MISSES it (kept); at 1000px x = 8/1000 = 0.008 (<= 0.015)
    # with width 80/1000 = 0.08 (>= 0.08) so it FIRES (dropped). Same physical
    # artifact, opposite verdict.
    assert _LEFT_EDGE_MAX_X == 0.015
    lo = is_page_edge_ocr_artifact(8, 200, 80, 200, 500, 600, "PERSON", None)
    hi = is_page_edge_ocr_artifact(8, 400, 80, 400, 1000, 1200, "PERSON", None)
    assert lo is False and hi is True  # the fixed-offset arbiter flips with DPI

    # Hull-calibrated: body hull to the right of the strip in both scans (scaled
    # with the content); em = line height. The strip is clear of the body at
    # both DPIs, so the verdict is consistent.
    hull_lo, em_lo = (140, 50, 460, 550), 20.0
    hull_hi, em_hi = (280, 100, 920, 1100), 40.0
    v_lo = is_page_edge_ocr_artifact(
        8, 200, 80, 200, 500, 600, "PERSON", None, hull_lo, em_lo
    )
    v_hi = is_page_edge_ocr_artifact(
        8, 400, 80, 400, 1000, 1200, "PERSON", None, hull_hi, em_hi
    )
    assert v_lo is True and v_hi is True  # consistent: dropped at BOTH DPIs


def test_hull_keeps_textless_region_overlapping_body() -> None:
    # A textless region that overlaps the body-text hull is content-adjacent,
    # never a margin artifact — kept even though it hugs the left edge.
    hull, em = (60, 50, 440, 550), 20.0
    assert not is_page_edge_ocr_artifact(
        8, 100, 100, 400, 500, 600, "PERSON", None, hull, em
    )


def test_hull_drops_textless_region_clear_of_body() -> None:
    hull, em = (140, 50, 460, 550), 20.0
    # strip right edge 98 < hull_left(140) - em(20) = 120 -> clear of body
    assert is_page_edge_ocr_artifact(
        8, 0, 90, 600, 500, 600, "PERSON", None, hull, em
    )


def test_hull_substantial_text_is_exempt_even_outside_body() -> None:
    hull, em = (140, 50, 460, 550), 20.0
    assert not is_page_edge_ocr_artifact(
        8, 0, 90, 600, 500, 600, "DATE", "2025年12月23日", hull, em
    )


def test_hull_visual_type_is_exempt() -> None:
    hull, em = (140, 50, 460, 550), 20.0
    assert not is_page_edge_ocr_artifact(
        8, 0, 90, 600, 500, 600, "SIGNATURE", None, hull, em
    )


def test_no_hull_falls_back_to_legacy_geometry() -> None:
    # With no text evidence to bound the body, the legacy geometric signature is
    # preserved (back-compat with the bottom-edge recall fix).
    assert is_page_edge_ocr_artifact(20, 605, 460, 6, 500, 611, "DATE", None)
    assert not is_page_edge_ocr_artifact(
        170, 358, 142, 12, 500, 611, "DATE", "【2025】年【12】月【23】日"
    )


def test_text_evidence_hull_self_calibrates_from_regions() -> None:
    class R:
        def __init__(self, left, top, width, height, text, etype):
            self.left, self.top, self.width, self.height = left, top, width, height
            self.text, self.entity_type = text, etype

    regions = [
        R(140, 50, 120, 20, "张三", "PERSON"),
        R(200, 300, 260, 22, "2025年12月23日", "DATE"),
        R(8, 0, 90, 600, None, "PERSON"),          # textless strip -> excluded
        R(300, 400, 40, 40, None, "SIGNATURE"),     # visual -> excluded
    ]
    hull, em = text_evidence_hull(regions)
    assert hull == (140, 50, 460, 322)
    assert em == 22.0  # upper median of the two text-region heights (20, 22)

    assert text_evidence_hull([R(8, 0, 90, 600, None, "PERSON")]) == (None, None)


# --------------------------------------------------------------------------- #
# ink gate — Otsu leak-guard
# --------------------------------------------------------------------------- #

def _gray_image(arr2d: np.ndarray) -> Image.Image:
    rgb = np.repeat(arr2d.astype(np.uint8)[:, :, None], 3, axis=2)
    return Image.fromarray(rgb, "RGB")


def test_low_contrast_light_signature_kept_where_185_reads_blank() -> None:
    # Light-gray strokes (value 200) on white (255): every pixel is brighter
    # than the fixed luminance-185 ink cut, so the old density test reads the
    # crop as blank and would DROP it. Otsu finds the real 200/255 split and the
    # region is kept.
    assert 200 > _INK_DARK_MAX  # the light ink is invisible to the fixed cut
    arr = np.full((30, 60), 255, dtype=np.uint8)
    arr[10:20, 5:55] = 200  # ~27% coverage of light ink
    img = _gray_image(arr)
    # sanity: fixed-cut density is below any floor
    assert np.count_nonzero(arr < _INK_DARK_MAX) == 0
    assert region_has_visible_ink(img, 0, 0, 60, 30) is True


def test_weak_bimodality_region_is_kept() -> None:
    # A near-uniform crop has no trustworthy foreground/background split; the
    # fixed test would drop it (no dark pixels) but the guard KEEPS it (a faint
    # signature could hide in a weak second mode Otsu folds into paper).
    arr = np.full((30, 60), 235, dtype=np.uint8)
    assert region_has_visible_ink(_gray_image(arr), 0, 0, 60, 30) is True


def test_strong_bimodal_blank_strip_still_dropped() -> None:
    # A genuinely blank paper strip with a negligible dark speck: strong bimodal
    # split, foreground far below the density floor, fixed cut also blank -> the
    # region is still dropped (coverage of the old blank-strip filter preserved).
    arr = np.full((30, 60), 250, dtype=np.uint8)
    arr[0, 0:5] = 30  # 5 / 1800 = 0.3% dark, below the 0.8% floor
    assert region_has_visible_ink(_gray_image(arr), 0, 0, 60, 30) is False


def test_dense_dark_text_region_kept() -> None:
    arr = np.full((30, 60), 255, dtype=np.uint8)
    arr[5:25, 5:40] = 20  # dense dark glyph mass
    assert region_has_visible_ink(_gray_image(arr), 0, 0, 60, 30) is True


def test_visual_type_never_ink_gated_off() -> None:
    # A visual feature carries no OCR text; even a blank crop must never be
    # dropped by the ink gate.
    arr = np.full((30, 60), 250, dtype=np.uint8)
    arr[0, 0:5] = 30
    assert region_has_visible_ink(_gray_image(arr), 0, 0, 60, 30, "SIGNATURE") is True


def test_red_ink_still_kept() -> None:
    # Crimson stamp ink (R high, G/B low) is kept by the red-channel signal,
    # unchanged.
    rgb = np.full((30, 60, 3), 255, dtype=np.uint8)
    rgb[10:20, 5:55] = (185, 45, 55)
    img = Image.fromarray(rgb, "RGB")
    assert region_has_visible_ink(img, 0, 0, 60, 30) is True
