"""
Region Merger - Region deduplication, IoU calculation, and confidence normalization.

Responsibilities:
- IoU (Intersection over Union) computation for bounding boxes
- Merging region lists from different pipelines with deduplication
"""
from __future__ import annotations

import logging

from app.services.ocr_has_vision_service import SensitiveRegion

logger = logging.getLogger(__name__)

# Merge / dedup thresholds (names for pre-existing literals; values unchanged).
_MERGE_DEFAULT_IOU_THRESHOLD = 0.5
_MERGE_SAME_TYPE_OVERLAP_MIN = 0.7
_MERGE_TIGHTER_AREA_RATIO = 0.9
# Entity-type precedence when two overlapping regions compete (higher wins).
_DEFAULT_ENTITY_PRIORITY = 1
_ENTITY_TYPE_PRIORITY = {
    "PERSON": 6,
    "PHONE": 6,
    "ID_CARD": 6,
    "BANK_ACCOUNT": 6,
    "BANK_CARD": 6,
    "BANK_NAME": 6,
    "AMOUNT": 6,
    "COMPANY": 5,
    "ORG": 4,
    "LEGAL_PARTY": 3,
}


# ---------------------------------------------------------------------------
# IoU helpers
# ---------------------------------------------------------------------------

def calc_iou_boxes(
    box1: tuple[int, int, int, int],
    box2: tuple[int, int, int, int],
) -> float:
    """
    Compute IoU for two bounding boxes given as (left, top, width, height).
    """
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[0] + box1[2], box2[0] + box2[2])
    y2 = min(box1[1] + box1[3], box2[1] + box2[3])

    if x2 <= x1 or y2 <= y1:
        return 0.0

    inter_area = (x2 - x1) * (y2 - y1)
    box1_area = box1[2] * box1[3]
    box2_area = box2[2] * box2[3]
    union_area = box1_area + box2_area - inter_area

    return inter_area / union_area if union_area > 0 else 0.0


def calc_iou_regions(r1: SensitiveRegion, r2: SensitiveRegion) -> float:
    """Compute IoU between two SensitiveRegion instances."""
    return calc_iou_boxes(
        (r1.left, r1.top, r1.width, r1.height),
        (r2.left, r2.top, r2.width, r2.height),
    )


# ---------------------------------------------------------------------------
# Merge / deduplication
# ---------------------------------------------------------------------------

def merge_regions(
    regions1: list[SensitiveRegion],
    regions2: list[SensitiveRegion],
    iou_threshold: float = _MERGE_DEFAULT_IOU_THRESHOLD,
) -> list[SensitiveRegion]:
    """
    Merge two region lists, dropping entries from *regions2* that overlap with
    an existing entry in *regions1* above *iou_threshold*.
    """
    def compact(text: str | None) -> str:
        return "".join(str(text or "").split())

    def overlap_ratio(a: SensitiveRegion, b: SensitiveRegion) -> float:
        x1 = max(a.left, b.left)
        y1 = max(a.top, b.top)
        x2 = min(a.left + a.width, b.left + b.width)
        y2 = min(a.top + a.height, b.top + b.height)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        inter = (x2 - x1) * (y2 - y1)
        smaller = max(1, min(a.width * a.height, b.width * b.height))
        return inter / smaller

    def area(region: SensitiveRegion) -> int:
        return max(1, region.width * region.height)

    def should_replace(existing: SensitiveRegion, candidate: SensitiveRegion) -> bool:
        existing_priority = _ENTITY_TYPE_PRIORITY.get(existing.entity_type, _DEFAULT_ENTITY_PRIORITY)
        candidate_priority = _ENTITY_TYPE_PRIORITY.get(candidate.entity_type, _DEFAULT_ENTITY_PRIORITY)
        if candidate_priority > existing_priority:
            return True
        if candidate_priority < existing_priority:
            return False

        if candidate.entity_type == existing.entity_type and overlap_ratio(candidate, existing) >= _MERGE_SAME_TYPE_OVERLAP_MIN:
            candidate_text = compact(candidate.text)
            existing_text = compact(existing.text)
            candidate_is_tighter = area(candidate) < area(existing) * _MERGE_TIGHTER_AREA_RATIO
            if candidate_is_tighter and len(candidate_text) <= len(existing_text):
                return True
        return False

    def duplicate_index(candidate: SensitiveRegion, merged: list[SensitiveRegion]) -> int | None:
        candidate_text = compact(candidate.text)
        for idx, existing in enumerate(merged):
            same_text_overlap = (
                candidate_text
                and candidate_text == compact(existing.text)
                and overlap_ratio(candidate, existing) >= _MERGE_SAME_TYPE_OVERLAP_MIN
            )
            if (
                same_text_overlap
                or calc_iou_regions(existing, candidate) >= iou_threshold
            ):
                return idx
        return None

    merged: list[SensitiveRegion] = []
    for region in [*regions1, *regions2]:
        idx = duplicate_index(region, merged)
        if idx is None:
            merged.append(region)
            continue
        existing = merged[idx]
        if should_replace(existing, region):
            merged[idx] = region

    return merged
