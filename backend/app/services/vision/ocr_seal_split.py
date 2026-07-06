"""Seal/stamp post-processing: split a model-returned box around stacked red seals.

Split out of ocr_pipeline.py (which stays the public facade).
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from app.services.ocr_has_vision_service import SensitiveRegion
from app.services.vision.ocr_tuning import (
    _RED_STAMP_MIN_RED,
    _RED_STAMP_OTHER_CHANNEL_FLOOR,
    _RED_STAMP_OTHER_CHANNEL_RATIO,
    _RED_STAMP_RED_MINUS_BLUE,
    _RED_STAMP_RED_MINUS_GREEN,
    _SEAL_ACTIVE_THRESHOLD_MIN,
    _SEAL_ACTIVE_THRESHOLD_WIDTH_RATIO,
    _SEAL_BAND_BOX_MIN_PX,
    _SEAL_BAND_BOX_MIN_WIDTH_RATIO,
    _SEAL_BAND_PAD_MIN,
    _SEAL_BAND_PAD_RATIO,
    _SEAL_CLOSE_GAP_HEIGHT_DIVISOR,
    _SEAL_CLOSE_GAP_MAX,
    _SEAL_CLOSE_GAP_MIN,
    _SEAL_HALF_BAND_MIN,
    _SEAL_HALF_BAND_WIDTH_RATIO,
    _SEAL_MAX_PEAKS,
    _SEAL_MIN_BAND_HEIGHT_MAX,
    _SEAL_MIN_BAND_HEIGHT_MIN,
    _SEAL_MIN_BAND_HEIGHT_WIDTH_RATIO,
    _SEAL_PEAK_MIN_DISTANCE_MIN,
    _SEAL_PEAK_MIN_DISTANCE_WIDTH_RATIO,
    _SEAL_PEAK_PROMINENCE_RATIO,
    _SEAL_SMOOTH_RADIUS_HEIGHT_DIVISOR,
    _SEAL_SMOOTH_RADIUS_MAX,
    _SEAL_SMOOTH_RADIUS_MIN,
    _SEAL_SPLIT_MIN_ASPECT,
    _SEAL_SPLIT_MIN_DIM_PX,
    _SEAL_SPLIT_MIN_WIDTH_IMG_RATIO,
    _SEAL_SPLIT_MIN_WIDTH_PX,
)


def _split_merged_seal_region(image: Image.Image, region: SensitiveRegion) -> list[SensitiveRegion]:
    """Split a model-returned seal box when it visibly contains stacked seals.

    PaddleOCR-VL sometimes returns one tall region around two adjacent red
    stamps. Redacting the combined box works, but it hides too much nearby text
    and makes manual review awkward. This post-process is intentionally generic:
    it only runs for unusually tall seal boxes and separates them by red-pixel
    row projections inside the box.
    """
    if region.entity_type != "SEAL":
        return [region]
    if region.width < _SEAL_SPLIT_MIN_DIM_PX or region.height < _SEAL_SPLIT_MIN_DIM_PX:
        return [region]
    if region.height < region.width * _SEAL_SPLIT_MIN_ASPECT:
        return [region]

    img_w, img_h = image.size
    if region.width < max(_SEAL_SPLIT_MIN_WIDTH_PX, int(img_w * _SEAL_SPLIT_MIN_WIDTH_IMG_RATIO)):
        return [region]
    x1 = max(0, min(region.left, img_w - 1))
    y1 = max(0, min(region.top, img_h - 1))
    x2 = max(x1 + 1, min(region.left + region.width, img_w))
    y2 = max(y1 + 1, min(region.top + region.height, img_h))
    crop = image.crop((x1, y1, x2, y2)).convert("RGB")
    width, height = crop.size
    arr = np.asarray(crop, dtype=np.int32)
    red = arr[:, :, 0]
    green = arr[:, :, 1]
    blue = arr[:, :, 2]
    channel_cap = np.maximum(
        _RED_STAMP_OTHER_CHANNEL_FLOOR,
        (red * _RED_STAMP_OTHER_CHANNEL_RATIO).astype(np.int32),
    )
    red_mask = (
        (red >= _RED_STAMP_MIN_RED)
        & (red - green >= _RED_STAMP_RED_MINUS_GREEN)
        & (red - blue >= _RED_STAMP_RED_MINUS_BLUE)
        & (green <= channel_cap)
        & (blue <= channel_cap)
    )
    red_rows: list[int] = [int(v) for v in red_mask.sum(axis=1)]

    # Smooth the projection so sparse red text and broken rings are treated as
    # one seal band while preserving larger vertical gaps between stamps.
    radius = max(_SEAL_SMOOTH_RADIUS_MIN, min(_SEAL_SMOOTH_RADIUS_MAX, height // _SEAL_SMOOTH_RADIUS_HEIGHT_DIVISOR))
    smoothed = [
        sum(red_rows[max(0, y - radius): min(height, y + radius + 1)])
        for y in range(height)
    ]
    active_threshold = max(_SEAL_ACTIVE_THRESHOLD_MIN, int(width * _SEAL_ACTIVE_THRESHOLD_WIDTH_RATIO))
    close_gap = max(_SEAL_CLOSE_GAP_MIN, min(_SEAL_CLOSE_GAP_MAX, height // _SEAL_CLOSE_GAP_HEIGHT_DIVISOR))
    min_band_height = max(_SEAL_MIN_BAND_HEIGHT_MIN, min(_SEAL_MIN_BAND_HEIGHT_MAX, int(region.width * _SEAL_MIN_BAND_HEIGHT_WIDTH_RATIO)))

    bands: list[tuple[int, int]] = []
    in_band = False
    start = 0
    gap = 0
    for y, count in enumerate(smoothed):
        if count >= active_threshold:
            if not in_band:
                start = y
                in_band = True
            gap = 0
        elif in_band:
            gap += 1
            if gap >= close_gap:
                end = y - gap + 1
                if end - start >= min_band_height:
                    bands.append((start, end))
                in_band = False
                gap = 0
    if in_band and height - start >= min_band_height:
        bands.append((start, height - 1))

    if len(bands) < 2:
        max_projection = max(smoothed) if smoothed else 0
        peak_candidates: list[tuple[float, int]] = []
        if max_projection > 0:
            for y in range(1, height - 1):
                if (
                    smoothed[y] >= smoothed[y - 1]
                    and smoothed[y] >= smoothed[y + 1]
                    and smoothed[y] >= max_projection * _SEAL_PEAK_PROMINENCE_RATIO
                ):
                    peak_candidates.append((float(smoothed[y]), y))
        peaks: list[int] = []
        min_peak_distance = max(_SEAL_PEAK_MIN_DISTANCE_MIN, int(width * _SEAL_PEAK_MIN_DISTANCE_WIDTH_RATIO))
        for _score, y in sorted(peak_candidates, reverse=True):
            if all(abs(y - existing) >= min_peak_distance for existing in peaks):
                peaks.append(y)
            if len(peaks) >= _SEAL_MAX_PEAKS:
                break
        peaks.sort()
        if len(peaks) >= 2:
            half_band = max(_SEAL_HALF_BAND_MIN, int(width * _SEAL_HALF_BAND_WIDTH_RATIO))
            bands = [
                (max(0, peak - half_band), min(height - 1, peak + half_band))
                for peak in peaks
            ]

    if len(bands) < 2:
        return [region]

    split_regions: list[SensitiveRegion] = []
    for band_start, band_end in bands:
        y_start = max(0, band_start - radius)
        y_end = min(height - 1, band_end + radius)
        band_ys, band_xs = np.nonzero(red_mask[y_start : y_end + 1, :])
        if band_xs.size == 0:
            continue
        bx1, bx2 = int(band_xs.min()), int(band_xs.max())
        by1, by2 = int(band_ys.min()) + y_start, int(band_ys.max()) + y_start
        box_w = bx2 - bx1 + 1
        box_h = by2 - by1 + 1
        if box_w < max(_SEAL_BAND_BOX_MIN_PX, region.width * _SEAL_BAND_BOX_MIN_WIDTH_RATIO) or box_h < max(_SEAL_BAND_BOX_MIN_PX, region.width * _SEAL_BAND_BOX_MIN_WIDTH_RATIO):
            continue
        pad = max(_SEAL_BAND_PAD_MIN, int(max(box_w, box_h) * _SEAL_BAND_PAD_RATIO))
        left = max(0, x1 + bx1 - pad)
        top = max(0, y1 + by1 - pad)
        right = min(img_w, x1 + bx2 + pad + 1)
        bottom = min(img_h, y1 + by2 + pad + 1)
        split_regions.append(SensitiveRegion(
            text=region.text,
            entity_type=region.entity_type,
            left=left,
            top=top,
            width=max(1, right - left),
            height=max(1, bottom - top),
            confidence=region.confidence,
            source=region.source,
            color=region.color,
        ))

    return split_regions if len(split_regions) >= 2 else [region]
