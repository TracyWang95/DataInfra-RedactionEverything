"""Fallback visual detectors for official seals.

PaddleOCR-VL and LocateAnything are the primary model paths. This module covers
practical scanned-document seal cases that still benefit from lightweight image
analysis when model confidence is low or unavailable.
"""
from __future__ import annotations

import weakref
from dataclasses import dataclass

from PIL import Image

try:
    import cv2
    import numpy as np

    _VISION_DEPS_MISSING = False
except Exception:
    cv2 = None
    np = None
    _VISION_DEPS_MISSING = True
_PREPARED_IMAGE_CACHE: list[tuple[weakref.ReferenceType[Image.Image], tuple[int, int], object, object]] = []
_RED_WORK_MAX_SIDE = 1800
_DARK_WORK_MAX_SIDE = 1800
_LOCAL_SEAL_MAX_PAGE_ASPECT = 3.0

# Default confidence reported for color (red) seal regions.
_RED_SEAL_CONFIDENCE = 0.72
# Confidence reported for dark/copied seal regions (lower than red).
_DARK_SEAL_CONFIDENCE = 0.66

# Red color thresholds (HSV hue wraps around at red).
_RED_HUE_LOW_MAX = 12
_RED_HUE_HIGH_MIN = 168
_RED_SAT_MIN = 55
_RED_VAL_MIN = 45
# Relaxed saturation used when building the red-exclusion mask for the dark pass.
_RED_EXCLUSION_SAT_MIN = 45
# RGB dominance gate ensuring the red channel clearly leads green/blue.
_RED_RGB_R_MIN = 115
_RED_RGB_R_OVER_G = 1.18
_RED_RGB_R_OVER_B = 1.12

# Red mask morphology: kernel size is min(w, h) divided by this factor.
_RED_KERNEL_SIDE_DIVISOR = 170
_RED_KERNEL_MIN = 3
_RED_DILATE_ITERATIONS = 2

# Red candidate area gates as fractions of page area.
_RED_MIN_AREA_RATIO = 0.000025
_RED_MIN_AREA_FLOOR = 16
_RED_MAX_BOX_AREA_RATIO = 0.12

# Page-edge proximity fractions used to flag near-edge / seam candidates.
_EDGE_MARGIN_RATIO = 0.04
_EDGE_FAR_RATIO = 0.96
# Red candidate size gates relative to the shorter page side.
_RED_LARGE_SIDE_RATIO = 0.035
_RED_MIN_SIDE_RATIO = 0.006
_RED_MIN_SIDE_FLOOR = 5
# Red stamp-like density / aspect acceptance window.
_RED_DENSITY_MIN = 0.018
_RED_DENSITY_MAX = 0.88
_RED_ASPECT_MIN = 0.10
_RED_ASPECT_MAX = 10.0
# Seam (thin edge-fragment) aspect windows around the stamp aspect window.
_RED_SEAM_ASPECT_LOW = 0.035
_RED_SEAM_ASPECT_HIGH = 28.0
_RED_SEAM_LARGE_SIDE_RATIO = 0.07
_RED_SEAM_MIN_SIDE_RATIO = 0.004
_RED_SEAM_MIN_SIDE_FLOOR = 4

# Red candidate score weighting.
_RED_SCORE_AREA_COEFF = 120
_RED_SCORE_AREA_CAP = 0.6
_RED_SCORE_SEAM_BONUS = 0.28
_RED_SCORE_EDGE_BONUS = 0.2

# Output padding for red regions relative to the shorter page side.
_RED_REGION_PAD_RATIO = 0.004
_REGION_PAD_FLOOR = 2

# Tighten-box padding relative to the shorter page side.
_TIGHTEN_PAD_RATIO = 0.0025

# Gutter-split gates (split adjacent red seals on a blank gutter).
_GUTTER_RIGHT_EDGE_RATIO = 0.94
_GUTTER_SEAM_ASPECT_MAX = 0.38
_GUTTER_MIN_BOX_AREA_RATIO = 0.012
_GUTTER_MIN_INK = 80
_GUTTER_PIECE_MIN_AREA_RATIO = 0.004

# Blank-gutter detection geometry.
_GUTTER_MIN_GAP_RATIO = 0.006
_GUTTER_MIN_GAP_FLOOR = 5
_GUTTER_MIN_SIDE_RATIO = 0.055
_GUTTER_MIN_SIDE_FLOOR = 24
_GUTTER_MIN_INK_BALANCE_RATIO = 0.22

# Stacked-seal split gates.
_STACK_MIN_BOX_AREA_RATIO = 0.025
_STACK_MIN_HEIGHT_RATIO = 0.22
_STACK_ASPECT_MIN = 0.35
_STACK_ASPECT_MAX = 1.35
_STACK_MIN_INK_POINTS = 80
_STACK_SEED_LOW_PERCENTILE = 30
_STACK_SEED_HIGH_PERCENTILE = 70
_STACK_SEED_MIN_GAP_RATIO = 0.18
_STACK_KMEANS_ITERATIONS = 12
_STACK_MIN_SEPARATION_RATIO = 0.30
_STACK_MIN_CLUSTER_RATIO = 0.22
_STACK_PAD_RATIO = 0.003
_STACK_MIN_CLUSTER_POINTS = 30
_STACK_CLUSTER_MIN_AREA_RATIO = 0.004

# Dark seal color / morphology thresholds.
_DARK_GRAY_MAX = 118
_DARK_CLOSE_SIDE_DIVISOR = 95
_DARK_CLOSE_MIN = 5
_DARK_DILATE_SIDE_DIVISOR = 145
_DARK_DILATE_MIN = 3

# Dark candidate area gates.
_DARK_MIN_AREA_RATIO = 0.00045
_DARK_MIN_AREA_FLOOR = 60
_DARK_MAX_BOX_AREA_RATIO = 0.09
# Above this box-area fraction, large non-edge boxes get circle refinement.
_DARK_REFINE_BOX_AREA_RATIO = 0.045

# Dark candidate size / shape acceptance.
_DARK_LARGE_SIDE_RATIO = 0.085
_DARK_LARGE_MIN_SIDE_RATIO = 0.045
_DARK_SEAM_ASPECT_LOW = 0.06
_DARK_SEAM_ASPECT_HIGH = 0.25
_DARK_SEAM_LARGE_SIDE_RATIO = 0.09
_DARK_SEAM_MIN_SIDE_RATIO = 0.006
_DARK_SEAM_MIN_SIDE_FLOOR = 5
_DARK_ROUNDISH_ASPECT_MIN = 0.42
_DARK_ROUNDISH_ASPECT_MAX = 1.9
_DARK_EDGE_ASPECT_MIN = 0.25
_DARK_EDGE_ASPECT_MAX = 3.2
_DARK_DENSITY_MIN = 0.025
_DARK_DENSITY_SEAM_MAX = 0.86
_DARK_DENSITY_MAX = 0.52

# Dark border/center darkness checks.
_DARK_BORDER_DIVISOR = 8
_DARK_BORDER_PIXEL_MAX = 135
_DARK_MIN_DARK_RATIO = 0.015
_DARK_BORDER_VS_CENTER_RATIO = 0.5

# Dark candidate score weighting.
_DARK_SCORE_BORDER_COEFF = 0.7
_DARK_SCORE_AREA_COEFF = 80
_DARK_SCORE_AREA_CAP = 0.45
_DARK_SCORE_SEAM_BONUS = 0.26
_DARK_SCORE_EDGE_BONUS = 0.18

# Output padding for dark regions relative to the shorter page side.
_DARK_REGION_PAD_RATIO = 0.006

# Circle-refinement (Hough) parameters for large dark seal boxes.
_CIRCLE_MIN_RADIUS_RATIO = 0.045
_CIRCLE_MIN_RADIUS_FLOOR = 18
_CIRCLE_MAX_RADIUS_RATIO = 0.55
_CIRCLE_MEDIAN_BLUR_KSIZE = 5
_CIRCLE_HOUGH_DP = 1.2
_CIRCLE_HOUGH_MIN_DIST_DIVISOR = 4
_CIRCLE_HOUGH_MIN_DIST_FLOOR = 28
_CIRCLE_HOUGH_PARAM1 = 100
_CIRCLE_HOUGH_PARAM2 = 24
_CIRCLE_PAD_RATIO = 0.10
_CIRCLE_PAD_FLOOR = 3
_CIRCLE_MAX_AREA_RATIO = 0.05
_CIRCLE_ASPECT_MIN = 0.55
_CIRCLE_ASPECT_MAX = 1.65
_CIRCLE_MIN_DARK_RATIO = 0.025
_CIRCLE_SCORE_RADIUS_CAP = 0.20

# Dominant rule-line (table border) coverage thresholds.
_RULE_LINE_DARK_MAX = 135
_RULE_LINE_COVERAGE = 0.82

# Box-merge gap relative to the shorter page side.
_MERGE_GAP_RATIO = 0.018
_MERGE_GAP_FLOOR = 8

# Curved-seam arc detection thresholds.
_SEAM_MIN_SAMPLE_RATIO = 0.18
_SEAM_MIN_SAMPLE_FLOOR = 8
_SEAM_SPAN_MIN = 0.18
_SEAM_STD_MIN = 0.055


@dataclass(frozen=True)
class SealRegion:
    x: float
    y: float
    width: float
    height: float
    confidence: float = _RED_SEAL_CONFIDENCE


def _vision_deps():
    global cv2, np, _VISION_DEPS_MISSING
    if _VISION_DEPS_MISSING:
        return None
    if cv2 is not None and np is not None:
        return cv2, np
    try:
        import cv2
        import numpy as np
    except Exception:
        _VISION_DEPS_MISSING = True
        return None
    return cv2, np


def _remember_prepared_image(image: Image.Image, size: tuple[int, int], arr, red_exclusion_mask) -> None:
    try:
        image_ref = weakref.ref(image)
    except TypeError:
        return
    _PREPARED_IMAGE_CACHE[:] = [
        item
        for item in _PREPARED_IMAGE_CACHE
        if item[0]() is not None and not (item[0]() is image and item[1] == size)
    ]
    _PREPARED_IMAGE_CACHE.append((image_ref, size, arr, red_exclusion_mask))
    del _PREPARED_IMAGE_CACHE[:-2]






def _tighten_red_seal_box(
    raw_mask,
    box: tuple[int, int, int, int],
    page_width: int,
    page_height: int,
) -> tuple[int, int, int, int]:
    """Tighten a morphology-expanded red seal box to the original red ink."""
    deps = _vision_deps()
    if deps is None:
        return box
    _cv2, np = deps

    x, y, bw, bh = box
    if bw <= 0 or bh <= 0:
        return box

    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(page_width, x + bw)
    y2 = min(page_height, y + bh)
    if x2 <= x1 or y2 <= y1:
        return box

    roi = raw_mask[y1:y2, x1:x2] > 0
    if roi.size == 0:
        return box
    ys, xs = np.nonzero(roi)
    if xs.size == 0:
        return box

    pad = max(1, int(round(min(page_width, page_height) * _TIGHTEN_PAD_RATIO)))
    nx1 = max(0, x1 + int(xs.min()) - pad)
    ny1 = max(0, y1 + int(ys.min()) - pad)
    nx2 = min(page_width, x1 + int(xs.max()) + pad + 1)
    ny2 = min(page_height, y1 + int(ys.max()) + pad + 1)
    if nx2 <= nx1 or ny2 <= ny1:
        return box
    return (nx1, ny1, nx2 - nx1, ny2 - ny1)


def _split_red_seal_box_by_gutter(
    raw_mask,
    box: tuple[int, int, int, int],
    page_width: int,
    page_height: int,
) -> list[tuple[int, int, int, int]]:
    """Split adjacent red seals when raw ink has a clear blank gutter.

    Morphology is useful for collecting sparse seal strokes, but it can bridge
    two nearby stamps. This split uses the pre-morphology red mask so blank
    paper between stamps does not become part of one large fallback box.
    """
    deps = _vision_deps()
    if deps is None:
        return [box]
    _cv2, np = deps

    tight = _tighten_red_seal_box(raw_mask, box, page_width, page_height)
    x, y, bw, bh = tight
    if bw <= 0 or bh <= 0:
        return [tight]

    aspect = bw / max(1, bh)
    right_edge_seam = x + bw >= page_width * _GUTTER_RIGHT_EDGE_RATIO and aspect < _GUTTER_SEAM_ASPECT_MAX
    if right_edge_seam:
        return [tight]

    page_area = float(page_width * page_height)
    if bw * bh < page_area * _GUTTER_MIN_BOX_AREA_RATIO:
        return [tight]

    roi = raw_mask[y:y + bh, x:x + bw] > 0
    if roi.size == 0:
        return [tight]
    total_ink = int(roi.sum())
    if total_ink < _GUTTER_MIN_INK:
        return [tight]

    split = _find_blank_gutter(roi, page_width, page_height)
    if split is None:
        return [tight]

    axis, cut = split
    if axis == "x":
        pieces = [(x, y, cut, bh), (x + cut, y, bw - cut, bh)]
    else:
        pieces = [(x, y, bw, cut), (x, y + cut, bw, bh - cut)]

    out: list[tuple[int, int, int, int]] = []
    for piece in pieces:
        px, py, pbw, pbh = piece
        if pbw <= 0 or pbh <= 0:
            return [tight]
        refined = _tighten_red_seal_box(raw_mask, piece, page_width, page_height)
        _, _, rbw, rbh = refined
        if rbw * rbh < page_area * _GUTTER_PIECE_MIN_AREA_RATIO:
            return [tight]
        out.append(refined)
    return sorted(out, key=lambda b: (b[1], b[0]))


def _find_blank_gutter(raw_roi, page_width: int, page_height: int) -> tuple[str, int] | None:
    deps = _vision_deps()
    if deps is None:
        return None
    _cv2, np = deps

    min_page_side = min(page_width, page_height)
    min_gap = max(_GUTTER_MIN_GAP_FLOOR, int(round(min_page_side * _GUTTER_MIN_GAP_RATIO)))
    min_side = max(_GUTTER_MIN_SIDE_FLOOR, int(round(min_page_side * _GUTTER_MIN_SIDE_RATIO)))
    total_ink = int(raw_roi.sum())
    best: tuple[int, str, int] | None = None

    for axis, projection in (("x", raw_roi.sum(axis=0)), ("y", raw_roi.sum(axis=1))):
        active_indices = np.flatnonzero(projection > 0)
        if active_indices.size == 0:
            continue
        first = int(active_indices[0])
        last = int(active_indices[-1])
        if last - first + 1 < min_side * 2 + min_gap:
            continue

        inactive = projection == 0
        run_start: int | None = None
        for idx in range(first, last + 2):
            in_gap = idx <= last and bool(inactive[idx])
            if in_gap and run_start is None:
                run_start = idx
            elif not in_gap and run_start is not None:
                run_end = idx
                run_len = run_end - run_start
                left_size = run_start
                right_size = len(projection) - run_end
                if run_len >= min_gap and left_size >= min_side and right_size >= min_side:
                    if axis == "x":
                        left_ink = int(raw_roi[:, :run_start].sum())
                        right_ink = int(raw_roi[:, run_end:].sum())
                    else:
                        left_ink = int(raw_roi[:run_start, :].sum())
                        right_ink = int(raw_roi[run_end:, :].sum())
                    if min(left_ink, right_ink) >= total_ink * _GUTTER_MIN_INK_BALANCE_RATIO:
                        cut = (run_start + run_end) // 2
                        candidate = (run_len, axis, cut)
                        if best is None or candidate[0] > best[0]:
                            best = candidate
                run_start = None

    if best is None:
        return None
    return (best[1], best[2])


def _is_extreme_aspect_page(width: int, height: int) -> bool:
    """Return true for banner/screenshot-shaped images, not document pages.

    The local color fallback is intentionally limited to document-like pages.
    Extremely wide or tall UI screenshots often contain saturated red labels,
    badges, and navigation text that are visually unlike seals but form valid
    color components. Model-backed seal detections still run for those images.
    """
    short_side = max(1, min(width, height))
    return max(width, height) / short_side > _LOCAL_SEAL_MAX_PAGE_ASPECT


def _split_stacked_red_seal_box(
    raw_mask,
    box: tuple[int, int, int, int],
    page_width: int,
    page_height: int,
) -> list[tuple[int, int, int, int]]:
    """Split a large fallback red-seal box when it contains stacked seals.

    Adjacent official seals can touch after morphology and become one coarse
    candidate. Only split large, roughly round-ish vertical candidates; narrow
    right-edge seam stamps intentionally stay intact.
    """
    deps = _vision_deps()
    if deps is None:
        return [box]
    _cv2, np = deps

    x, y, bw, bh = box
    if bw <= 0 or bh <= 0:
        return [box]
    page_area = float(page_width * page_height)
    aspect = bw / max(1, bh)
    right_edge_seam = x + bw >= page_width * _GUTTER_RIGHT_EDGE_RATIO and aspect < _GUTTER_SEAM_ASPECT_MAX
    if (
        right_edge_seam
        or bw * bh < page_area * _STACK_MIN_BOX_AREA_RATIO
        or bh < min(page_width, page_height) * _STACK_MIN_HEIGHT_RATIO
        or not (_STACK_ASPECT_MIN <= aspect <= _STACK_ASPECT_MAX)
    ):
        return [box]

    roi = raw_mask[y:y + bh, x:x + bw] > 0
    if roi.size == 0:
        return [box]
    ys, xs = np.nonzero(roi)
    if ys.size < _STACK_MIN_INK_POINTS:
        return [box]

    c1 = float(np.percentile(ys, _STACK_SEED_LOW_PERCENTILE))
    c2 = float(np.percentile(ys, _STACK_SEED_HIGH_PERCENTILE))
    if abs(c2 - c1) < bh * _STACK_SEED_MIN_GAP_RATIO:
        return [box]
    for _ in range(_STACK_KMEANS_ITERATIONS):
        dist1 = np.abs(ys - c1)
        dist2 = np.abs(ys - c2)
        labels = dist2 < dist1
        if labels.all() or (~labels).all():
            return [box]
        c1 = float(ys[~labels].mean())
        c2 = float(ys[labels].mean())
    if c1 > c2:
        c1, c2 = c2, c1
        labels = ~labels

    separation = c2 - c1
    lower_count = int((~labels).sum())
    upper_count = int(labels.sum())
    total = max(1, ys.size)
    if (
        separation < bh * _STACK_MIN_SEPARATION_RATIO
        or min(lower_count, upper_count) < total * _STACK_MIN_CLUSTER_RATIO
    ):
        return [box]

    split_boxes: list[tuple[int, int, int, int]] = []
    pad = max(_REGION_PAD_FLOOR, int(round(min(page_width, page_height) * _STACK_PAD_RATIO)))
    for cluster_mask in (~labels, labels):
        cluster_xs = xs[cluster_mask]
        cluster_ys = ys[cluster_mask]
        if cluster_xs.size < _STACK_MIN_CLUSTER_POINTS:
            return [box]
        cx1 = max(0, x + int(cluster_xs.min()) - pad)
        cy1 = max(0, y + int(cluster_ys.min()) - pad)
        cx2 = min(page_width, x + int(cluster_xs.max()) + pad + 1)
        cy2 = min(page_height, y + int(cluster_ys.max()) + pad + 1)
        cbw = cx2 - cx1
        cbh = cy2 - cy1
        if cbw <= 0 or cbh <= 0 or cbw * cbh < page_area * _STACK_CLUSTER_MIN_AREA_RATIO:
            return [box]
        split_boxes.append((cx1, cy1, cbw, cbh))

    return sorted(split_boxes, key=lambda b: b[1])


def _merge_nearby_boxes(boxes: list[tuple[int, int, int, int]], w: int, h: int) -> list[tuple[int, int, int, int]]:
    merged: list[tuple[int, int, int, int]] = []
    gap = max(_MERGE_GAP_FLOOR, int(round(min(w, h) * _MERGE_GAP_RATIO)))
    for box in boxes:
        x, y, bw, bh = box
        current = (x, y, x + bw, y + bh)
        did_merge = True
        while did_merge:
            did_merge = False
            next_boxes: list[tuple[int, int, int, int]] = []
            for existing in merged:
                ex1, ey1, ex2, ey2 = existing
                if current[0] <= ex2 + gap and current[2] + gap >= ex1 and current[1] <= ey2 + gap and current[3] + gap >= ey1:
                    current = (
                        min(current[0], ex1),
                        min(current[1], ey1),
                        max(current[2], ex2),
                        max(current[3], ey2),
                    )
                    did_merge = True
                else:
                    next_boxes.append(existing)
            merged = next_boxes
        merged.append(current)

    out = [(x1, y1, x2 - x1, y2 - y1) for x1, y1, x2, y2 in merged]
    return sorted(out, key=lambda b: b[2] * b[3], reverse=True)


def _has_curved_seam_fragment(mask_roi, *, vertical: bool) -> bool:
    """Distinguish partial round stamp arcs from straight scan/page lines."""
    deps = _vision_deps()
    if deps is None:
        return False
    _cv2, np = deps

    active = mask_roi > 0
    if active.size == 0:
        return False

    h, w = active.shape[:2]
    positions: list[float] = []
    if vertical:
        denom = max(1, w - 1)
        for row in range(h):
            xs = np.flatnonzero(active[row, :])
            if xs.size:
                positions.append(float(xs.mean() / denom))
    else:
        denom = max(1, h - 1)
        for col in range(w):
            ys = np.flatnonzero(active[:, col])
            if ys.size:
                positions.append(float(ys.mean() / denom))

    if len(positions) < max(_SEAM_MIN_SAMPLE_FLOOR, int((h if vertical else w) * _SEAM_MIN_SAMPLE_RATIO)):
        return False
    span = max(positions) - min(positions)
    std = float(np.std(positions))
    return span >= _SEAM_SPAN_MIN or std >= _SEAM_STD_MIN
