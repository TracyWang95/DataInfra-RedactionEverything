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

# Otsu separability (between-class variance / total histogram variance, in
# [0, 1]) that a region's own grayscale histogram must reach before an Otsu
# "blank" verdict is trusted enough to DROP the region. It is a dimensionless,
# self-calibrated statistic — not a pixel threshold. A near-uniform crop
# (weak/absent bimodality) fails this and is KEPT, because a low-contrast
# light-ink signature can sit in a weak second mode that Otsu would otherwise
# fold into the paper background — dropping it there would be a leak. 0.5 = the
# split must explain at least half of the histogram's spread.
_OTSU_STRONG_SEPARABILITY = 0.5

# Minimum count of decoded content characters (CJK / alphanumeric) that marks a
# region as recognized text rather than a blank scanner strip. A scan-edge line
# or page border decodes to nothing coherent (0-1 stray chars); real PII — a
# signing date, even a 2-character Chinese name — has at least two. Threshold 2
# protects short names while still catching textless noise. ``str.isalnum()`` is
# True for CJK ideographs and digits, False for brackets/underscores/punctuation.
_MIN_CONTENT_CHARS = 2


def _has_substantial_text(text: str | None) -> bool:
    if not text:
        return False
    return sum(1 for ch in text if ch.isalnum()) >= _MIN_CONTENT_CHARS

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


def text_evidence_hull(
    regions: list,
) -> tuple[tuple[float, float, float, float] | None, float | None]:
    """Body-text hull + line-em self-calibrated from the OCR regions that
    actually decoded substantial text.

    The hull is the bounding box of every region whose OCR text is real content
    (>= 2 alnum chars) and whose type is not a text-less visual feature. It is
    the document's own measurement of where the body lives — no fixed pixel
    margin. ``em`` is the median text-region height (≈ one CJK line em), the
    document's own scale for "clearly separated from the body".

    Returns ``(None, None)`` when there is no text evidence to bound the page,
    so callers fall back to keeping (or to the legacy geometry) rather than
    inventing a hull.
    """
    texts = [
        r
        for r in regions
        if _has_substantial_text(getattr(r, "text", None))
        and not is_visual_ocr_type(getattr(r, "entity_type", None))
    ]
    if not texts:
        return None, None
    x1 = min(r.left for r in texts)
    y1 = min(r.top for r in texts)
    x2 = max(r.left + r.width for r in texts)
    y2 = max(r.top + r.height for r in texts)
    heights = sorted(max(1.0, float(r.height)) for r in texts)
    em = heights[len(heights) // 2]
    return (x1, y1, x2, y2), em


def _region_clear_of_text_hull(
    left: float,
    top: float,
    region_width: float,
    region_height: float,
    text_hull: tuple[float, float, float, float],
    page_em: float | None,
) -> bool:
    """True when the region lies wholly beyond one edge of the OCR body-text
    hull by at least one line-em. Pure coordinate ordering + a self-calibrated
    em margin — no fixed pixel epsilon. A region that touches or overlaps the
    body (within an em) is content-adjacent and never reported as an artifact.
    """
    hx1, hy1, hx2, hy2 = text_hull
    margin = float(page_em) if page_em and page_em > 0 else 0.0
    r_x1, r_y1 = left, top
    r_x2, r_y2 = left + region_width, top + region_height
    return (
        r_x2 <= hx1 - margin
        or r_x1 >= hx2 + margin
        or r_y2 <= hy1 - margin
        or r_y1 >= hy2 + margin
    )


def is_page_edge_ocr_artifact(
    left: int,
    top: int,
    region_width: int,
    region_height: int,
    page_width: int,
    page_height: int,
    entity_type: str | None = None,
    text: str | None = None,
    text_hull: tuple[float, float, float, float] | None = None,
    page_em: float | None = None,
) -> bool:
    if page_width <= 0 or page_height <= 0 or is_visual_ocr_type(entity_type):
        return False
    # A region OCR decoded into coherent text is recognized content (e.g. a
    # signing date sitting on the document's last line), not a blank scanner
    # edge strip. The edge heuristics below only target textless scan
    # lines/borders, so never let them drop real decoded PII.
    if _has_substantial_text(text):
        return False

    # Self-calibrated path: when the page's OCR text hull is known, an artifact
    # is a textless, non-visual region that lies wholly OUTSIDE the measured
    # body text (by one line-em). This replaces the fixed normalized edge
    # offsets (0.015 / 0.012 …), which are resolution-dependent: two DPIs of the
    # same page reach the same hull-relative verdict where a fixed offset flips.
    if text_hull is not None:
        return _region_clear_of_text_hull(
            left, top, region_width, region_height, text_hull, page_em
        )

    # Legacy geometric fallback — only when there is no text evidence to bound
    # the body (e.g. a page that decoded no content at all).
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


def _otsu_threshold_separability(gray: np.ndarray) -> tuple[int, float] | None:
    """Otsu threshold and its separability η = σ²_between / σ²_total (in [0, 1])
    for a grayscale array. Returns ``None`` for an empty or perfectly uniform
    crop (no bimodality to measure)."""
    hist = np.bincount(gray.reshape(-1), minlength=256).astype(np.float64)
    total = hist.sum()
    if total <= 0:
        return None
    levels = np.arange(256, dtype=np.float64)
    p = hist / total
    omega = np.cumsum(p)
    mu = np.cumsum(p * levels)
    mu_t = mu[-1]
    sigma_total = float(np.sum(p * (levels - mu_t) ** 2))
    if sigma_total <= 0.0:
        return None
    denom = omega * (1.0 - omega)
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b = np.where(denom > 0, (mu_t * omega - mu) ** 2 / denom, 0.0)
    t = int(np.argmax(sigma_b))
    eta = float(sigma_b[t] / sigma_total)
    return t, eta


def ink_foreground_mask(rgb: np.ndarray) -> np.ndarray:
    """Boolean ink (foreground) mask over an HxWx3 uint8 RGB array.

    A pixel is ink when it is dark (min channel below the luminance cut) OR a
    saturated red-ink mark (red dominant over green/blue). This is the SINGLE
    foreground identity shared by the ink-density gate below and the vertical
    ink-hull measurement in the vision service — there is no second threshold
    set, so both agree on what "ink" is.
    """
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]
    gray = rgb.min(axis=2)
    dark = gray < _INK_DARK_MAX
    red_mark = (
        (red > _INK_RED_MIN)
        & (red > green * _INK_RED_OVER_GREEN)
        & (red > blue * _INK_RED_OVER_BLUE)
    )
    return dark | red_mark


def region_has_visible_ink(
    image: Image.Image,
    left: int,
    top: int,
    region_width: int,
    region_height: int,
    entity_type: str | None = None,
) -> bool:
    # Visual features carry no OCR text and are proven by the visual channel, not
    # by ink density — never let the ink gate drop them.
    if is_visual_ocr_type(entity_type):
        return True
    width, height = image.size
    x1 = max(0, min(width, int(left)))
    y1 = max(0, min(height, int(top)))
    x2 = max(x1 + 1, min(width, int(left + region_width)))
    y2 = max(y1 + 1, min(height, int(top + region_height)))
    crop = image.crop((x1, y1, x2, y2)).convert("RGB")
    arr = np.asarray(crop)
    area = max(1, crop.width * crop.height)
    gray = arr.min(axis=2)
    ink = int(np.count_nonzero(ink_foreground_mask(arr)))
    density = ink / area
    page_area = max(1, width * height)
    region_area_ratio = area / page_area
    min_density = _SMALL_REGION_MIN_DENSITY if region_area_ratio < _SMALL_REGION_AREA_RATIO else _DEFAULT_MIN_DENSITY
    if density >= min_density:
        return True

    # Below the density floor the fixed luminance-185 cut reads the crop as
    # blank and WOULD drop it. Otsu is not automatically safer than 185 — on a
    # low-contrast light-ink signature it can fold the ink into the paper class
    # and miss it — so the drop only proceeds when Otsu STRONGLY confirms the
    # crop is background. Any weaker signal keeps the region (fail toward
    # over-coverage), so this branch can only ever DROP a subset of what the
    # fixed floor already dropped — coverage never shrinks.
    otsu = _otsu_threshold_separability(gray)
    if otsu is None:
        return True  # uniform / unmeasurable -> keep
    t_local, eta = otsu
    if eta < _OTSU_STRONG_SEPARABILITY:
        return True  # weak bimodality -> light ink may hide in the paper mode -> keep
    fg_fraction = float(np.count_nonzero(gray <= t_local)) / area
    if fg_fraction >= min_density:
        return True  # local Otsu finds ink the fixed cut missed -> keep
    return False  # strong split, foreground negligible, fixed cut blank -> drop
