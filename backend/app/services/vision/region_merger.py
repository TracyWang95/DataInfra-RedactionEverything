# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
Region Merger - Region deduplication, IoU calculation, and confidence normalization.

Responsibilities:
- IoU (Intersection over Union) computation for bounding boxes
- Merging region lists from different pipelines with deduplication
"""
from __future__ import annotations

import logging
from typing import List, Tuple

from app.services.hybrid_vision_service import SensitiveRegion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IoU helpers
# ---------------------------------------------------------------------------

def calc_iou_boxes(
    box1: Tuple[int, int, int, int],
    box2: Tuple[int, int, int, int],
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
    regions1: List[SensitiveRegion],
    regions2: List[SensitiveRegion],
    iou_threshold: float = 0.5,
) -> List[SensitiveRegion]:
    """
    Merge two region lists, dropping entries from *regions2* that overlap with
    an existing entry in *regions1* above *iou_threshold*.
    """
    merged = list(regions1)

    for r2 in regions2:
        is_duplicate = False
        for r1 in merged:
            if calc_iou_regions(r1, r2) >= iou_threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            merged.append(r2)

    return merged
