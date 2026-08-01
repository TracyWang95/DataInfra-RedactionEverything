"""Window-geometry helper shared by the vision stage.

``_axis_positions`` gives start / center / end anchor offsets for a sliding
window; PaddleOCR-VL's wide-block char-box windowing (``ocr_paddle_extract``)
grounds its crops on it.

This module used to hold the zero-recall tile-retry geometry and the slug gates
that drove it. That path is retired: 公章 is detected by PaddleOCR-VL (primary)
+ YOLO, qr_code/barcode by the YOLO machine-code detector, fingerprint/signature
by their own detectors — so LocateAnything now outputs directly with no tile
passes and the margin/bottom/grid tile geometry it needed is gone.
"""
from __future__ import annotations


def _axis_positions(total: int, window: int) -> list[int]:
    """start / center / end anchor offsets for a sliding window."""
    last = max(0, total - window)
    return sorted({0, last // 2, last})
