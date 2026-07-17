# Copyright 2026 DataInfra-RedactionEverything Contributors
"""LA 多采样共识：同一图跑 N 次 seedless 采样，只保留多数次都出现的框。

LA 用官方 temp 0.7 + seedless 开放采样（A/B 验证过：低温=硬漏检、固定seed=坏样本
永久化），代价是每次结果有波动——复杂图上偶尔幻觉出多余的公章/签字/指纹框。共识在
不动采样参数的前提下压这个波动：同 type 且 IoU≥阈值的框聚为一簇，只有被 ≥min_votes
个不同 run 支持的簇才保留（只出现 1 次的幻觉被过滤，每次都在的真框保留），代表框取
簇内各维中位数。samples≤1 或 min_votes≤1 → 直接返回首次结果（向后兼容，默认关闭）。
"""
from __future__ import annotations

from collections import defaultdict

from app.models.entity_schemas import BoundingBox


def _iou(a: BoundingBox, b: BoundingBox) -> float:
    x1, y1 = max(a.x, b.x), max(a.y, b.y)
    x2 = min(a.x + a.width, b.x + b.width)
    y2 = min(a.y + a.height, b.y + b.height)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    union = a.width * a.height + b.width * b.height - inter
    return inter / union if union > 0 else 0.0


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def consensus_boxes(
    runs: list[list[BoundingBox]],
    min_votes: int,
    iou_thresh: float = 0.5,
) -> list[BoundingBox]:
    """跨 N 次采样取共识框。见模块 docstring。"""
    runs = [r for r in runs if r]
    if not runs:
        return []
    if len(runs) == 1 or min_votes <= 1:
        return runs[0]

    by_type: dict[str, list[tuple[int, BoundingBox]]] = defaultdict(list)
    for run_idx, run in enumerate(runs):
        for box in run:
            by_type[box.type].append((run_idx, box))

    out: list[BoundingBox] = []
    for group in by_type.values():
        used = [False] * len(group)
        for i in range(len(group)):
            if used[i]:
                continue
            # single-linkage: 与簇内任一框 IoU≥阈值即入簇, 传递扩展(避免链式相邻框被漏)
            cluster = [group[i]]
            used[i] = True
            grew = True
            while grew:
                grew = False
                for j in range(len(group)):
                    if used[j]:
                        continue
                    if any(_iou(cb, group[j][1]) >= iou_thresh for _, cb in cluster):
                        cluster.append(group[j])
                        used[j] = True
                        grew = True
            votes = len({run_idx for run_idx, _ in cluster})
            if votes < min_votes:
                continue
            boxes = [b for _, b in cluster]
            rep = max(boxes, key=lambda b: b.confidence)
            out.append(rep.model_copy(update={
                "x": _median([b.x for b in boxes]),
                "y": _median([b.y for b in boxes]),
                "width": _median([b.width for b in boxes]),
                "height": _median([b.height for b in boxes]),
            }))
    return out
