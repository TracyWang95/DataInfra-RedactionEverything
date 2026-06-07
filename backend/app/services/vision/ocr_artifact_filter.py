# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Shared filters for OCR boxes that are scanner or page-edge artifacts."""

from __future__ import annotations

from PIL import Image

# Left-edge artifact: max normalized x-offset and min normalized width.
_LEFT_EDGE_MAX_X = 0.015
_LEFT_EDGE_MIN_WIDTH = 0.08
# Top-left corner artifact thresholds (normalized).
_TOP_LEFT_MAX_X = 0.04
_TOP_LEFT_MAX_Y = 0.02
_TOP_LEFT_MIN_WIDTH = 0.10
_TOP_LEFT_MIN_HEIGHT = 0.06
# Top-edge strip artifact thresholds (normalized).
_TOP_EDGE_MAX_Y = 0.012
_TOP_EDGE_MIN_WIDTH = 0.12
_TOP_EDGE_MAX_HEIGHT = 0.05
# Right-edge vertical sliver thresholds (normalized).
_RIGHT_EDGE_MIN_RIGHT = 0.965
_RIGHT_EDGE_MIN_X = 0.93
_RIGHT_EDGE_MIN_HEIGHT = 0.06
_RIGHT_EDGE_MAX_WIDTH = 0.06
# Bottom-edge strip artifact thresholds (normalized).
_BOTTOM_EDGE_MIN_BOTTOM = 0.975
_BOTTOM_EDGE_MIN_WIDTH = 0.10
_BOTTOM_EDGE_MAX_HEIGHT = 0.035

# Ink detection: per-pixel luminance/red-channel thresholds.
_INK_DARK_MAX = 185
_INK_RED_MIN = 120
_INK_RED_OVER_GREEN = 1.18
_INK_RED_OVER_BLUE = 1.12
# Region-area ratio below which a looser ink-density floor applies.
_SMALL_REGION_AREA_RATIO = 0.006
_SMALL_REGION_MIN_DENSITY = 0.004
_DEFAULT_MIN_DENSITY = 0.008

VISUAL_OCR_TYPES = {
    "BARCODE",
    "FACE",
    "FINGERPRINT",
    "HANDWRITING",
    "HANDWRITTEN_SIGNATURE",
    "OFFICIAL_SEAL",
    "PHOTO",
    "PORTRAIT",
    "QR_CODE",
    "QRCODE",
    "SEAL",
    "SIGNATURE",
    "STAMP",
    "WATERMARK",
}


def is_visual_ocr_type(entity_type: str | None) -> bool:
    return str(entity_type or "").strip().upper() in VISUAL_OCR_TYPES


def is_page_edge_ocr_artifact(
    left: int,
    top: int,
    region_width: int,
    region_height: int,
    page_width: int,
    page_height: int,
    entity_type: str | None = None,
) -> bool:
    if page_width <= 0 or page_height <= 0 or is_visual_ocr_type(entity_type):
        return False

    x = left / page_width
    y = top / page_height
    width = region_width / page_width
    height = region_height / page_height

    if x <= _LEFT_EDGE_MAX_X and width >= _LEFT_EDGE_MIN_WIDTH:
        return True
    if x <= _TOP_LEFT_MAX_X and y <= _TOP_LEFT_MAX_Y and width >= _TOP_LEFT_MIN_WIDTH and height >= _TOP_LEFT_MIN_HEIGHT:
        return True
    if y <= _TOP_EDGE_MAX_Y and width >= _TOP_EDGE_MIN_WIDTH and height <= _TOP_EDGE_MAX_HEIGHT:
        return True
    if (x + width >= _RIGHT_EDGE_MIN_RIGHT or x >= _RIGHT_EDGE_MIN_X) and height >= _RIGHT_EDGE_MIN_HEIGHT and width <= _RIGHT_EDGE_MAX_WIDTH:
        return True
    return y + height >= _BOTTOM_EDGE_MIN_BOTTOM and width >= _BOTTOM_EDGE_MIN_WIDTH and height <= _BOTTOM_EDGE_MAX_HEIGHT


def region_has_visible_ink(
    image: Image.Image,
    left: int,
    top: int,
    region_width: int,
    region_height: int,
) -> bool:
    width, height = image.size
    x1 = max(0, min(width, int(left)))
    y1 = max(0, min(height, int(top)))
    x2 = max(x1 + 1, min(width, int(left + region_width)))
    y2 = max(y1 + 1, min(height, int(top + region_height)))
    crop = image.crop((x1, y1, x2, y2)).convert("RGB")
    raw = crop.tobytes()
    area = max(1, crop.width * crop.height)
    ink = 0
    for idx in range(0, len(raw), 3):
        r, g, b = raw[idx], raw[idx + 1], raw[idx + 2]
        if min(r, g, b) < _INK_DARK_MAX or (r > _INK_RED_MIN and r > g * _INK_RED_OVER_GREEN and r > b * _INK_RED_OVER_BLUE):
            ink += 1
    density = ink / area
    page_area = max(1, width * height)
    region_area_ratio = area / page_area
    min_density = _SMALL_REGION_MIN_DENSITY if region_area_ratio < _SMALL_REGION_AREA_RATIO else _DEFAULT_MIN_DENSITY
    return density >= min_density
