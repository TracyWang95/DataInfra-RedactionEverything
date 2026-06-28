from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image, ImageOps

from app.core.config import settings
from app.core.retry import RETRYABLE_HTTPX, retry_async
from app.core.visual_feature_categories import (
    DEFAULT_VISUAL_FEATURE_SLUGS,
    SLUG_TO_NAME_ZH,
    filter_visual_feature_slugs,
    is_visual_feature_slug,
    normalize_visual_slug,
)
from app.models.schemas import BoundingBox
from app.services import model_config_service

logger = logging.getLogger(__name__)

# JPEG encode quality for the image sent to the chat model
_JPEG_QUALITY = 92
# Smallest allowed longest-side (px) when downscaling the chat request image
_MIN_IMAGE_SIDE = 256
# Fallback longest-side cap (px) when no setting is configured
_DEFAULT_MAX_IMAGE_SIDE = 2048
# Slack multiplier deciding whether boxes are normalized (0..coord) vs absolute pixels
_COORD_MODE_TOLERANCE = 1.05
# Retry budget / base backoff (s) for the detect HTTP call
_DETECT_MAX_RETRIES = 2
_DETECT_BASE_DELAY = 1.0
# Fallback max-new-tokens cap when no setting is configured
_DEFAULT_MAX_NEW_TOKENS = 8192
# Sampling defaults / caps for the chat request
_DEFAULT_TEMPERATURE = 0.1
_MAX_TEMPERATURE = 0.2
_DEFAULT_TOP_P = 0.6
# Default confidence when the model omits one
_DEFAULT_DETECT_CONFIDENCE = 0.8
_DEFAULT_CHECKLIST_CONFIDENCE = 0.82


@dataclass
class LocateGroundingTimings:
    model: int = 0
    prepare: int = 0
    draw: int = 0
    total: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "model": self.model,
            "prepare": self.prepare,
            "draw": self.draw,
            "total": self.total,
        }


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


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


def _type_rules(type_config: Any) -> list[str]:
    checklist = getattr(type_config, "checklist", None) or []
    rules: list[str] = []
    for item in checklist:
        if isinstance(item, dict):
            for key in ("rule", "positive_prompt"):
                value = str(item.get(key) or "").strip()
                if value:
                    rules.append(value)
        else:
            for key in ("rule", "positive_prompt"):
                value = str(getattr(item, key, "") or "").strip()
                if value:
                    rules.append(value)
    if not rules:
        rules = [str(rule).strip() for rule in (getattr(type_config, "rules", None) or []) if str(rule).strip()]
    description = str(getattr(type_config, "description", "") or "").strip()
    if description:
        rules.append(description)
    name = str(getattr(type_config, "name", "") or getattr(type_config, "id", "")).strip()
    if name:
        rules.append(name)
    return list(dict.fromkeys(rules))


def _checklist_prompt(type_configs: list[Any]) -> str:
    lines = [
        "Task: locate visual features in this document image.",
        "Use actual visible visual evidence only; do not infer from labels, blank fields, table lines, or surrounding text.",
        "Return JSON only.",
        'Schema: {"objects":[{"type_id":"<allowed type_id>","label":"<label>","box_2d":[xmin,ymin,xmax,ymax],"confidence":0.8,"rule_matched":"<type_id>#<rule_index>","text":""}]}',
        f"Coordinates are integers in 0..{settings.VISUAL_FEATURES_COORD_MODE}, origin top-left.",
        "Use one tight box per visible instance.",
        f"Allowed type_id: {', '.join(str(getattr(item, 'id', '')).strip() for item in type_configs)}",
        "Configured visual checklist:",
    ]
    for item in type_configs:
        type_id = str(getattr(item, "id", "")).strip()
        name = str(getattr(item, "name", "") or type_id).strip()
        lines.append(f"- type_id={type_id}; name={name}")
        for index, rule in enumerate(_type_rules(item), start=1):
            lines.append(f"  {index}. Check: {rule}")
        negative = str(getattr(item, "negative_prompt", "") or "").strip()
        if bool(getattr(item, "negative_prompt_enabled", False)) and negative:
            lines.append(f"  Exclude: {negative}")
    lines.append('If none, return {"objects":[]}.')
    return "\n".join(lines)


class LocateAnythingGroundingService:
    """Single adapter for all visual grounding boxes produced by LocateAnything."""

    def __init__(self) -> None:
        self.last_raw_response: str | None = None

    async def detect_categories(
        self,
        image_data: bytes,
        page: int,
        pipeline_types: list[Any] | None,
    ) -> tuple[list[BoundingBox], dict[str, int]]:
        total_start = time.perf_counter()
        timings = LocateGroundingTimings()
        slugs = None if pipeline_types is None else [str(getattr(item, "id", item)) for item in pipeline_types]
        model_slugs = filter_visual_feature_slugs(slugs if slugs is not None else list(DEFAULT_VISUAL_FEATURE_SLUGS))
        if model_slugs is not None and not model_slugs:
            timings.total = _elapsed_ms(total_start)
            logger.info("LocateAnything visual category stage skipped: no supported fixed visual categories")
            return [], timings.as_dict()

        model_start = time.perf_counter()
        # Parallel inference across both GPUs: fan out one request per category
        # so the load balancer round-robins them onto GPU0/GPU1 concurrently.
        # Each LA call then does exactly one MoonViT encode + one generation, so
        # the default {signature, official_seal} pair finishes in ~one category's
        # time (~2s) instead of two sequential passes (~4s) on a single card.
        if model_slugs is not None and len(model_slugs) > 1:
            results = await asyncio.gather(
                *[self._post_detect(image_data, [slug]) for slug in model_slugs],
                return_exceptions=True,
            )
            raw_boxes = []
            for slug, res in zip(model_slugs, results):
                if isinstance(res, BaseException):
                    logger.warning("LocateAnything category %s failed, skipping: %s", slug, res)
                    continue
                raw_boxes.extend(res)
        else:
            raw_boxes = await self._post_detect(image_data, model_slugs)
        timings.model = _elapsed_ms(model_start)

        boxes: list[BoundingBox] = []
        for index, raw in enumerate(raw_boxes):
            slug = normalize_visual_slug(raw.get("category", ""))
            if not is_visual_feature_slug(slug):
                logger.debug("Skipping unsupported LocateAnything category: %s", raw.get("category"))
                continue
            try:
                normalized = _clamp_box(
                    float(raw.get("x") or 0),
                    float(raw.get("y") or 0),
                    float(raw.get("width") or 0),
                    float(raw.get("height") or 0),
                )
            except (TypeError, ValueError):
                normalized = None
            if normalized is None:
                continue
            x, y, width, height = normalized
            boxes.append(
                BoundingBox(
                    id=f"locate_{index}_{uuid.uuid4().hex[:8]}",
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    type=slug,
                    text=SLUG_TO_NAME_ZH.get(slug, slug),
                    page=page,
                    confidence=float(raw.get("confidence", _DEFAULT_DETECT_CONFIDENCE) or _DEFAULT_DETECT_CONFIDENCE),
                    source="visual_features",
                    source_detail="locate_anything:detect",
                    evidence_source="visual_feature_model",
                )
            )
        timings.total = _elapsed_ms(total_start)
        logger.info("LocateAnything fixed visual stage parsed %d boxes", len(boxes))
        return boxes, timings.as_dict()

    async def detect_checklist(
        self,
        image_data: bytes,
        page: int,
        type_configs: list[Any],
        *,
        timeout: float | None = None,
    ) -> tuple[list[BoundingBox], dict[str, int]]:
        total_start = time.perf_counter()
        timings = LocateGroundingTimings()
        if not type_configs:
            timings.total = _elapsed_ms(total_start)
            return [], timings.as_dict()

        prepare_start = time.perf_counter()
        max_side = max(
            _MIN_IMAGE_SIDE,
            int(
                getattr(
                    settings,
                    "VISUAL_FEATURES_SIGNATURE_MAX_IMAGE_SIDE",
                    getattr(settings, "VISUAL_FEATURES_MAX_IMAGE_SIDE", _DEFAULT_MAX_IMAGE_SIDE),
                )
                or _DEFAULT_MAX_IMAGE_SIDE
            ),
        )
        request_image, (width, height) = _prepare_jpeg(image_data, max_side)
        timings.prepare = _elapsed_ms(prepare_start)

        model_start = time.perf_counter()
        content = await self._post_chat(request_image, _checklist_prompt(type_configs), timeout=timeout)
        timings.model = _elapsed_ms(model_start)
        self.last_raw_response = content

        parsed = _extract_json_payload(content)
        boxes = self._objects_to_boxes(parsed.get("objects") or [], type_configs, width, height, page)
        timings.total = _elapsed_ms(total_start)
        logger.info("LocateAnything checklist visual stage parsed %d boxes", len(boxes))
        return boxes, timings.as_dict()

    async def _post_detect(self, image_data: bytes, categories: list[str] | None) -> list[dict[str, Any]]:
        base_url = model_config_service.get_visual_features_base_url()
        url = f"{base_url}/detect"
        body: dict[str, Any] = {
            "image_base64": base64.b64encode(image_data).decode("utf-8"),
            "conf": settings.VISUAL_FEATURES_CONF,
        }
        if categories is not None:
            body["categories"] = categories

        async def request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=settings.VISUAL_FEATURES_TIMEOUT, trust_env=False) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                return response

        response = await retry_async(
            request,
            max_retries=_DETECT_MAX_RETRIES,
            base_delay=_DETECT_BASE_DELAY,
            retryable_exceptions=RETRYABLE_HTTPX,
        )
        data = response.json()
        return list(data.get("boxes") or [])

    async def _post_chat(self, image_data: bytes, prompt: str, *, timeout: float | None) -> str:
        config = model_config_service.get_visual_features_config()
        if not config:
            logger.info("LocateAnything checklist stage skipped: visual feature service is disabled or missing")
            return '{"objects":[]}'
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        max_tokens = max(
            int(getattr(settings, "LOCATE_ANYTHING_MAX_NEW_TOKENS", _DEFAULT_MAX_NEW_TOKENS) or _DEFAULT_MAX_NEW_TOKENS),
            int(config.max_tokens or 0),
        )
        payload = {
            "model": config.model_name or settings.VISUAL_FEATURES_MODEL_NAME,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _image_data_url(image_data)}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "temperature": min(float(config.temperature or _DEFAULT_TEMPERATURE), _MAX_TEMPERATURE),
            "top_p": float(config.top_p or _DEFAULT_TOP_P),
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "thinking": {"type": "disabled"},
            "enable_thinking": False,
        }
        url = _json_endpoint(config.base_url or settings.VISUAL_FEATURES_BASE_URL, "chat/completions")
        request_timeout = float(timeout if timeout is not None else settings.VISUAL_FEATURES_TIMEOUT)

        async def request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=request_timeout, trust_env=False) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return response

        response = await retry_async(
            request,
            max_retries=_DETECT_MAX_RETRIES,
            base_delay=_DETECT_BASE_DELAY,
            retryable_exceptions=RETRYABLE_HTTPX,
        )
        data = response.json()
        return str(data.get("choices", [{}])[0].get("message", {}).get("content", ""))

    def _objects_to_boxes(
        self,
        objects: list[Any],
        type_configs: list[Any],
        width: int,
        height: int,
        page: int,
    ) -> list[BoundingBox]:
        by_id = {str(getattr(item, "id", "")).strip(): item for item in type_configs}
        name_to_id = {
            str(getattr(item, "name", "") or "").strip(): str(getattr(item, "id", "")).strip()
            for item in type_configs
        }
        boxes: list[BoundingBox] = []
        for index, obj in enumerate(objects):
            if not isinstance(obj, dict):
                continue
            type_id = str(obj.get("type_id") or "").strip()
            if type_id not in by_id:
                type_id = name_to_id.get(str(obj.get("label") or "").strip(), "")
            if type_id not in by_id and len(type_configs) == 1:
                type_id = str(getattr(type_configs[0], "id", "")).strip()
            if type_id not in by_id:
                continue
            normalized = _normalize_box(obj.get("box_2d"), width, height)
            if normalized is None:
                continue
            x, y, box_width, box_height = normalized
            type_config = by_id[type_id]
            label = str(getattr(type_config, "name", "") or obj.get("label") or type_id)
            boxes.append(
                BoundingBox(
                    id=f"locate_visual_{index}_{uuid.uuid4().hex[:8]}",
                    x=x,
                    y=y,
                    width=box_width,
                    height=box_height,
                    type=type_id,
                    text=str(obj.get("text") or label).strip() or label,
                    page=page,
                    confidence=max(0.0, min(1.0, float(obj.get("confidence", _DEFAULT_CHECKLIST_CONFIDENCE) or _DEFAULT_CHECKLIST_CONFIDENCE))),
                    source="visual_features",
                    source_detail=f"locate_anything:{obj.get('rule_matched') or 'checklist'}",
                    evidence_source="visual_feature_model",
                )
            )
        return boxes

