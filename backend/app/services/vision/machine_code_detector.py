"""Deterministic machine-code (QR / barcode) detector.

LocateAnything is the primary model path for machine codes; its recall on very
small codes (e.g. a corner QR a few dozen pixels wide) is borderline. This
module supplements it with cv2's decoders: a region is reported only when the
code's payload actually DECODES. Decode success is the strictest possible
format check, so this path has zero false positives by construction — no
pixel thresholds, no area windows, no shape rules.
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageOps

try:
    import cv2
    import numpy as np

    _VISION_DEPS_MISSING = False
except Exception:
    cv2 = None
    np = None
    _VISION_DEPS_MISSING = True

QR_CODE_SLUG = "qr_code"
BARCODE_SLUG = "barcode"

# A decoded payload proves the code exists and the box is exact.
_DECODED_CONFIDENCE = 1.0


@dataclass(frozen=True)
class MachineCodeRegion:
    x: float
    y: float
    width: float
    height: float
    code_type: str  # QR_CODE_SLUG | BARCODE_SLUG
    text: str
    confidence: float = _DECODED_CONFIDENCE


def _vision_deps():
    global cv2, np, _VISION_DEPS_MISSING
    if _VISION_DEPS_MISSING:
        return None
    if cv2 is not None and np is not None:
        return cv2, np
    try:
        import cv2
        import numpy as np
    except Exception:
        _VISION_DEPS_MISSING = True
        return None
    return cv2, np


def detect_machine_code_regions(image: Image.Image) -> list[MachineCodeRegion]:
    """Return normalized boxes for every QR / barcode that fully decodes."""
    deps = _vision_deps()
    if deps is None:
        return []
    cv2, np = deps

    img = ImageOps.exif_transpose(image).convert("RGB")
    width, height = img.size
    if width <= 0 or height <= 0:
        return []
    gray = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
    return [*_decode_qr_codes(gray, width, height), *_decode_barcodes(gray, width, height)]


def _qr_detector():
    # QRCodeDetectorAruco (cv2 >= 4.8) finds small codes the classic finder-pattern
    # pipeline misses; both variants only return text once the payload decodes.
    if hasattr(cv2, "QRCodeDetectorAruco"):
        return cv2.QRCodeDetectorAruco()
    return cv2.QRCodeDetector()


def _decode_qr_codes(gray, width: int, height: int) -> list[MachineCodeRegion]:
    try:
        ok, texts, points, _ = _qr_detector().detectAndDecodeMulti(gray)
    except cv2.error:
        return []
    if not ok or points is None:
        return []
    regions: list[MachineCodeRegion] = []
    for text, quad in zip(texts, points, strict=False):
        # Empty text = detected but NOT decoded (e.g. a decorative QR-look-alike
        # in a synthetic document); only a decoded payload counts as proof.
        if not text:
            continue
        region = _quad_to_region(quad, width, height, QR_CODE_SLUG, str(text))
        if region is not None:
            regions.append(region)
    return regions


def _decode_barcodes(gray, width: int, height: int) -> list[MachineCodeRegion]:
    barcode_module = getattr(cv2, "barcode", None)
    if barcode_module is None:
        return []
    try:
        ok, infos, _types, points = barcode_module.BarcodeDetector().detectAndDecodeWithType(gray)
    except cv2.error:
        return []
    if not ok or points is None:
        return []
    regions: list[MachineCodeRegion] = []
    for text, quad in zip(infos, points, strict=False):
        if not text:
            continue
        region = _quad_to_region(quad, width, height, BARCODE_SLUG, str(text))
        if region is not None:
            regions.append(region)
    return regions


def _quad_to_region(quad, width: int, height: int, code_type: str, text: str) -> MachineCodeRegion | None:
    xs = [float(point[0]) for point in quad]
    ys = [float(point[1]) for point in quad]
    x1 = max(0.0, min(min(xs), float(width)))
    y1 = max(0.0, min(min(ys), float(height)))
    x2 = max(0.0, min(max(xs), float(width)))
    y2 = max(0.0, min(max(ys), float(height)))
    if x2 <= x1 or y2 <= y1:
        return None
    return MachineCodeRegion(
        x=x1 / width,
        y=y1 / height,
        width=(x2 - x1) / width,
        height=(y2 - y1) / height,
        code_type=code_type,
        text=text,
    )
