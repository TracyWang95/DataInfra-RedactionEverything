"""Shared filters for OCR boxes that are scanner or page-edge artifacts."""

from __future__ import annotations

import numpy as np
from PIL import Image

from app.core.visual_feature_categories import (
    VISUAL_FEATURE_SLUGS,
    VISUAL_ONLY_ENTITY_TYPES,
)

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

# Visual-region exemption for the page-edge/ink artifact filters, derived from
# the canonical visual registries instead of a hand-maintained parallel word
# list: the visual-only entity type ids plus the fixed visual category slugs
# uppercased. Regions of these types carry no OCR text evidence, so the
# edge/ink heuristics must never drop them.
VISUAL_OCR_TYPES = frozenset(VISUAL_ONLY_ENTITY_TYPES) | frozenset(
    slug.upper() for slug in VISUAL_FEATURE_SLUGS
)


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
    arr = np.asarray(crop)
    area = max(1, crop.width * crop.height)
    red = arr[:, :, 0]
    green = arr[:, :, 1]
    blue = arr[:, :, 2]
    dark = arr.min(axis=2) < _INK_DARK_MAX
    red_mark = (
        (red > _INK_RED_MIN)
        & (red > green * _INK_RED_OVER_GREEN)
        & (red > blue * _INK_RED_OVER_BLUE)
    )
    ink = int(np.count_nonzero(dark | red_mark))
    density = ink / area
    page_area = max(1, width * height)
    region_area_ratio = area / page_area
    min_density = _SMALL_REGION_MIN_DENSITY if region_area_ratio < _SMALL_REGION_AREA_RATIO else _DEFAULT_MIN_DENSITY
    return density >= min_density
