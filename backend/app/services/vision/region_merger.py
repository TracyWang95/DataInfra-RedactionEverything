"""
Region Merger — geometric box/region deduplication.

A single IoU pass is the *only* dedup rule. Earlier versions layered type
priorities, source ranks, same-line heuristics, containment ratios and
signature-name folding on top; each of those hardcoded rules could drop a
genuine PII box (a missed redaction). Pure IoU only ever merges boxes that
occupy essentially the same pixels, so distinct detections are always kept.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import TypeVar

logger = logging.getLogger(__name__)

# The single geometric dedup knob: two boxes whose IoU is >= this are treated as
# the same physical region. There are deliberately no other thresholds or rules.
_DEDUP_IOU_THRESHOLD = 0.5

_Box = TypeVar("_Box")
_Rect = tuple[float, float, float, float]  # (left, top, width, height)


def calc_iou_boxes(box1: _Rect, box2: _Rect) -> float:
    """Intersection-over-Union for two (left, top, width, height) rects."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[0] + box1[2], box2[0] + box2[2])
    y2 = min(box1[1] + box1[3], box2[1] + box2[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    union = box1[2] * box1[3] + box2[2] * box2[3] - inter
    return inter / union if union > 0 else 0.0


def _rect_area(r: _Rect) -> float:
    return max(0.0, r[2]) * max(0.0, r[3])


def deduplicate_by_iou(
    boxes: Sequence[_Box],
    rect: Callable[[_Box], _Rect],
    iou_threshold: float = _DEDUP_IOU_THRESHOLD,
) -> list[_Box]:
    """Drop spatial near-duplicates using IoU alone.

    ``rect`` maps a box to ``(left, top, width, height)``, so this works for both
    normalized ``BoundingBox`` (x/y/width/height) and pixel ``SensitiveRegion``
    (left/top/width/height). Larger boxes are considered first, so when two boxes
    coincide the kept one covers at least as much area — redaction never loses
    coverage. Deliberately type-agnostic: any type/text/priority rule risks
    dropping a real detection, which is exactly the bug this replaces.
    """
    ordered = sorted(boxes, key=lambda b: -_rect_area(rect(b)))
    kept: list[_Box] = []
    kept_rects: list[_Rect] = []
    for box in ordered:
        r = rect(box)
        if any(calc_iou_boxes(r, kept_rect) >= iou_threshold for kept_rect in kept_rects):
            continue
        kept.append(box)
        kept_rects.append(r)
    return kept
