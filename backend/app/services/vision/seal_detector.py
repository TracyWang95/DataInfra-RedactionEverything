"""Fallback visual detectors for official seals.\r\n\r\nPaddleOCR-VL and LocateAnything are the primary model paths. This module covers practical scanned-document seal cases that still benefit from lightweight image analysis when model confidence is low or unavailable.\r\n"""
from __future__ import annotations

import weakref
from dataclasses import dataclass

from PIL import Image, ImageOps

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


@dataclass(frozen=True)
class SealRegion:
    x: float
    y: float
    width: float
    height: float
    confidence: float = 0.72


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


def _cached_prepared_image(image: Image.Image, size: tuple[int, int]):
    for image_ref, cached_size, arr, red_exclusion_mask in reversed(_PREPARED_IMAGE_CACHE):
        if image_ref() is image and cached_size == size:
            return arr, red_exclusion_mask
    return None


def detect_red_seal_regions(image: Image.Image, *, max_regions: int = 8) -> list[SealRegion]:
    """Detect red stamp-like regions using color and connected components.

    The detector is intentionally generic: it looks for clusters of saturated
    red ink, including partial clusters at page edges. It does not read text or
    rely on document-specific keywords.
    """
    deps = _vision_deps()
    if deps is None:
        return []
    cv2, np = deps

    img = ImageOps.exif_transpose(image).convert("RGB")
    original_w, original_h = img.size
    if original_w <= 0 or original_h <= 0:
        return []
    if _is_extreme_aspect_page(original_w, original_h):
        return []

    max_side = max(original_w, original_h)
    scale = 1.0
    if max_side > _RED_WORK_MAX_SIDE:
        scale = _RED_WORK_MAX_SIDE / max_side
        img = img.resize((max(1, int(original_w * scale)), max(1, int(original_h * scale))))

    arr = np.array(img)
    h, w = arr.shape[:2]
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    red_hue = (hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 168)
    saturated = hsv[:, :, 1] >= 55
    bright = hsv[:, :, 2] >= 45
    rgb_red = (
        (arr[:, :, 0] >= 115)
        & (arr[:, :, 0] >= arr[:, :, 1] * 1.18)
        & (arr[:, :, 0] >= arr[:, :, 2] * 1.12)
    )
    mask = (red_hue & saturated & bright & rgb_red).astype("uint8") * 255
    red_exclusion_mask = (red_hue & (hsv[:, :, 1] >= 45) & bright).astype("uint8") * 255
    _remember_prepared_image(image, (w, h), arr, red_exclusion_mask)

    if int(mask.sum()) == 0:
        return []
    raw_mask = mask.copy()

    kernel_size = max(3, int(round(min(w, h) / 170)))
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask = cv2.dilate(mask, kernel, iterations=2)

    num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    page_area = float(w * h)
    min_red_area = max(16, int(page_area * 0.000025))
    max_box_area = page_area * 0.12
    candidates: list[tuple[float, tuple[int, int, int, int]]] = []

    for label in range(1, num_labels):
        x, y, bw, bh, area = [int(v) for v in stats[label]]
        if area < min_red_area or bw <= 0 or bh <= 0:
            continue
        box_area = bw * bh
        if box_area > max_box_area:
            continue
        density = area / max(1, box_area)
        aspect = bw / max(1, bh)
        near_edge = x <= w * 0.04 or y <= h * 0.04 or x + bw >= w * 0.96 or y + bh >= h * 0.96
        large_enough = max(bw, bh) >= min(w, h) * 0.035 and min(bw, bh) >= max(5, min(w, h) * 0.006)
        stamp_like_density = 0.018 <= density <= 0.88
        stamp_like_aspect = 0.10 <= aspect <= 10.0
        seam_like_aspect = near_edge and (0.035 <= aspect < 0.10 or 10.0 < aspect <= 28.0)
        seam_large_enough = max(bw, bh) >= min(w, h) * 0.07 and min(bw, bh) >= max(4, min(w, h) * 0.004)
        if seam_like_aspect and not _has_curved_seam_fragment(mask[y:y + bh, x:x + bw], vertical=aspect < 1.0):
            continue
        if not (
            stamp_like_density
            and (stamp_like_aspect or (seam_like_aspect and seam_large_enough))
            and (large_enough or near_edge)
        ):
            continue
        score = density + min(area / page_area * 120, 0.6) + (0.28 if seam_like_aspect else 0.2 if near_edge else 0.0)
        candidates.append((score, (x, y, bw, bh)))

    merged = _merge_nearby_boxes([box for _score, box in sorted(candidates, reverse=True)], w, h)
    refined: list[tuple[int, int, int, int]] = []
    for box in merged:
        for tight_box in _split_red_seal_box_by_gutter(raw_mask, box, w, h):
            for split_box in _split_stacked_red_seal_box(raw_mask, tight_box, w, h):
                refined.append(_tighten_red_seal_box(raw_mask, split_box, w, h))
    merged = sorted(refined, key=lambda b: b[2] * b[3], reverse=True)
    regions: list[SealRegion] = []
    for x, y, bw, bh in merged[:max_regions]:
        pad = max(2, int(round(min(w, h) * 0.004)))
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(w, x + bw + pad)
        y2 = min(h, y + bh + pad)
        regions.append(SealRegion(
            x=x1 / w,
            y=y1 / h,
            width=max(1, x2 - x1) / w,
            height=max(1, y2 - y1) / h,
        ))
    return regions


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

    pad = max(1, int(round(min(page_width, page_height) * 0.0025)))
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
    right_edge_seam = x + bw >= page_width * 0.94 and aspect < 0.38
    if right_edge_seam:
        return [tight]

    page_area = float(page_width * page_height)
    if bw * bh < page_area * 0.012:
        return [tight]

    roi = raw_mask[y:y + bh, x:x + bw] > 0
    if roi.size == 0:
        return [tight]
    total_ink = int(roi.sum())
    if total_ink < 80:
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
        if rbw * rbh < page_area * 0.004:
            return [tight]
        out.append(refined)
    return sorted(out, key=lambda b: (b[1], b[0]))


def _find_blank_gutter(raw_roi, page_width: int, page_height: int) -> tuple[str, int] | None:
    deps = _vision_deps()
    if deps is None:
        return None
    _cv2, np = deps

    min_page_side = min(page_width, page_height)
    min_gap = max(5, int(round(min_page_side * 0.006)))
    min_side = max(24, int(round(min_page_side * 0.055)))
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
                    if min(left_ink, right_ink) >= total_ink * 0.22:
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
    right_edge_seam = x + bw >= page_width * 0.94 and aspect < 0.38
    if (
        right_edge_seam
        or bw * bh < page_area * 0.025
        or bh < min(page_width, page_height) * 0.22
        or not (0.35 <= aspect <= 1.35)
    ):
        return [box]

    roi = raw_mask[y:y + bh, x:x + bw] > 0
    if roi.size == 0:
        return [box]
    ys, xs = np.nonzero(roi)
    if ys.size < 80:
        return [box]

    c1 = float(np.percentile(ys, 30))
    c2 = float(np.percentile(ys, 70))
    if abs(c2 - c1) < bh * 0.18:
        return [box]
    for _ in range(12):
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
        separation < bh * 0.30
        or min(lower_count, upper_count) < total * 0.22
    ):
        return [box]

    split_boxes: list[tuple[int, int, int, int]] = []
    pad = max(2, int(round(min(page_width, page_height) * 0.003)))
    for cluster_mask in (~labels, labels):
        cluster_xs = xs[cluster_mask]
        cluster_ys = ys[cluster_mask]
        if cluster_xs.size < 30:
            return [box]
        cx1 = max(0, x + int(cluster_xs.min()) - pad)
        cy1 = max(0, y + int(cluster_ys.min()) - pad)
        cx2 = min(page_width, x + int(cluster_xs.max()) + pad + 1)
        cy2 = min(page_height, y + int(cluster_ys.max()) + pad + 1)
        cbw = cx2 - cx1
        cbh = cy2 - cy1
        if cbw <= 0 or cbh <= 0 or cbw * cbh < page_area * 0.004:
            return [box]
        split_boxes.append((cx1, cy1, cbw, cbh))

    return sorted(split_boxes, key=lambda b: b[1])


def detect_dark_seal_regions(image: Image.Image, *, max_regions: int = 6) -> list[SealRegion]:
    """Detect black/gray copied stamp-like regions.

    This covers photocopied or grayscale documents where the seal ring is dark
    instead of red. The filters intentionally prefer round-ish, medium-density
    ink clusters so paragraphs, long dark strokes, and scan shadows are ignored.
    """
    deps = _vision_deps()
    if deps is None:
        return []
    cv2, np = deps

    img = ImageOps.exif_transpose(image).convert("RGB")
    original_w, original_h = img.size
    if original_w <= 0 or original_h <= 0:
        return []

    max_side = max(original_w, original_h)
    scale = 1.0
    if max_side > _DARK_WORK_MAX_SIDE:
        scale = _DARK_WORK_MAX_SIDE / max_side
        img = img.resize((max(1, int(original_w * scale)), max(1, int(original_h * scale))))

    cached = _cached_prepared_image(image, img.size)
    if cached is None:
        arr = np.array(img)
        red_exclusion_mask = None
    else:
        arr, red_exclusion_mask = cached
    h, w = arr.shape[:2]
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    dark = gray < 118
    # Exclude saturated red ink; red seals are handled by the color detector.
    if red_exclusion_mask is None:
        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
        red_hue = (hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 168)
        red_ink = red_hue & (hsv[:, :, 1] >= 45) & (hsv[:, :, 2] >= 45)
    else:
        red_ink = red_exclusion_mask > 0
    mask = (dark & ~red_ink).astype("uint8") * 255

    if int(mask.sum()) == 0:
        return []
    raw_mask = mask.copy()

    close_size = max(5, int(round(min(w, h) / 95)))
    if close_size % 2 == 0:
        close_size += 1
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel, iterations=1)

    dilate_size = max(3, int(round(min(w, h) / 145)))
    if dilate_size % 2 == 0:
        dilate_size += 1
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_size, dilate_size))
    mask = cv2.dilate(mask, dilate_kernel, iterations=1)

    num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    page_area = float(w * h)
    min_area = max(60, int(page_area * 0.00045))
    max_box_area = page_area * 0.09
    candidates: list[tuple[float, tuple[int, int, int, int]]] = []

    for label in range(1, num_labels):
        x, y, bw, bh, area = [int(v) for v in stats[label]]
        if area < min_area or bw <= 0 or bh <= 0:
            continue
        box_area = bw * bh
        if box_area > max_box_area:
            continue
        density = area / max(1, box_area)
        aspect = bw / max(1, bh)
        near_edge = x <= w * 0.04 or y <= h * 0.04 or x + bw >= w * 0.96 or y + bh >= h * 0.96
        if not near_edge and box_area > page_area * 0.045:
            refined_box = _refine_large_dark_seal_box_by_circle(gray, (x, y, bw, bh), w, h)
            if refined_box is None:
                continue
            x, y, bw, bh = refined_box
            box_area = bw * bh
            area = int((raw_mask[y:y + bh, x:x + bw] > 0).sum())
            if area < min_area:
                continue
            density = area / max(1, box_area)
            aspect = bw / max(1, bh)
        large_enough = max(bw, bh) >= min(w, h) * 0.085 and min(bw, bh) >= min(w, h) * 0.045
        seam_like_aspect = near_edge and 0.06 <= aspect < 0.25
        seam_large_enough = max(bw, bh) >= min(w, h) * 0.09 and min(bw, bh) >= max(5, min(w, h) * 0.006)
        if seam_like_aspect and not _has_curved_seam_fragment(mask[y:y + bh, x:x + bw], vertical=aspect < 1.0):
            continue
        roundish = 0.42 <= aspect <= 1.9 or (near_edge and 0.25 <= aspect <= 3.2) or (seam_like_aspect and seam_large_enough)
        stamp_density = 0.025 <= density <= (0.86 if seam_like_aspect else 0.52)
        if not ((large_enough or (seam_like_aspect and seam_large_enough)) and roundish and stamp_density):
            continue

        roi = gray[y:y + bh, x:x + bw]
        if roi.size == 0:
            continue
        border = max(1, min(bw, bh) // 8)
        border_pixels = np.concatenate([
            roi[:border, :].ravel(),
            roi[-border:, :].ravel(),
            roi[:, :border].ravel(),
            roi[:, -border:].ravel(),
        ])
        center = roi[border:-border, border:-border] if bh > border * 2 and bw > border * 2 else roi
        border_dark = float((border_pixels < 135).mean()) if border_pixels.size else 0.0
        center_dark = float((center < 135).mean()) if center.size else 0.0
        if border_dark < 0.015 and center_dark < 0.015:
            continue
        if not near_edge and border_dark < center_dark * 0.5:
            continue
        score = density + border_dark * 0.7 + min(area / page_area * 80, 0.45) + (0.26 if seam_like_aspect else 0.18 if near_edge else 0.0)
        candidates.append((score, (x, y, bw, bh)))

    merged = _merge_nearby_boxes([box for _score, box in sorted(candidates, reverse=True)], w, h)
    regions: list[SealRegion] = []
    for x, y, bw, bh in merged[:max_regions]:
        pad = max(2, int(round(min(w, h) * 0.006)))
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(w, x + bw + pad)
        y2 = min(h, y + bh + pad)
        regions.append(SealRegion(
            x=x1 / w,
            y=y1 / h,
            width=max(1, x2 - x1) / w,
            height=max(1, y2 - y1) / h,
            confidence=0.66,
        ))
    return regions


def _refine_large_dark_seal_box_by_circle(
    gray,
    box: tuple[int, int, int, int],
    page_width: int,
    page_height: int,
) -> tuple[int, int, int, int] | None:
    """Tighten a coarse dark copied-seal candidate to a circular stamp.

    Dark fallback masks can merge a copied seal with nearby account numbers or
    labels. For large non-edge boxes, keep the fallback only when a plausible
    circular seal outline can be isolated inside the coarse component.
    """
    deps = _vision_deps()
    if deps is None:
        return None
    cv2, np = deps

    x, y, bw, bh = box
    if bw <= 0 or bh <= 0:
        return None

    roi = gray[y:y + bh, x:x + bw]
    if roi.size == 0:
        return None

    min_page_side = min(page_width, page_height)
    min_radius = max(18, int(round(min_page_side * 0.045)))
    max_radius = max(min_radius + 1, int(round(min(bw, bh) * 0.55)))
    blurred = cv2.medianBlur(roi, 5)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(28, min(bw, bh) // 4),
        param1=100,
        param2=24,
        minRadius=min_radius,
        maxRadius=max_radius,
    )
    if circles is None:
        return None

    page_area = float(page_width * page_height)
    candidates: list[tuple[float, tuple[int, int, int, int]]] = []
    for cx, cy, radius in np.round(circles[0]).astype(int):
        if radius < min_radius:
            continue
        pad = max(3, int(round(radius * 0.10)))
        nx1 = max(0, x + cx - radius - pad)
        ny1 = max(0, y + cy - radius - pad)
        nx2 = min(page_width, x + cx + radius + pad)
        ny2 = min(page_height, y + cy + radius + pad)
        nbw = nx2 - nx1
        nbh = ny2 - ny1
        if nbw <= 0 or nbh <= 0:
            continue
        refined_area = nbw * nbh
        if refined_area <= 0 or refined_area > page_area * 0.05:
            continue
        aspect = nbw / max(1, nbh)
        if not 0.55 <= aspect <= 1.65:
            continue
        circle_roi = gray[ny1:ny2, nx1:nx2]
        if circle_roi.size == 0:
            continue
        dark_ratio = float((circle_roi < 135).mean())
        if dark_ratio < 0.025:
            continue
        if _has_dominant_dark_rule_line(circle_roi):
            continue
        score = dark_ratio + min(radius / max(1, min_page_side), 0.20)
        candidates.append((score, (int(nx1), int(ny1), int(nbw), int(nbh))))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _has_dominant_dark_rule_line(gray_roi) -> bool:
    """Detect table/form rules that dominate a copied-seal circle candidate."""
    deps = _vision_deps()
    if deps is None:
        return False
    _cv2, np = deps

    if gray_roi.size == 0:
        return False
    dark = gray_roi < 135
    if not bool(dark.any()):
        return False

    height, width = dark.shape[:2]
    if width <= 0 or height <= 0:
        return False
    row_coverage = float(dark.sum(axis=1).max()) / max(1, width)
    col_coverage = float(dark.sum(axis=0).max()) / max(1, height)
    return row_coverage >= 0.82 or col_coverage >= 0.82


def _merge_nearby_boxes(boxes: list[tuple[int, int, int, int]], w: int, h: int) -> list[tuple[int, int, int, int]]:
    merged: list[tuple[int, int, int, int]] = []
    gap = max(8, int(round(min(w, h) * 0.018)))
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

    if len(positions) < max(8, int((h if vertical else w) * 0.18)):
        return False
    span = max(positions) - min(positions)
    std = float(np.std(positions))
    return span >= 0.18 or std >= 0.055
