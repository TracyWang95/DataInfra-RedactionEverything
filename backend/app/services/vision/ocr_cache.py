"""OCR output caching, in-flight dedupe registries and stage-metric bookkeeping.

Split out of ocr_pipeline.py (which stays the public facade). All module-level
mutable state (OCR text-block cache, OCR-output in-flight registry, HaS text
NER in-flight registry and their locks) lives here exactly once, together with
the functions that own it, the output clone helpers and the stage-metric
recorders.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from PIL import Image

from app.core.config import settings
from app.services.ocr_has_vision_service import OCRTextBlock, SensitiveRegion
from app.services.vision.ocr_tuning import _HAS_NEGATIVE_HEALTH_TTL_SEC

logger = logging.getLogger(__name__)


_OCR_TEXT_BLOCK_CACHE_LOCK = threading.Lock()
_OCR_TEXT_BLOCK_CACHE: OrderedDict[
    tuple[Any, ...],
    tuple[float, list[OCRTextBlock], list[SensitiveRegion]],
] = OrderedDict()
_OCR_TEXT_BLOCK_INFLIGHT_LOCK = threading.Lock()
_OCR_TEXT_BLOCK_INFLIGHT: dict[tuple[Any, ...], _OcrOutputInflight] = {}
_HAS_TEXT_NER_INFLIGHT: dict[tuple[Any, ...], asyncio.Future] = {}
_HAS_TEXT_NER_INFLIGHT_LOOP: asyncio.AbstractEventLoop | None = None


class _OcrOutputInflight:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: tuple[list[OCRTextBlock], list[SensitiveRegion]] | None = None
        self.error: BaseException | None = None


def _copy_has_text_ner_result(
    result: Any,
) -> Any:
    if not isinstance(result, dict):
        return None
    return {
        key: list(value) if isinstance(value, list) else value
        for key, value in result.items()
    }


def _has_text_ner_inflight_key(
    has_client: Any,
    text_content: str,
    chinese_types: list[str],
) -> tuple[Any, ...]:
    identity: Any = type(has_client).__qualname__
    effective_base_url = getattr(has_client, "_effective_base_url", None)
    if callable(effective_base_url):
        try:
            identity = effective_base_url()
        except Exception:
            logger.debug("HaS client identity lookup failed", exc_info=True)
    else:
        identity = getattr(has_client, "base_url", identity)
    digest = hashlib.sha256(text_content.encode("utf-8", errors="ignore")).hexdigest()
    return (identity, tuple(chinese_types), digest)


def _begin_has_text_ner_inflight(
    key: tuple[Any, ...],
) -> tuple[bool, asyncio.Future]:
    global _HAS_TEXT_NER_INFLIGHT_LOOP
    loop = asyncio.get_running_loop()
    if _HAS_TEXT_NER_INFLIGHT_LOOP is not loop:
        _HAS_TEXT_NER_INFLIGHT.clear()
        _HAS_TEXT_NER_INFLIGHT_LOOP = loop

    future = _HAS_TEXT_NER_INFLIGHT.get(key)
    if future is not None:
        return False, future

    future = loop.create_future()
    _HAS_TEXT_NER_INFLIGHT[key] = future
    return True, future


def _finish_has_text_ner_inflight(
    key: tuple[Any, ...],
    future: asyncio.Future,
    result: Any,
) -> None:
    if _HAS_TEXT_NER_INFLIGHT.get(key) is future:
        _HAS_TEXT_NER_INFLIGHT.pop(key, None)
    if not future.done():
        future.set_result(_copy_has_text_ner_result(result))


def _has_recent_negative_health(has_client: Any) -> bool:
    checked_at = float(getattr(has_client, "_health_checked_at", 0.0) or 0.0)
    if checked_at <= 0:
        return False
    if bool(getattr(has_client, "_health_ready", False)):
        return False
    return time.monotonic() - checked_at < _HAS_NEGATIVE_HEALTH_TTL_SEC


def _get_cached_has_text_ner(
    has_client: Any,
    text_content: str,
    chinese_types: list[str],
) -> dict[str, list[str]] | None:
    getter = getattr(has_client, "get_cached_ner", None)
    if not callable(getter):
        return None
    try:
        cached = getter(text_content, chinese_types)
    except Exception:
        logger.debug("HaS NER cache lookup failed", exc_info=True)
        return None
    return cached if isinstance(cached, dict) else None


def _clone_text_block(block: OCRTextBlock) -> OCRTextBlock:
    return OCRTextBlock(
        text=block.text,
        polygon=[[float(point[0]), float(point[1])] for point in block.polygon],
        confidence=float(block.confidence),
        chars=[dict(char_box) for char_box in block.chars],
    )


def _clone_sensitive_region(region: SensitiveRegion) -> SensitiveRegion:
    return SensitiveRegion(
        text=region.text,
        entity_type=region.entity_type,
        left=int(region.left),
        top=int(region.top),
        width=int(region.width),
        height=int(region.height),
        confidence=float(region.confidence),
        source=region.source,
        color=tuple(region.color),
    )


def _clone_ocr_output(
    blocks: list[OCRTextBlock],
    visual_regions: list[SensitiveRegion],
) -> tuple[list[OCRTextBlock], list[SensitiveRegion]]:
    return (
        [_clone_text_block(block) for block in blocks],
        [_clone_sensitive_region(region) for region in visual_regions],
    )



def _record_ocr_cache_stage(
    stage_status: dict[str, Any] | None,
    stage: str,
    status: str,
) -> None:
    if stage_status is None:
        return
    stage_status[f"ocr_{stage}_cache_status"] = status
    if status == "hit":
        stage_status[f"ocr_{stage}_cache_hit"] = True
        stage_status["ocr_cache_hits"] = int(stage_status.get("ocr_cache_hits", 0) or 0) + 1
    elif status == "miss":
        stage_status[f"ocr_{stage}_cache_hit"] = False
        stage_status["ocr_cache_misses"] = int(stage_status.get("ocr_cache_misses", 0) or 0) + 1


def _record_ocr_stage_duration(
    stage_status: dict[str, Any] | None,
    stage: str,
    started_at: float,
) -> None:
    if stage_status is None:
        return
    key = f"ocr_{stage}_ms"
    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
    stage_status[key] = int(stage_status.get(key, 0) or 0) + elapsed_ms


def _record_has_text_metric(
    stage_status: dict[str, Any] | None,
    key: str,
    value: Any,
) -> None:
    if stage_status is not None:
        stage_status[key] = value


def _add_has_text_duration(
    stage_status: dict[str, Any] | None,
    key: str,
    elapsed_ms: int,
) -> None:
    if stage_status is None:
        return
    stage_status[key] = int(stage_status.get(key, 0) or 0) + max(0, int(elapsed_ms))


def _ocr_cache_enabled() -> bool:
    return settings.OCR_TEXT_BLOCK_CACHE_TTL_SEC > 0 and settings.OCR_TEXT_BLOCK_CACHE_MAX_ITEMS > 0


def _ocr_service_cache_identity(ocr_service: Any) -> tuple[str, str, int]:
    base_url = str(getattr(ocr_service, "base_url", "") or "")
    service_name = f"{type(ocr_service).__module__}.{type(ocr_service).__qualname__}"
    return base_url, service_name, id(ocr_service)


def _image_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _ocr_cache_key(
    stage: str,
    image: Image.Image,
    image_bytes: bytes,
    ocr_service: Any,
) -> tuple[Any, ...]:
    config_bits: tuple[Any, ...]
    if stage == "vl":
        config_bits = (int(settings.OCR_MAX_NEW_TOKENS),)
    else:
        config_bits = ()
    return (
        stage,
        hashlib.sha256(image_bytes).hexdigest(),
        image.width,
        image.height,
        image.mode,
        _ocr_service_cache_identity(ocr_service),
        config_bits,
    )


def _get_cached_ocr_output(
    key: tuple[Any, ...],
    stage: str,
    stage_status: dict[str, Any] | None,
) -> tuple[list[OCRTextBlock], list[SensitiveRegion]] | None:
    if not _ocr_cache_enabled():
        _record_ocr_cache_stage(stage_status, stage, "disabled")
        return None

    now = time.monotonic()
    ttl = float(settings.OCR_TEXT_BLOCK_CACHE_TTL_SEC)
    with _OCR_TEXT_BLOCK_CACHE_LOCK:
        cached = _OCR_TEXT_BLOCK_CACHE.get(key)
        if cached is None:
            _record_ocr_cache_stage(stage_status, stage, "miss")
            return None
        stored_at, blocks, visual_regions = cached
        if now - stored_at > ttl:
            _OCR_TEXT_BLOCK_CACHE.pop(key, None)
            _record_ocr_cache_stage(stage_status, stage, "miss")
            return None
        _OCR_TEXT_BLOCK_CACHE.move_to_end(key)
        _record_ocr_cache_stage(stage_status, stage, "hit")
        return _clone_ocr_output(blocks, visual_regions)


def _set_cached_ocr_output(
    key: tuple[Any, ...],
    blocks: list[OCRTextBlock],
    visual_regions: list[SensitiveRegion],
) -> None:
    if not _ocr_cache_enabled():
        return

    max_items = int(settings.OCR_TEXT_BLOCK_CACHE_MAX_ITEMS)
    with _OCR_TEXT_BLOCK_CACHE_LOCK:
        cached_blocks, cached_regions = _clone_ocr_output(blocks, visual_regions)
        _OCR_TEXT_BLOCK_CACHE[key] = (time.monotonic(), cached_blocks, cached_regions)
        _OCR_TEXT_BLOCK_CACHE.move_to_end(key)
        while len(_OCR_TEXT_BLOCK_CACHE) > max_items:
            _OCR_TEXT_BLOCK_CACHE.popitem(last=False)


def _begin_ocr_output_inflight(
    key: tuple[Any, ...],
) -> tuple[bool, _OcrOutputInflight]:
    with _OCR_TEXT_BLOCK_INFLIGHT_LOCK:
        inflight = _OCR_TEXT_BLOCK_INFLIGHT.get(key)
        if inflight is not None:
            return False, inflight
        inflight = _OcrOutputInflight()
        _OCR_TEXT_BLOCK_INFLIGHT[key] = inflight
        return True, inflight


def _finish_ocr_output_inflight(
    key: tuple[Any, ...],
    inflight: _OcrOutputInflight,
    result: tuple[list[OCRTextBlock], list[SensitiveRegion]] | None,
    error: BaseException | None = None,
) -> None:
    with _OCR_TEXT_BLOCK_INFLIGHT_LOCK:
        if _OCR_TEXT_BLOCK_INFLIGHT.get(key) is inflight:
            _OCR_TEXT_BLOCK_INFLIGHT.pop(key, None)
    if result is not None:
        inflight.result = _clone_ocr_output(*result)
    inflight.error = error
    inflight.event.set()


def _wait_for_ocr_output_inflight(
    inflight: _OcrOutputInflight,
) -> tuple[list[OCRTextBlock], list[SensitiveRegion]]:
    # 兜底超时：owner 正常路径总会 set event；若 owner 异常退出未触发 finish，
    # 避免同图请求永久挂死。超时按 inflight 失败处理。
    timeout = float(settings.OCR_TIMEOUT) + 30.0
    if not inflight.event.wait(timeout):
        raise TimeoutError(
            f"等待同图 OCR in-flight 结果超时（{timeout:.0f}s），按失败处理"
        )
    if inflight.error is not None:
        raise inflight.error
    if inflight.result is None:
        return [], []
    return _clone_ocr_output(*inflight.result)
