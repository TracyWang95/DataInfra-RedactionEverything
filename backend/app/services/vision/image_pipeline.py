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
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum

from PIL import Image, ImageDraw, ImageFont

from app.services.ocr_has_vision_service import OCRTextBlock, SensitiveRegion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Visual feature / OCR matching (coordinate refinement)
# ---------------------------------------------------------------------------

# Thresholds for matching an OCR block to a visual region (names for pre-existing
# literals; values unchanged).
_OCR_VISUAL_MATCH_IOU_THRESHOLD = 0.3
_OCR_VISUAL_TEXT_SIMILARITY_MIN = 0.6


def match_ocr_to_visual_regions(
    ocr_blocks: list[OCRTextBlock],
    visual_regions: list[SensitiveRegion],
    iou_threshold: float = _OCR_VISUAL_MATCH_IOU_THRESHOLD,
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
                        if ratio >= _OCR_VISUAL_TEXT_SIMILARITY_MIN:
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
# Drawing / visualization (shared preview rendering core)
# ---------------------------------------------------------------------------

# Preview/debug rendering constants (names for pre-existing literals; unchanged).
_PREVIEW_FONT_SIZE = 14
_PREVIEW_BOX_WIDTH = 2
_PREVIEW_LABEL_BG_PAD = 2
_PREVIEW_LABEL_TEXT_COLOR = (255, 255, 255)
_PREVIEW_FONT_PATHS = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
]


class SourcePipeline(Enum):
    """Which recall channel produced a detection box."""

    TEXT = "text"        # OCR+HaS text chain (incl. regex_fallback, PDF text layer)
    VISUAL = "visual"    # LocateAnything / visual_features chain


# Preview colours encode the SOURCE PIPELINE, not the entity type (type info is
# carried by the label text). The frontend has no source-colour convention for
# badges, so: visual aligns with the frontend's default vision-type colour
# #6366F1 (indigo); text uses #059669 (green) for clear contrast at 2px lines.
TEXT_PIPELINE_COLOR = (5, 150, 105)     # #059669
VISUAL_PIPELINE_COLOR = (99, 102, 241)  # #6366F1

_SOURCE_PIPELINE_COLORS = {
    SourcePipeline.TEXT: TEXT_PIPELINE_COLOR,
    SourcePipeline.VISUAL: VISUAL_PIPELINE_COLOR,
}


@dataclass(frozen=True)
class PreviewBox:
    """One detection box for preview rendering, in pixel coordinates."""

    left: int
    top: int
    right: int
    bottom: int
    label: str
    pipeline: SourcePipeline


def _load_preview_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a CJK-capable font from the platform table, else PIL default."""
    for fp in _PREVIEW_FONT_PATHS:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, _PREVIEW_FONT_SIZE)
            except OSError:
                pass
    return ImageFont.load_default()


def draw_preview_boxes(
    image: Image.Image,
    boxes: list[PreviewBox],
) -> Image.Image:
    """Shared rendering core: boxes + full-text labels (coloured block, white text).

    Labels are never truncated. Placement prefers above the box; near canvas
    edges it falls back to below the box, then inside the box, and is clamped
    horizontally so the label block stays on the canvas.
    """
    draw_image = image.copy()
    draw = ImageDraw.Draw(draw_image)
    font = _load_preview_font()
    img_w, img_h = draw_image.size
    pad = _PREVIEW_LABEL_BG_PAD

    for box in boxes:
        color = _SOURCE_PIPELINE_COLORS[box.pipeline]
        draw.rectangle([box.left, box.top, box.right, box.bottom], outline=color, width=_PREVIEW_BOX_WIDTH)

        if not box.label:
            continue

        # Measure the label once at origin; the rendered bbox just shifts.
        text_bbox = draw.textbbox((0, 0), box.label, font=font)
        block_w = (text_bbox[2] - text_bbox[0]) + 2 * pad
        block_h = (text_bbox[3] - text_bbox[1]) + 2 * pad

        # Vertical: above the box -> below the box -> inside at the top edge.
        if box.top - block_h >= 0:
            block_top = box.top - block_h
        elif box.bottom + block_h <= img_h:
            block_top = box.bottom
        else:
            block_top = max(0, min(box.top, img_h - block_h))
        # Horizontal: align with the box's left edge, clamped onto the canvas.
        block_left = max(0, min(box.left, img_w - block_w))

        draw.rectangle(
            [block_left, block_top, block_left + block_w, block_top + block_h],
            fill=color,
        )
        text_origin = (
            block_left + pad - text_bbox[0],
            block_top + pad - text_bbox[1],
        )
        draw.text(text_origin, box.label, fill=_PREVIEW_LABEL_TEXT_COLOR, font=font)

    return draw_image


def draw_regions_on_image(
    image: Image.Image,
    regions: list[SensitiveRegion],
) -> Image.Image:
    """Draw OCR+HaS text-chain regions for debugging / preview.

    Everything in this chain (incl. regex_fallback and OCR-supplied visual
    regions) was recalled by the text pipeline, so it all gets the text colour.
    """
    boxes = []
    for region in regions:
        label = f"{region.entity_type}"
        if region.text:
            label += f": {region.text}"
        boxes.append(PreviewBox(
            left=region.left,
            top=region.top,
            right=region.left + region.width,
            bottom=region.top + region.height,
            label=label,
            pipeline=SourcePipeline.TEXT,
        ))
    return draw_preview_boxes(image, boxes)


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
