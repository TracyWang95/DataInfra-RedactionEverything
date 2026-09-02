"""GPU OCR + HaS adapter for burned-in DICOM pixel PHI.

The DICOM core is intentionally synchronous, while the shared OCR/HaS
pipeline is asynchronous.  This adapter keeps that boundary in one place and
returns only pixel coordinates.  Recognised text is deliberately discarded so
it cannot be serialised into a DICOM report or API response.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Any, TypeVar

import numpy as np
from PIL import Image
from pydicom.dataset import Dataset

from .errors import DicomPixelDecodeError
from .pixel import PixelDetectorResult, PixelRegion
from .render import _to_uint8_grayscale

_T = TypeVar("_T")

_DETECTOR_NAME = "PaddleOCR+HaS+DICOM-fail-safe"
_DETECTOR_VERSION = "1"

# DICOM images with an unknown BurnedInAnnotation value get a conservative
# label-line fallback in addition to semantic HaS findings.  YES is stricter:
# every OCR block is considered identifying material.
_DICOM_PHI_LABEL_RE = re.compile(
    r"(?:"
    r"\bPATIENT(?:\s+(?:NAME|ID|IDENTIFIER))?\b|"
    r"\b(?:PT|PAT)\s*(?:NAME|ID)\b|"
    r"\bNAME\b|"
    r"\bMRN\b|"
    r"\bMEDICAL\s+RECORD(?:\s+(?:NO|NUMBER|ID))?\b|"
    r"\b(?:PATIENT\s+)?ID\b|"
    r"\bDOB\b|"
    r"\bDATE\s+OF\s+BIRTH\b|"
    r"\bBIRTH(?:\s*DATE)?\b|"
    r"\bACCESSION(?:\s+(?:NO|NUMBER|ID))?\b|"
    r"\bHOSPITAL\s+(?:NO|NUMBER|ID)\b|"
    r"\bCASE\s+(?:NO|NUMBER|ID)\b|"
    r"患者|姓名|病历号|病歷號|病案号|病案號|住院号|住院號|就诊号|就診號|"
    r"门诊号|門診號|检查号|檢查號|出生日期|身份证|身份證"
    r")",
    re.IGNORECASE,
)


def _env_enabled(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _run_async(factory: Callable[[], Awaitable[_T]]) -> _T:
    """Run one coroutine from synchronous core code.

    The HTTP endpoint normally moves the whole preflight into Starlette's
    worker pool.  The fallback thread here also makes direct library use safe
    when a caller happens to be inside an already-running event loop.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="dicom-pixel-ocr") as executor:
        return executor.submit(lambda: asyncio.run(factory())).result()


def _render_frame_png(frame: np.ndarray, dataset: Dataset) -> bytes:
    """Render a decoded DICOM frame to the same-size PNG used by OCR."""

    pixels = np.asarray(frame)
    samples = max(1, int(dataset.get("SamplesPerPixel", 1) or 1))
    if samples > 1:
        if pixels.ndim != 3 or pixels.shape[-1] not in {3, 4}:
            raise DicomPixelDecodeError(
                "Unsupported decoded color pixel shape for DICOM OCR",
                details={"shape": list(pixels.shape), "samples_per_pixel": samples},
            )
        if pixels.dtype != np.uint8:
            values = pixels.astype(np.float64, copy=False)
            finite = values[np.isfinite(values)]
            if finite.size == 0:
                raise DicomPixelDecodeError("Decoded DICOM frame contains no finite pixel values")
            low = float(finite.min())
            high = float(finite.max())
            values = np.clip((values - low) / max(high - low, 1.0), 0.0, 1.0)
            pixels = np.rint(values * 255.0).astype(np.uint8)
        mode = "RGBA" if pixels.shape[-1] == 4 else "RGB"
        image = Image.fromarray(pixels, mode=mode)
    else:
        if pixels.ndim != 2:
            raise DicomPixelDecodeError(
                "Unsupported decoded grayscale pixel shape for DICOM OCR",
                details={"shape": list(pixels.shape)},
            )
        rendered = _to_uint8_grayscale(
            pixels,
            dataset,
            window_center=None,
            window_width=None,
        )
        image = Image.fromarray(rendered, mode="L")

    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return min(1.0, max(0.0, result))


def _pixel_region(candidate: Any, *, frame_index: int, width: int, height: int) -> PixelRegion:
    try:
        left = int(candidate.left)
        top = int(candidate.top)
        candidate_width = int(candidate.width)
        candidate_height = int(candidate.height)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError("DICOM OCR returned a region without valid pixel coordinates") from exc

    if candidate_width <= 0 or candidate_height <= 0:
        raise RuntimeError("DICOM OCR returned a non-positive pixel region")
    right = left + candidate_width
    bottom = top + candidate_height
    x1 = max(0, left)
    y1 = max(0, top)
    x2 = min(width, right)
    y2 = min(height, bottom)
    if x2 <= x1 or y2 <= y1:
        raise RuntimeError("DICOM OCR returned a pixel region outside the rendered frame")
    return PixelRegion(
        frame_index=frame_index,
        x=x1,
        y=y1,
        width=x2 - x1,
        height=y2 - y1,
        # Do not retain OCR/HaS source text in the core result.  Coordinates
        # and confidence are sufficient for masking and validation.
        text="",
        confidence=_confidence(getattr(candidate, "confidence", None)),
    )


def _intersection_area(first: PixelRegion, second: PixelRegion) -> int:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    return max(0, right - left) * max(0, bottom - top)


def _append_without_duplicate(regions: list[PixelRegion], candidate: PixelRegion) -> None:
    candidate_area = candidate.width * candidate.height
    for existing in regions:
        if existing.frame_index != candidate.frame_index:
            continue
        intersection = _intersection_area(existing, candidate)
        smaller_area = min(existing.width * existing.height, candidate_area)
        if smaller_area and intersection / smaller_area >= 0.9:
            # Fail-safe OCR blocks are appended first.  When a narrower HaS
            # entity is inside the same block, keeping the block masks at
            # least as much and avoids duplicate report counts.
            return
    regions.append(candidate)


def _is_dicom_phi_label(text: Any) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    return bool(_DICOM_PHI_LABEL_RE.search(text))


class DicomOCRPixelDetector:
    """Synchronous ``BurnedInPixelDetector`` backed by GPU OCR + HaS."""

    def __init__(self, service: Any, *, verify_backends: bool = True) -> None:
        self._service = service
        self._verify_backends = verify_backends

    def _ensure_backends_online(self) -> None:
        if not self._verify_backends:
            return
        ocr_client = getattr(self._service, "_ocr_service", None)
        has_client = getattr(self._service, "_has_client", None)
        if ocr_client is None or has_client is None:
            raise RuntimeError("DICOM pixel OCR/HaS backend is not configured")
        try:
            ocr_online = bool(ocr_client.is_available())
            has_online = bool(has_client.is_available())
        except Exception as exc:
            raise RuntimeError("DICOM pixel OCR/HaS backend health check failed") from exc
        if not ocr_online or not has_online:
            raise RuntimeError("DICOM pixel OCR/HaS backend is offline")

    async def _detect_frames(
        self,
        dataset: Dataset,
        frames: list[np.ndarray],
    ) -> list[PixelRegion]:
        burned_in = str(dataset.get("BurnedInAnnotation", "")).upper().strip()
        output: list[PixelRegion] = []
        for frame_index, frame in enumerate(frames):
            pixels = np.asarray(frame)
            if pixels.ndim < 2:
                raise DicomPixelDecodeError(
                    "Decoded DICOM frame has no two-dimensional pixel plane",
                    details={"shape": list(pixels.shape)},
                )
            height, width = int(pixels.shape[0]), int(pixels.shape[1])
            image_bytes = _render_frame_png(pixels, dataset)
            ocr_blocks: list[Any] = []
            detected = await self._service.detect_and_draw(
                image_bytes,
                vision_types=None,
                draw_result=False,
                blocks_out=ocr_blocks,
            )
            if not isinstance(detected, tuple) or len(detected) != 2:
                raise RuntimeError("DICOM OCR/HaS returned an invalid detection result")
            semantic_regions = detected[0]
            if semantic_regions is None:
                semantic_regions = []
            if not isinstance(semantic_regions, list):
                raise RuntimeError("DICOM OCR/HaS returned invalid sensitive regions")

            if burned_in == "YES":
                fallback_blocks = ocr_blocks
            elif burned_in != "NO":
                fallback_blocks = [block for block in ocr_blocks if _is_dicom_phi_label(getattr(block, "text", ""))]
            else:
                fallback_blocks = []

            # Conservative DICOM fallbacks are first so overlapping narrower
            # semantic regions cannot shrink the area selected for masking.
            for candidate in [*fallback_blocks, *semantic_regions]:
                region = _pixel_region(
                    candidate,
                    frame_index=frame_index,
                    width=width,
                    height=height,
                )
                _append_without_duplicate(output, region)
        return output

    def detect(self, dataset: Dataset, frames: list[np.ndarray]) -> PixelDetectorResult:
        self._ensure_backends_online()
        regions = _run_async(lambda: self._detect_frames(dataset, frames))
        return PixelDetectorResult(
            regions=regions,
            detector_name=_DETECTOR_NAME,
            detector_version=_DETECTOR_VERSION,
        )


def get_dicom_ocr_pixel_detector() -> DicomOCRPixelDetector:
    """Build the production detector around the application's shared service."""

    from app.services.ocr_has_vision_service import get_ocr_has_vision_service

    return DicomOCRPixelDetector(
        get_ocr_has_vision_service(),
        verify_backends=_env_enabled("DICOM_PIXEL_OCR_HEALTHCHECK", default=True),
    )


__all__ = ["DicomOCRPixelDetector", "get_dicom_ocr_pixel_detector"]
