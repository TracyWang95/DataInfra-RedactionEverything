"""Image encoding, model-response JSON parsing, and coordinate conversion.

Pure helpers split out of ``locate_grounding`` for single-responsibility: turn
image bytes into the JPEG data-URL the chat model wants, pull the JSON payload
back out of the model's text answer, and normalize/clamp boxes into
page-relative (x, y, w, h). Behavior is verbatim.
"""
from __future__ import annotations

import base64
import io
import json
import re
from typing import Any

from PIL import Image, ImageOps

from app.core.config import settings

# JPEG encode quality for the image sent to the chat model
_JPEG_QUALITY = 92
# Slack multiplier deciding whether boxes are normalized (0..coord) vs absolute pixels
_COORD_MODE_TOLERANCE = 1.05


def _json_endpoint(base_url: str, suffix: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/{suffix.lstrip('/')}"
    return f"{base}/v1/{suffix.lstrip('/')}"


def _extract_json_payload(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {"objects": []}
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", raw, re.S)
        if not match:
            return {"objects": [], "raw_response": text}
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return {"objects": [], "raw_response": text}
    if isinstance(data, list):
        return {"objects": data}
    if isinstance(data, dict) and isinstance(data.get("objects"), list):
        return data
    return {"objects": [], "raw_response": text}


def _image_data_url(image_data: bytes) -> str:
    return f"data:image/jpeg;base64,{base64.b64encode(image_data).decode('ascii')}"


def _prepare_jpeg(image_data: bytes, max_side: int) -> tuple[bytes, tuple[int, int]]:
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_data))).convert("RGB")
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    encoded = io.BytesIO()
    image.save(encoded, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return encoded.getvalue(), image.size


def _clamp_box(x: float, y: float, width: float, height: float) -> tuple[float, float, float, float] | None:
    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    width = max(0.0, min(1.0 - x, width))
    height = max(0.0, min(1.0 - y, height))
    if width <= 0.0 or height <= 0.0:
        return None
    return x, y, width, height


def _normalize_box(raw_box: Any, width: int, height: int) -> tuple[float, float, float, float] | None:
    if not isinstance(raw_box, list | tuple) or len(raw_box) != 4:
        return None
    try:
        x1, y1, x2, y2 = [float(value) for value in raw_box]
    except (TypeError, ValueError):
        return None
    coord = max(1.0, float(settings.VISUAL_FEATURES_COORD_MODE))
    if max(x1, y1, x2, y2) <= coord * _COORD_MODE_TOLERANCE:
        x1, x2 = x1 / coord * width, x2 / coord * width
        y1, y2 = y1 / coord * height, y2 / coord * height
    x1, x2 = sorted((max(0.0, min(float(width), x1)), max(0.0, min(float(width), x2))))
    y1, y2 = sorted((max(0.0, min(float(height), y1)), max(0.0, min(float(height), y2))))
    if x2 <= x1 or y2 <= y1:
        return None  # degenerate (non-positive area); trust LA for everything else
    return x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height
