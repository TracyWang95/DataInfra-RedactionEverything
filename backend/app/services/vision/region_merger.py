"""
Region Merger — geometric box/region deduplication.

Pure geometry is the *only* dedup rule — no type priorities, source ranks,
same-line heuristics or signature-name folding (each of those hardcoded rules
could drop a genuine PII box). Two modes: an IoU pass for the seal-shard merge
path, and a strict containment pass that drops a box only when its pixels are
fully covered by the union of the kept boxes (any exposed pixel keeps it), so
distinct detections and partial-overlap twins are always kept.
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


def rect_covered_by_union(target: _Rect, covers: Sequence[_Rect]) -> bool:
    """Whether ``target`` is fully covered by the union of ``covers`` rects.

    Exact axis-aligned coverage by coordinate compression — no threshold and no
    rasterization loss: clip every cover to the target, then test the midpoint
    of each compressed grid cell. A target with no positive area is vacuously
    covered (it has no pixels to lose). The direction of any error is toward
    "not covered" (a real gap keeps the box), so a caller that drops only on a
    True result can never uncover a pixel.
    """
    tx1, ty1, tw, th = target
    tx2, ty2 = tx1 + tw, ty1 + th
    if tx2 <= tx1 or ty2 <= ty1:
        return True
    xs = {tx1, tx2}
    ys = {ty1, ty2}
    clipped: list[tuple[float, float, float, float]] = []
    for c in covers:
        cx1 = max(tx1, c[0])
        cy1 = max(ty1, c[1])
        cx2 = min(tx2, c[0] + c[2])
        cy2 = min(ty2, c[1] + c[3])
        if cx2 > cx1 and cy2 > cy1:
            clipped.append((cx1, cy1, cx2, cy2))
            xs.add(cx1)
            xs.add(cx2)
            ys.add(cy1)
            ys.add(cy2)
    if not clipped:
        return False
    xs_sorted = sorted(xs)
    ys_sorted = sorted(ys)
    for i in range(len(xs_sorted) - 1):
        if xs_sorted[i + 1] <= xs_sorted[i]:
            continue
        mx = (xs_sorted[i] + xs_sorted[i + 1]) / 2.0
        for j in range(len(ys_sorted) - 1):
            if ys_sorted[j + 1] <= ys_sorted[j]:
                continue
            my = (ys_sorted[j] + ys_sorted[j + 1]) / 2.0
            if not any(k[0] <= mx <= k[2] and k[1] <= my <= k[3] for k in clipped):
                return False
    return True


def deduplicate_by_iou(
    boxes: Sequence[_Box],
    rect: Callable[[_Box], _Rect],
    iou_threshold: float = _DEDUP_IOU_THRESHOLD,
    mode: str = "iou",
) -> list[_Box]:
    """Drop spatial near-duplicates. Two modes, both leak-monotone.

    ``rect`` maps a box to ``(left, top, width, height)``, so this works for both
    normalized ``BoundingBox`` (x/y/width/height) and pixel ``SensitiveRegion``
    (left/top/width/height). Larger boxes are considered first, so a kept box
    always covers at least as much area as the box tested against it.

    ``mode="iou"`` (visual/seal merge path): drop a box whose IoU with a kept box
    clears ``iou_threshold``. Kept for the seal-shard merge, which deliberately
    folds partially-overlapping stamp fragments.

    ``mode="containment"``: drop a box ONLY when every pixel it covers already
    lies inside the union of the already-kept (larger-or-equal) boxes — any
    exposed pixel keeps both boxes. This is the strict "preserve coverage" rule:
    a partial-overlap twin that sticks out (old IoU>=0.5 would have dropped it,
    uncovering the exposed strip) is now kept, while a box swallowed whole is
    dropped because its pixels remain covered. Deliberately type-agnostic: any
    type/text/priority rule risks dropping a real detection.
    """
    ordered = sorted(boxes, key=lambda b: -_rect_area(rect(b)))
    kept: list[_Box] = []
    kept_rects: list[_Rect] = []
    for box in ordered:
        r = rect(box)
        if mode == "containment":
            if kept_rects and rect_covered_by_union(r, kept_rects):
                continue
        elif any(calc_iou_boxes(r, kept_rect) >= iou_threshold for kept_rect in kept_rects):
            continue
        kept.append(box)
        kept_rects.append(r)
    return kept
