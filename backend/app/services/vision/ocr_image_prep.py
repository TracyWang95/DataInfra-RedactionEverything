"""Image preparation: decode/EXIF-orient/RGB-convert plus blank-page detection.

Split out of ocr_pipeline.py (which stays the public facade).
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps

from app.services.vision.ocr_tuning import (
    _BLANK_PAGE_DARK_PIXEL_MAX,
    _BLANK_PAGE_DARK_RATIO_MAX,
    _BLANK_PAGE_INK_PIXEL_MAX,
    _BLANK_PAGE_INK_RATIO_MAX,
    _BLANK_PAGE_MIN_HEIGHT_PX,
    _BLANK_PAGE_MIN_WIDTH_PX,
    _BLANK_PAGE_THUMBNAIL_PX,
)


def prepare_image(image_bytes: bytes) -> tuple[Image.Image, int, int]:
    """Decode image bytes, apply EXIF orientation, convert to RGB."""
    image = Image.open(io.BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image, image.width, image.height


def _is_effectively_blank_page(image: Image.Image) -> tuple[bool, float, float]:
    """Return whether a page is blank enough to skip expensive OCR inference."""
    if image.width < _BLANK_PAGE_MIN_WIDTH_PX or image.height < _BLANK_PAGE_MIN_HEIGHT_PX:
        return False, 1.0, 1.0

    sample = image.convert("RGB")
    sample.thumbnail((_BLANK_PAGE_THUMBNAIL_PX, _BLANK_PAGE_THUMBNAIL_PX))
    gray = sample.convert("L")
    histogram = gray.histogram()
    total = sum(histogram)
    if total == 0:
        return True, 0.0, 0.0

    dark_pixels = sum(histogram[:_BLANK_PAGE_DARK_PIXEL_MAX])
    ink_pixels = sum(histogram[:_BLANK_PAGE_INK_PIXEL_MAX])
    dark_ratio = dark_pixels / total
    ink_ratio = ink_pixels / total

    # Keep this threshold deliberately low: it only skips pages with essentially
    # no visible ink, while preserving faint scans, small seals, and single-line
    # pages for the semantic OCR path.
    return dark_ratio <= _BLANK_PAGE_DARK_RATIO_MAX and ink_ratio <= _BLANK_PAGE_INK_RATIO_MAX, dark_ratio, ink_ratio
