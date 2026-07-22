# Copyright 2026 DataInfra-RedactionEverything Contributors

"""检测框的纯几何计算：重叠、包含、行高。

没有状态、没有 I/O、不认识任何服务对象——合并与仲裁策略要用的度量都在这里，
策略本身留在 vision_service。
"""

from app.models.schemas import BoundingBox


def _higher_confidence(a: float | None, b: float | None) -> float | None:
    """两个框折叠时保留较高的分；None 表示没人测过。

    缺分不是零：把未测的框折进已测的框，既不能凭空造一个数，也不能把已测的
    那个拉低。
    """
    scores = [s for s in (a, b) if s is not None]
    return max(scores) if scores else None


def _norm_box_type(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

def _calculate_iou(box1: BoundingBox, box2: BoundingBox) -> float:
    x1 = max(box1.x, box2.x)
    y1 = max(box1.y, box2.y)
    x2 = min(box1.x + box1.width, box2.x + box2.width)
    y2 = min(box1.y + box1.height, box2.y + box2.height)

    if x2 <= x1 or y2 <= y1:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)
    area1 = box1.width * box1.height
    area2 = box2.width * box2.height
    union = area1 + area2 - intersection

    if union <= 0:
        return 0.0

    return intersection / union

def _calculate_smaller_overlap(box1: BoundingBox, box2: BoundingBox) -> float:
    x1 = max(box1.x, box2.x)
    y1 = max(box1.y, box2.y)
    x2 = min(box1.x + box1.width, box2.x + box2.width)
    y2 = min(box1.y + box1.height, box2.y + box2.height)

    if x2 <= x1 or y2 <= y1:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)
    smaller = min(box1.width * box1.height, box2.width * box2.height)
    if smaller <= 0:
        return 0.0
    return intersection / smaller

def _center_inside(inner: BoundingBox, outer: BoundingBox) -> bool:
    """True if the center point of ``inner`` lies within ``outer``."""
    cx = inner.x + inner.width / 2.0
    cy = inner.y + inner.height / 2.0
    return outer.x <= cx <= outer.x + outer.width and outer.y <= cy <= outer.y + outer.height

def _x_overlap_fraction(a: BoundingBox, b: BoundingBox) -> float:
    """Horizontal overlap as a fraction of the narrower box (0..1)."""
    lo = max(a.x, b.x)
    hi = min(a.x + a.width, b.x + b.width)
    return max(0.0, hi - lo) / max(1e-9, min(a.width, b.width))

def _has_vertically_disjoint_pair(boxes: list[BoundingBox]) -> bool:
    """True if any two boxes in the column don't vertically overlap.

    Two vertically disjoint LA boxes mean two distinct text rows live in
    this column — the value's row is then ambiguous.
    """
    for i in range(len(boxes)):
        a = boxes[i]
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            overlap = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
            if overlap <= 1e-9:
                return True
    return False


def _doc_line_height(boxes: list[BoundingBox]) -> float:
    """Self-calibrated document line height (normalized) from the OCR boxes.

    This must NOT be the median box height: char-box merge is exactly what
    inflates some value boxes, so the median is contaminated by the tall
    tail. But merge only ever GROWS a box's height (union over a taller
    block) — it never shrinks one below the true single-line glyph height.
    So the true line height is the LOWER envelope of the height
    distribution, and a low quantile (median of the shorter half ≈ 25th
    percentile) is a robust estimate immune to the inflated tail. Derived
    purely from the page's own boxes — no fixed pixel constant. Returns 0.0
    when there is nothing to calibrate from (caller then skips tightening).
    """
    hs = sorted(
        b.height
        for b in boxes
        if b.source == "ocr_has" and str(b.text or "").strip() and b.height > 0
    )
    if not hs:
        return 0.0
    lower = hs[: max(1, len(hs) // 2)]
    return lower[len(lower) // 2]

