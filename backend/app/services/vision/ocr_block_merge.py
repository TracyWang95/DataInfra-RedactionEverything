"""OCR block merging: IoU + content-relation merge of primary/extra engine blocks.

Split out of ocr_pipeline.py (which stays the public facade).
"""
from __future__ import annotations

from difflib import SequenceMatcher

from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.has_text_payload import _compact_text
from app.services.vision.ocr_tuning import (
    _MERGE_DUPLICATE_IOU,
    _MERGE_OVERLAP_IOU,
    _SHORT_FIELD_MAX_COMPACT_LEN,
    _SHORT_FIELD_MAX_DELIMITERS,
    _SHORT_FIELD_MIN_COMPACT_LEN,
    _SUPPLEMENT_HEIGHT_RATIO,
    _SUPPLEMENT_LONGER_TEXT_MARGIN,
    _SUPPLEMENT_SIMILARITY_MIN,
    _SUPPLEMENT_WIDER_RATIO,
    _SUPPLEMENT_WIDTH_RATIO,
)


def _is_coarse_markup_block(block: OCRTextBlock) -> bool:
    return block.text.lstrip().lower().startswith(("<table", "<html", "<div"))


def _merge_ocr_blocks(
    primary: list[OCRTextBlock],
    extra: list[OCRTextBlock],
    *,
    prefer_extra_text: bool = False,
) -> list[OCRTextBlock]:
    """Merge extra blocks into primary; primary wins on overlap.

    prefer_extra_text: the extra engine reads glyphs more accurately than the
    primary one (PaddleOCR-VL vs the PP-OCR line recognizer). When an extra
    block re-reads an existing line — same place with equal glyph count, or a
    fuller reading of the same pixels — its text is carried onto the existing
    block while the existing geometry and char boxes (value-crop evidence) are
    kept, and the box widens to the union so the mask never claims pixels it
    does not cover.
    """
    if extra:
        merged = [
            block for block in primary
            if not _is_coarse_markup_block(block)
        ]
    else:
        merged = list(primary)

    def iou(a: OCRTextBlock, b: OCRTextBlock) -> float:
        ax1, ay1, ax2, ay2 = a.bbox
        bx1, by1, bx2, by2 = b.bbox
        x1, y1 = max(ax1, bx1), max(ay1, by1)
        x2, y2 = min(ax2, bx2), min(ay2, by2)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        inter = (x2 - x1) * (y2 - y1)
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        return inter / (area_a + area_b - inter)

    def looks_like_short_field(block: OCRTextBlock) -> bool:
        text = str(block.text or "").strip()
        compact = _compact_text(text)
        if len(compact) < _SHORT_FIELD_MIN_COMPACT_LEN or len(compact) > _SHORT_FIELD_MAX_COMPACT_LEN:
            return False
        if not any(separator in text for separator in (":", "：")):
            return False
        if text.count(":") + text.count("：") > _SHORT_FIELD_MAX_DELIMITERS:
            return False
        return block.width > 0 and block.height > 0

    def is_structure_precision_supplement(existing: OCRTextBlock, candidate: OCRTextBlock) -> bool:
        if not looks_like_short_field(candidate):
            return False
        existing_text = _compact_text(existing.text)
        candidate_text = _compact_text(candidate.text)
        if not existing_text or not candidate_text or existing_text == candidate_text:
            return False
        if candidate.width > existing.width * _SUPPLEMENT_WIDTH_RATIO or candidate.height > existing.height * _SUPPLEMENT_HEIGHT_RATIO:
            return False
        similar = SequenceMatcher(None, candidate_text, existing_text).ratio()
        if candidate_text not in existing_text and existing_text not in candidate_text and similar < _SUPPLEMENT_SIMILARITY_MIN:
            return False
        return existing.width > candidate.width * _SUPPLEMENT_WIDER_RATIO or len(existing_text) > len(candidate_text) + _SUPPLEMENT_LONGER_TEXT_MARGIN

    def content_relation(candidate_compact: str, existing_compact: str) -> str | None:
        """How the candidate's content relates to the existing block's.

        Identity facts only, no similarity thresholds: 'same' for equal glyph
        counts (two recognizers reading the same glyphs differently, e.g.
        戬浜/我浜); 'subset'/'superset' when the shorter text is an in-order
        subsequence of the longer (one engine dropped or recovered glyphs);
        None when the readings are unrelated content.
        """
        if not candidate_compact or not existing_compact:
            return None
        if len(candidate_compact) == len(existing_compact):
            return "same"
        shorter, longer = sorted((candidate_compact, existing_compact), key=len)
        corresponding = sum(
            size
            for _shorter_pos, _longer_pos, size in SequenceMatcher(
                None, shorter, longer, autojunk=False
            ).get_matching_blocks()
        )
        if corresponding != len(shorter):
            return None
        return "subset" if shorter is candidate_compact else "superset"

    def adopted_block(existing: OCRTextBlock, candidate: OCRTextBlock) -> OCRTextBlock:
        left = min(existing.bbox[0], candidate.bbox[0])
        top = min(existing.bbox[1], candidate.bbox[1])
        right = max(existing.bbox[2], candidate.bbox[2])
        bottom = max(existing.bbox[3], candidate.bbox[3])
        return OCRTextBlock(
            text=candidate.text,
            polygon=[[left, top], [right, top], [right, bottom], [left, bottom]],
            confidence=existing.confidence,
            chars=existing.chars,
        )

    for block in extra:
        if _is_coarse_markup_block(block):
            continue
        compact = _compact_text(block.text)
        duplicate = False
        for index, existing in enumerate(merged):
            overlap = iou(block, existing)
            if overlap > _MERGE_DUPLICATE_IOU:
                relation = content_relation(compact, _compact_text(existing.text))
                if prefer_extra_text and relation in ("same", "superset"):
                    merged[index] = adopted_block(existing, block)
                    duplicate = True
                    break
                if relation in ("same", "subset"):
                    duplicate = True
                    break
            if overlap > _MERGE_OVERLAP_IOU:
                if is_structure_precision_supplement(existing, block):
                    continue
                duplicate = True
                break
        if not duplicate:
            merged.append(block)
    return merged
