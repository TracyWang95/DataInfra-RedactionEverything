"""Geometry helpers for signature-like handwriting regions."""

from __future__ import annotations

import numpy as np


def signature_stroke_mask(rgb: np.ndarray) -> np.ndarray:
    arr = rgb.astype(np.int16, copy=False)
    red = arr[:, :, 0]
    green = arr[:, :, 1]
    blue = arr[:, :, 2]
    gray = (red * 30 + green * 59 + blue * 11) / 100
    span = arr.max(axis=2) - arr.min(axis=2)
    red_mark = (red > 120) & (red > green * 1.22) & (red > blue * 1.22)
    dark_ink = (gray < 120) | ((gray < 158) & (span < 48))
    mask = dark_ink & ~red_mark

    crop_width = mask.shape[1]
    if crop_width > 0:
        row_counts = mask.sum(axis=1)
        rule_rows = np.where(row_counts > max(80, crop_width * 0.32))[0]
        for row in rule_rows:
            mask[max(0, row - 2) : min(mask.shape[0], row + 3), :] = False
    return remove_straight_form_lines(mask)


def remove_straight_form_lines(mask: np.ndarray) -> np.ndarray:
    if mask.ndim != 2 or mask.size == 0:
        return mask

    cleaned = mask.copy()
    height, width = cleaned.shape
    row_run_min = max(36, int(width * 0.16))
    col_run_min = max(36, int(height * 0.35))

    for row in range(height):
        for start, end in true_runs(mask[row, :]):
            if end - start + 1 >= row_run_min:
                cleaned[max(0, row - 1) : min(height, row + 2), start : end + 1] = False

    column_source = cleaned.copy()
    for col in range(width):
        for start, end in true_runs(column_source[:, col]):
            if end - start + 1 >= col_run_min:
                cleaned[start : end + 1, max(0, col - 1) : min(width, col + 2)] = False
    return cleaned


def true_runs(values: np.ndarray) -> list[tuple[int, int]]:
    active = np.flatnonzero(values)
    if len(active) == 0:
        return []
    runs: list[tuple[int, int]] = []
    start = prev = int(active[0])
    for raw_index in active[1:]:
        index = int(raw_index)
        if index == prev + 1:
            prev = index
            continue
        runs.append((start, prev))
        start = prev = index
    runs.append((start, prev))
    return runs
