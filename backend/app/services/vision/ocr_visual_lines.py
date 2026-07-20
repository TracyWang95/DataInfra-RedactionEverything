"""Visual-line geometry and reconstruction.

Split out of ocr_pipeline.py (which stays the public facade): same-visual-line
tests, short-CJK-prefix bridging, block union, entity-agnostic virtual line
reconstruction and typical text-line height inference.
"""
from __future__ import annotations

from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.has_text_payload import _compact_text
from app.services.vision.ocr_tuning import (
    _BRIDGE_COMBINED_MAX_LEN,
    _BRIDGE_LEFT_MAX_LEN,
    _BRIDGE_LEFT_MIN_CJK,
    _BRIDGE_LEFT_MIN_LEN,
    _BRIDGE_RIGHT_MAX_LEN,
    _BRIDGE_RIGHT_MIN_CJK,
    _BRIDGE_RIGHT_MIN_LEN,
    _RECONSTRUCT_TALL_ASPECT_MULT,
    _RECONSTRUCT_TALL_HEIGHT_MULT,
    _SAME_LINE_CENTER_HEIGHT_RATIO,
    _SAME_LINE_VERTICAL_OVERLAP_RATIO,
    _TEXTLINE_MIN_HEIGHT_PX,
    _UNION_BLOCK_CONFIDENCE_FACTOR,
    _VISUAL_LINE_JOIN_GAP_HEIGHT_MULT,
    _VISUAL_LINE_JOIN_GAP_MIN_PX,
)


def _blocks_same_visual_line(left: OCRTextBlock, right: OCRTextBlock) -> bool:
    left_top = float(left.top)
    right_top = float(right.top)
    left_bottom = left_top + max(1.0, float(left.height))
    right_bottom = right_top + max(1.0, float(right.height))
    overlap = min(left_bottom, right_bottom) - max(left_top, right_top)
    if overlap > 0 and overlap / max(1.0, min(float(left.height), float(right.height))) >= _SAME_LINE_VERTICAL_OVERLAP_RATIO:
        return True
    left_center = left_top + float(left.height) / 2
    right_center = right_top + float(right.height) / 2
    return abs(left_center - right_center) <= max(float(left.height), float(right.height)) * _SAME_LINE_CENTER_HEIGHT_RATIO


def _should_join_visual_line_blocks(left: OCRTextBlock, right: OCRTextBlock) -> bool:
    if not _blocks_same_visual_line(left, right):
        return False
    gap = int(right.left) - int(left.left + left.width)
    if gap < 0:
        return False
    typical_height = max(1, int(max(left.height, right.height)))
    return gap <= max(_VISUAL_LINE_JOIN_GAP_MIN_PX, int(typical_height * _VISUAL_LINE_JOIN_GAP_HEIGHT_MULT))


def _is_plain_cjk_or_alnum(text: str) -> bool:
    compact = _compact_text(text)
    return bool(compact) and all(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in compact)


def _cjk_count(text: str) -> int:
    return sum(1 for ch in _compact_text(text) if "\u4e00" <= ch <= "\u9fff")


def _should_bridge_short_cjk_prefix(left: OCRTextBlock, right: OCRTextBlock) -> bool:
    left_text = _compact_text(left.text)
    right_text = _compact_text(right.text)
    if not (_BRIDGE_LEFT_MIN_LEN <= len(left_text) <= _BRIDGE_LEFT_MAX_LEN and _BRIDGE_RIGHT_MIN_LEN <= len(right_text) <= _BRIDGE_RIGHT_MAX_LEN):
        return False
    if len(left_text + right_text) > _BRIDGE_COMBINED_MAX_LEN:
        return False
    if not (_is_plain_cjk_or_alnum(left_text) and _is_plain_cjk_or_alnum(right_text)):
        return False
    if any(ch.isdigit() for ch in left_text):
        return False
    return _cjk_count(left_text) >= _BRIDGE_LEFT_MIN_CJK and _cjk_count(right_text) >= _BRIDGE_RIGHT_MIN_CJK


def _join_visual_line_text(left: str, right: str) -> str:
    if _is_plain_cjk_or_alnum(left) and _is_plain_cjk_or_alnum(right):
        return f"{_compact_text(left)}{_compact_text(right)}"
    return f"{str(left).strip()} {str(right).strip()}".strip()


def _union_ocr_blocks(blocks: list[OCRTextBlock], text: str) -> OCRTextBlock:
    left = min(int(block.left) for block in blocks)
    top = min(int(block.top) for block in blocks)
    right = max(int(block.left + block.width) for block in blocks)
    bottom = max(int(block.top + block.height) for block in blocks)
    return OCRTextBlock(
        text=text,
        polygon=[
            [left, top],
            [right, top],
            [right, bottom],
            [left, bottom],
        ],
        confidence=min(float(block.confidence) for block in blocks) * _UNION_BLOCK_CONFIDENCE_FACTOR,
    )


def reconstruct_visual_line_blocks(ocr_blocks: list[OCRTextBlock]) -> list[OCRTextBlock]:
    """Create entity-agnostic virtual lines from adjacent OCR blocks."""
    typical_height = _infer_typical_textline_height(ocr_blocks) or 0
    text_blocks = [
        block
        for block in ocr_blocks
        if _compact_text(block.text)
        and not str(block.text or "").lstrip().startswith("<table")
        and not (
            typical_height
            and block.height > typical_height * _RECONSTRUCT_TALL_HEIGHT_MULT
            and block.width < block.height * _RECONSTRUCT_TALL_ASPECT_MULT
        )
    ]
    if len(text_blocks) < 2:
        return []

    virtual_blocks: list[OCRTextBlock] = []
    seen: set[str] = set()
    ordered_blocks = sorted(text_blocks, key=lambda item: (item.left, item.top))
    for left in ordered_blocks:
        right_candidates = [
            right
            for right in ordered_blocks
            if right.left > left.left
            and _should_join_visual_line_blocks(left, right)
            and _should_bridge_short_cjk_prefix(left, right)
        ]
        if not right_candidates:
            continue
        right = min(right_candidates, key=lambda item: item.left - (left.left + left.width))
        text = _join_visual_line_text(str(left.text or ""), str(right.text or ""))
        compact = _compact_text(text)
        if compact and compact not in seen:
            seen.add(compact)
            virtual_blocks.append(_union_ocr_blocks([left, right], text))

    return virtual_blocks


def _infer_typical_textline_height(blocks: list[OCRTextBlock]) -> int | None:
    heights = [
        block.height
        for block in blocks
        if block.height > _TEXTLINE_MIN_HEIGHT_PX
        and block.width > block.height
        and not block.text.lstrip().startswith(("<table", "<div"))
    ]
    if not heights:
        return None
    heights = sorted(heights)
    return int(heights[(len(heights) - 1) // 2])
