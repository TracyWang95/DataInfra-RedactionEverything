"""DICOM frame rendering for reviewer previews."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from pydicom.dataset import Dataset
from pydicom.multival import MultiValue

from .errors import DicomPixelDecodeError
from .pixel import decoded_frames
from .reader import read_dataset


def _first_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, MultiValue | list | tuple):
        value = value[0] if value else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_uint8_grayscale(
    frame: np.ndarray,
    dataset: Dataset,
    *,
    window_center: float | None,
    window_width: float | None,
) -> np.ndarray:
    values = frame.astype(np.float64, copy=False)
    slope = _first_number(dataset.get("RescaleSlope"))
    intercept = _first_number(dataset.get("RescaleIntercept"))
    values = values * (slope if slope is not None else 1.0) + (intercept if intercept is not None else 0.0)

    center = window_center if window_center is not None else _first_number(dataset.get("WindowCenter"))
    width = window_width if window_width is not None else _first_number(dataset.get("WindowWidth"))
    if center is not None and width is not None:
        if width <= 0:
            raise ValueError("window_width must be greater than zero")
        low = center - (width / 2.0)
        high = center + (width / 2.0)
    else:
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            raise DicomPixelDecodeError("Decoded Pixel Data contains no finite values")
        low = float(finite.min())
        high = float(finite.max())
        if high <= low:
            high = low + 1.0
    normalised = np.clip((values - low) / (high - low), 0.0, 1.0)
    rendered = np.rint(normalised * 255.0).astype(np.uint8)
    if str(dataset.get("PhotometricInterpretation", "")).upper() == "MONOCHROME1":
        rendered = 255 - rendered
    return rendered


def render_dataset_preview(
    dataset: Dataset,
    *,
    frame_index: int = 0,
    window_center: float | None = None,
    window_width: float | None = None,
    source_path: str | Path = "",
) -> bytes:
    frames = decoded_frames(dataset, source_path=source_path)
    if not frames:
        raise DicomPixelDecodeError("DICOM instance contains no Pixel Data", details={"path": str(source_path)})
    if frame_index < 0 or frame_index >= len(frames):
        raise IndexError(f"frame_index {frame_index} is outside 0..{len(frames) - 1}")
    frame = np.asarray(frames[frame_index])
    samples = max(1, int(dataset.get("SamplesPerPixel", 1) or 1))
    if samples > 1:
        if frame.ndim != 3 or frame.shape[-1] not in {3, 4}:
            raise DicomPixelDecodeError(
                "Unsupported decoded color pixel shape",
                details={"shape": list(frame.shape), "samples_per_pixel": samples},
            )
        if frame.dtype != np.uint8:
            finite = frame[np.isfinite(frame)]
            low = float(finite.min()) if finite.size else 0.0
            high = float(finite.max()) if finite.size else 1.0
            frame = np.rint(np.clip((frame - low) / max(high - low, 1.0), 0, 1) * 255).astype(np.uint8)
        mode = "RGBA" if frame.shape[-1] == 4 else "RGB"
        image = Image.fromarray(frame, mode=mode)
    else:
        if frame.ndim != 2:
            raise DicomPixelDecodeError(
                "Unsupported decoded grayscale pixel shape",
                details={"shape": list(frame.shape)},
            )
        rendered = _to_uint8_grayscale(
            frame,
            dataset,
            window_center=window_center,
            window_width=window_width,
        )
        image = Image.fromarray(rendered, mode="L")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def render_instance_preview(
    path: str,
    frame_index: int = 0,
    window_center: float | None = None,
    window_width: float | None = None,
) -> bytes:
    dataset = read_dataset(path, stop_before_pixels=False)
    return render_dataset_preview(
        dataset,
        frame_index=frame_index,
        window_center=window_center,
        window_width=window_width,
        source_path=path,
    )


__all__ = ["render_dataset_preview", "render_instance_preview"]
