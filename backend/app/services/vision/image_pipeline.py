"""
Image Pipeline - visual feature region refinement and image manipulation.

Responsibilities:
- Matching visual feature regions with OCR text blocks (coordinate refinement)
- Drawing detection boxes on images (debug/preview visualization)
- Applying redaction (solid color overlay on sensitive regions)
"""
from __future__ import annotations

import logging
import os
from difflib import SequenceMatcher

from PIL import Image, ImageDraw, ImageFont

from app.services.ocr_has_vision_service import OCRTextBlock, SensitiveRegion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Visual feature / OCR matching (coordinate refinement)
# ---------------------------------------------------------------------------

def match_ocr_to_visual_regions(
    ocr_blocks: list[OCRTextBlock],
    visual_regions: list[SensitiveRegion],
    iou_threshold: float = 0.3,
) -> list[SensitiveRegion]:
    """
    Refine visual feature regions using OCR text blocks.

    When a visual region overlaps an OCR block (by IoU or text similarity), the
    OCR block's more precise coordinates are used instead.
    """
    from app.services.vision.region_merger import calc_iou_boxes

    def normalize_text(text: str) -> str:
        if not text:
            return ""
        return "".join(
            ch
            for ch in text
            if not ch.isspace() and (ch.isalnum() or ch == "_" or "\u4e00" <= ch <= "\u9fff")
        )

    refined_regions: list[SensitiveRegion] = []

    for visual_region in visual_regions:
        visual_box = (visual_region.left, visual_region.top, visual_region.width, visual_region.height)

        best_match: OCRTextBlock | None = None
        best_iou = 0.0

        for ocr_block in ocr_blocks:
            ocr_box = (ocr_block.left, ocr_block.top, ocr_block.width, ocr_block.height)
            iou = calc_iou_boxes(visual_box, ocr_box)

            if iou > best_iou and iou >= iou_threshold:
                best_iou = iou
                best_match = ocr_block

        if not best_match:
            # IoU failed - fall back to text similarity
            norm_visual = normalize_text(visual_region.text)
            if norm_visual:
                for ocr_block in ocr_blocks:
                    norm_ocr = normalize_text(ocr_block.text)
                    if norm_ocr and (norm_visual in norm_ocr or norm_ocr in norm_visual):
                        best_match = ocr_block
                        break
                    if norm_ocr:
                        ratio = SequenceMatcher(None, norm_visual, norm_ocr).ratio()
                        if ratio >= 0.6:
                            best_match = ocr_block
                            break

        if best_match:
            refined_regions.append(SensitiveRegion(
                text=best_match.text,
                entity_type=visual_region.entity_type,
                left=best_match.left,
                top=best_match.top,
                width=best_match.width,
                height=best_match.height,
                confidence=max(visual_region.confidence, best_match.confidence),
                source="merged",
                color=visual_region.color,
            ))
        else:
            refined_regions.append(visual_region)

    return refined_regions


# ---------------------------------------------------------------------------
# Drawing / visualization
# ---------------------------------------------------------------------------

def draw_regions_on_image(
    image: Image.Image,
    regions: list[SensitiveRegion],
) -> Image.Image:
    """Draw bounding boxes and labels on an image for debugging / preview."""
    draw_image = image.copy()
    draw = ImageDraw.Draw(draw_image)

    # Try to load a CJK font
    font = None
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 14)
                break
            except OSError:
                pass
    if not font:
        font = ImageFont.load_default()

    type_colors = {
        # People
        "PERSON": (59, 130, 246),
        # Organizations
        "ORG": (16, 185, 129),
        "COMPANY": (20, 184, 166),
        # Contact
        "PHONE": (249, 115, 22),
        "EMAIL": (234, 179, 8),
        # IDs
        "ID_CARD": (239, 68, 68),
        "BANK_CARD": (236, 72, 153),
        # Bank accounts
        "ACCOUNT_NAME": (168, 85, 247),
        "BANK_NAME": (124, 58, 237),
        "ACCOUNT_NUMBER": (139, 92, 246),
        # Address
        "ADDRESS": (99, 102, 241),
        # Date
        "DATE": (161, 98, 7),
        # Visual
        "SEAL": (220, 20, 60),
    }

    for region in regions:
        color = type_colors.get(region.entity_type, (255, 0, 0))

        x1, y1 = region.left, region.top
        x2, y2 = region.left + region.width, region.top + region.height
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)

        label = f"{region.entity_type}"
        if region.text:
            label += f": {region.text[:15]}"

        bbox = draw.textbbox((x1, y1 - 18), label, font=font)
        draw.rectangle([bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2], fill=color)
        draw.text((x1, y1 - 18), label, fill=(255, 255, 255), font=font)

    return draw_image


# ---------------------------------------------------------------------------
# Redaction application
# ---------------------------------------------------------------------------

def apply_redaction(
    image: Image.Image,
    regions: list[SensitiveRegion],
    redaction_color: tuple[int, int, int] = (0, 0, 0),
) -> Image.Image:
    """Cover sensitive regions with a solid color block."""
    draw = ImageDraw.Draw(image)

    for region in regions:
        x1, y1 = region.left, region.top
        x2, y2 = region.left + region.width, region.top + region.height
        draw.rectangle([x1, y1, x2, y2], fill=redaction_color)

    return image
