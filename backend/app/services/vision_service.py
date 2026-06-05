"""Vision recognition service.
视觉识别服务
The runtime combines OCR/HaS semantic regions with LocateAnything visual
feature grounding.
"""
import asyncio
import base64
import inspect
import io
import logging
import os
import time
import uuid
from collections import OrderedDict
from threading import Lock
from types import SimpleNamespace

import httpx
import numpy as np

logger = logging.getLogger(__name__)

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.core.config import settings
from app.core.visual_feature_categories import (
    LOCATE_ANYTHING_VISUAL_SLUGS,
    OCR_FALLBACK_ONLY_VISUAL_SLUGS,
    SLUG_TO_NAME_ZH,
    normalize_visual_slug,
)
from app.models.schemas import BoundingBox, FileType
from app.services.file_parser import FileParser
from app.services.ocr_has_vision_service import get_ocr_has_vision_service
from app.services.vision.ocr_artifact_filter import (
    is_page_edge_ocr_artifact,
    region_has_visible_ink,
)
from app.services.vision.locate_grounding import LocateAnythingGroundingService
from app.services.vision.signature_geometry import signature_stroke_mask

VISUAL_TYPE_LABELS_ZH = {
    **SLUG_TO_NAME_ZH,
}

_PDF_TEXT_LAYER_SPARSE_SKIP_AFTER = 2
_PDF_TEXT_LAYER_SPARSE_CACHE_MAX_ITEMS = 128
_PDF_TEXT_LAYER_SPARSE_LOCK = Lock()
_PDF_TEXT_LAYER_SPARSE_COUNTS: OrderedDict[tuple[str, int, int], int] = OrderedDict()
_PDF_TEXT_LAYER_PROBE_LOCKS: dict[tuple[str, int, int], asyncio.Lock] = {}
_PDF_TEXT_LAYER_PROBE_LOCKS_LOOP: asyncio.AbstractEventLoop | None = None


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


def _normalize_file_type(file_type: FileType | str) -> FileType | str:
    try:
        return FileType(file_type) if isinstance(file_type, str) else file_type
    except ValueError:
        return file_type


def _pdf_text_layer_sparse_key(file_path: str) -> tuple[str, int, int] | None:
    try:
        resolved = os.path.realpath(file_path)
        stat = os.stat(resolved)
        return (resolved, int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        logger.debug("Unable to stat PDF for sparse text-layer cache: %s", file_path, exc_info=True)
        return None


def _should_skip_sparse_pdf_text_layer(file_path: str, file_type: FileType | str) -> bool:
    if file_type != FileType.PDF_SCANNED:
        return False
    key = _pdf_text_layer_sparse_key(file_path)
    if key is None:
        return False
    with _PDF_TEXT_LAYER_SPARSE_LOCK:
        count = _PDF_TEXT_LAYER_SPARSE_COUNTS.get(key, 0)
        if count:
            _PDF_TEXT_LAYER_SPARSE_COUNTS.move_to_end(key)
        return count >= _PDF_TEXT_LAYER_SPARSE_SKIP_AFTER


def _get_pdf_text_layer_probe_lock(file_path: str, file_type: FileType | str) -> asyncio.Lock | None:
    if file_type != FileType.PDF_SCANNED:
        return None
    key = _pdf_text_layer_sparse_key(file_path)
    if key is None:
        return None

    global _PDF_TEXT_LAYER_PROBE_LOCKS_LOOP
    loop = asyncio.get_running_loop()
    with _PDF_TEXT_LAYER_SPARSE_LOCK:
        if _PDF_TEXT_LAYER_PROBE_LOCKS_LOOP is not loop:
            _PDF_TEXT_LAYER_PROBE_LOCKS.clear()
            _PDF_TEXT_LAYER_PROBE_LOCKS_LOOP = loop
        lock = _PDF_TEXT_LAYER_PROBE_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _PDF_TEXT_LAYER_PROBE_LOCKS[key] = lock
        return lock


def _sparse_pdf_text_layer_probe_weight(stats: dict | None = None) -> int:
    if not isinstance(stats, dict):
        return 1
    min_chars = max(0, int(settings.PDF_TEXT_LAYER_MIN_CHARS))
    if min_chars <= 0:
        return 1
    char_count = int(stats.get("char_count") or 0)
    if char_count <= max(1, min_chars // 4):
        return _PDF_TEXT_LAYER_SPARSE_SKIP_AFTER
    return 1


def _record_sparse_pdf_text_layer_probe(
    file_path: str,
    file_type: FileType | str,
    *,
    stats: dict | None = None,
) -> None:
    if file_type != FileType.PDF_SCANNED:
        return
    key = _pdf_text_layer_sparse_key(file_path)
    if key is None:
        return
    weight = max(1, _sparse_pdf_text_layer_probe_weight(stats))
    with _PDF_TEXT_LAYER_SPARSE_LOCK:
        _PDF_TEXT_LAYER_SPARSE_COUNTS[key] = min(
            _PDF_TEXT_LAYER_SPARSE_SKIP_AFTER,
            _PDF_TEXT_LAYER_SPARSE_COUNTS.get(key, 0) + weight,
        )
        _PDF_TEXT_LAYER_SPARSE_COUNTS.move_to_end(key)
        while len(_PDF_TEXT_LAYER_SPARSE_COUNTS) > _PDF_TEXT_LAYER_SPARSE_CACHE_MAX_ITEMS:
            _PDF_TEXT_LAYER_SPARSE_COUNTS.popitem(last=False)


def _clear_pdf_text_layer_sparse_probe_cache() -> None:
    with _PDF_TEXT_LAYER_SPARSE_LOCK:
        _PDF_TEXT_LAYER_SPARSE_COUNTS.clear()
        _PDF_TEXT_LAYER_PROBE_LOCKS.clear()


async def prime_pdf_text_layer_sparse_probe(
    file_path: str,
    file_type: FileType | str,
    *,
    page: int = 1,
) -> dict:
    """Warm the scanned-PDF text-layer skip decision before page fan-out."""
    file_type = _normalize_file_type(file_type)
    if (
        file_type != FileType.PDF_SCANNED
        or not settings.PDF_TEXT_LAYER_VISION_ENABLED
        or _should_skip_sparse_pdf_text_layer(file_path, file_type)
    ):
        return {"ran": False, "skipped": True}

    probe_lock = _get_pdf_text_layer_probe_lock(file_path, file_type)

    async def probe_once() -> dict:
        if _should_skip_sparse_pdf_text_layer(file_path, file_type):
            return {"ran": False, "skipped": True}
        parser = FileParser()
        started = time.perf_counter()
        blocks, width, height = await parser.get_pdf_page_text_blocks(file_path, page)
        text_chars = sum(len(str(block.text or "").strip()) for block in blocks)
        stats = {
            "page": int(page),
            "block_count": len(blocks),
            "char_count": text_chars,
            "page_width": width,
            "page_height": height,
            "cache_hit": bool(getattr(parser, "last_pdf_page_text_blocks_cache_hit", False)),
            "duration_ms": _elapsed_ms(started),
        }
        min_chars = int(settings.PDF_TEXT_LAYER_MIN_CHARS)
        if text_chars < min_chars:
            _record_sparse_pdf_text_layer_probe(file_path, file_type, stats=stats)
            stats["sparse"] = True
            stats["skip_after_probe"] = _should_skip_sparse_pdf_text_layer(file_path, file_type)
        else:
            stats["sparse"] = False
            stats["skip_after_probe"] = False
        stats["ran"] = True
        return stats

    if probe_lock is not None:
        async with probe_lock:
            return await probe_once()
    return await probe_once()


class VisionService:
    """Vision recognition orchestration."""

    def __init__(self):
        self.file_parser = FileParser()
        self.ocr_has_service = get_ocr_has_vision_service()
        self.visual_grounding = LocateAnythingGroundingService()
        self.last_visual_feature_stage_duration_ms: dict[str, int] = {}
        self.last_warnings: list[str] = []

    async def detect_sensitive_regions(
        self,
        file_path: str,
        file_type: FileType,
        page: int = 1,
        draw_result: bool = True,
        pipeline_mode: str = "ocr_has",
        pipeline_types: list = None,
    ) -> tuple[list[BoundingBox], str | None]:
        total_start = time.perf_counter()
        duration_ms: dict[str, int | dict[str, int]] = {"ocr_has": 0, "visual_features": 0}
        self.last_pdf_text_layer_duration_ms = 0
        self.last_pdf_text_layer_stats = {}
        file_type = _normalize_file_type(file_type)
        image_data: bytes | None = None

        async def get_image_data() -> bytes:
            nonlocal image_data
            if image_data is not None:
                return image_data
            if file_type == FileType.IMAGE:
                image_data = await self.file_parser.read_image(file_path)
                return image_data
            render_start = time.perf_counter()
            image_data = await self.file_parser.get_pdf_page_image(file_path, page)
            duration_ms["pdf_render_ms"] = _elapsed_ms(render_start)
            duration_ms["pdf_render_cache_hit"] = bool(
                getattr(self.file_parser, "last_pdf_page_image_cache_hit", False)
            )
            return image_data

        if file_type == FileType.IMAGE:
            image_data = await get_image_data()
        elif file_type in [FileType.PDF, FileType.PDF_SCANNED]:
            pass
        else:
            raise ValueError(f"Unsupported file type for vision: {file_type}")

        logger.info("Using pipeline: %s", pipeline_mode)

        pipeline_start = time.perf_counter()
        used_pdf_text_layer = False
        if pipeline_mode == "visual_features":
            image_data = await get_image_data()
            bounding_boxes, result_image_base64 = await self._detect_with_visual_features(
                image_data, page, pipeline_types
            )
        else:
            async def try_pdf_text_layer() -> tuple[list[BoundingBox], str | None] | None:
                if (
                    file_type not in [FileType.PDF, FileType.PDF_SCANNED]
                    or not settings.PDF_TEXT_LAYER_VISION_ENABLED
                ):
                    return None
                probe_lock = _get_pdf_text_layer_probe_lock(file_path, file_type)
                if probe_lock is not None:
                    async with probe_lock:
                        return await attempt_pdf_text_layer()
                return await attempt_pdf_text_layer()

            async def attempt_pdf_text_layer() -> tuple[list[BoundingBox], str | None] | None:
                if _should_skip_sparse_pdf_text_layer(file_path, file_type):
                    duration_ms["pdf_text_layer_skipped_sparse_file"] = True
                    return None
                try:
                    pdf_boxes, pdf_result = await self._detect_with_pdf_text_layer(
                        file_path,
                        page,
                        pipeline_types,
                    )
                    duration_ms["pdf_text_layer_used"] = True
                    return pdf_boxes, pdf_result
                except ValueError as exc:
                    duration_ms["pdf_text_layer_used"] = False
                    _record_sparse_pdf_text_layer_probe(
                        file_path,
                        file_type,
                        stats=self.last_pdf_text_layer_stats,
                    )
                    logger.info("PDF text layer not used for page %d: %s", page, exc)
                except Exception:
                    duration_ms["pdf_text_layer_used"] = False
                    logger.exception("PDF text layer detection failed; falling back to image OCR")
                return None

            pdf_text_layer_result = await try_pdf_text_layer()
            if pdf_text_layer_result is not None:
                bounding_boxes, result_image_base64 = pdf_text_layer_result
                used_pdf_text_layer = True
                if draw_result:
                    preview_start = time.perf_counter()
                    image_data = await get_image_data()
                    img = Image.open(io.BytesIO(image_data))
                    img = ImageOps.exif_transpose(img)
                    result_image_base64 = self._draw_boxes_on_image(img, bounding_boxes)
                    duration_ms["preview_draw_ms"] = _elapsed_ms(preview_start)
            if not used_pdf_text_layer:
                image_data = await get_image_data()
                bounding_boxes, result_image_base64 = await self._detect_with_ocr_has(
                    image_data, page, pipeline_types
                )
        duration_ms[pipeline_mode] = _elapsed_ms(pipeline_start)
        duration_ms["total"] = _elapsed_ms(total_start)
        if self.last_pdf_text_layer_stats:
            duration_ms["pdf_text_layer_ms"] = int(self.last_pdf_text_layer_duration_ms)
            duration_ms["pdf_text_layer"] = dict(self.last_pdf_text_layer_stats or {})
        self.last_duration_ms = duration_ms
        self.last_pipeline_status = {
            pipeline_mode: {
                "ran": True,
                "skipped": False,
                "failed": False,
                "region_count": len(bounding_boxes),
                "error": None,
                "duration_ms": duration_ms[pipeline_mode],
            }
        }
        ocr_has_service = getattr(self, "ocr_has_service", None)
        if pipeline_mode == "ocr_has" and getattr(ocr_has_service, "last_duration_ms", None):
            self.last_pipeline_status[pipeline_mode]["stage_duration_ms"] = dict(
                ocr_has_service.last_duration_ms
            )
        elif pipeline_mode == "visual_features" and getattr(self, "last_visual_feature_stage_duration_ms", None):
            self.last_pipeline_status[pipeline_mode]["stage_duration_ms"] = dict(
                self.last_visual_feature_stage_duration_ms
            )

        logger.info("Vision detect done (%s): %d regions", pipeline_mode, len(bounding_boxes))
        return bounding_boxes, result_image_base64

    async def detect_with_dual_pipeline(
        self,
        file_path: str,
        file_type: FileType,
        page: int = 1,
        ocr_has_types: list = None,
        visual_feature_types: list = None,
        include_result_image: bool = True,
    ) -> tuple[list[BoundingBox], str | None]:
        total_start = time.perf_counter()
        duration_ms: dict[str, int | dict[str, int]] = {"ocr_has": 0, "visual_features": 0}
        self.last_visual_feature_stage_duration_ms = {}
        self.last_pdf_text_layer_duration_ms = 0
        self.last_pdf_text_layer_stats = {}
        file_type = _normalize_file_type(file_type)
        image_data: bytes | None = None
        image_data_task: asyncio.Task[bytes] | None = None
        if file_type not in [FileType.IMAGE, FileType.PDF, FileType.PDF_SCANNED]:
            raise ValueError(f"Unsupported file type for vision: {file_type}")

        async def load_image_data() -> bytes:
            nonlocal image_data
            if file_type == FileType.IMAGE:
                image_data = await self.file_parser.read_image(file_path)
                return image_data
            render_start = time.perf_counter()
            image_data = await self.file_parser.get_pdf_page_image(file_path, page)
            duration_ms["pdf_render_ms"] = _elapsed_ms(render_start)
            duration_ms["pdf_render_cache_hit"] = bool(
                getattr(self.file_parser, "last_pdf_page_image_cache_hit", False)
            )
            return image_data

        async def get_image_data() -> bytes:
            nonlocal image_data_task
            if image_data is not None:
                return image_data
            if image_data_task is None:
                image_data_task = asyncio.create_task(load_image_data())
            try:
                return await image_data_task
            except Exception:
                image_data_task = None
                raise

        visual_feature_items = list(visual_feature_types or [])
        seal_requested_via_visual_features = (
            self._visual_slug_requested(visual_feature_items, "official_seal")
            if visual_feature_types
            else False
        )
        effective_ocr_has_types = list(ocr_has_types or [])
        if seal_requested_via_visual_features and not any(
            str(getattr(item, "id", item) or "").strip().upper() == "SEAL"
            for item in effective_ocr_has_types
        ):
            effective_ocr_has_types.append(
                SimpleNamespace(id="SEAL", name=SLUG_TO_NAME_ZH.get("official_seal", "公章"))
            )

        effective_visual_feature_types: list | None = None
        if visual_feature_types:
            effective_visual_feature_types = [
                item
                for item in visual_feature_items
                if normalize_visual_slug(getattr(item, "id", item)) not in OCR_FALLBACK_ONLY_VISUAL_SLUGS
            ]
            if not effective_visual_feature_types:
                effective_visual_feature_types = None

        all_boxes: list[BoundingBox] = []
        ocr_blocks_for_signature: list | None = None
        visual_signature_requested = self._signature_requested(effective_visual_feature_types)
        pipeline_status: dict[str, dict] = {
            "ocr_has": {
                "ran": False,
                "skipped": not bool(effective_ocr_has_types),
                "failed": False,
                "region_count": 0,
                "error": None,
                "duration_ms": 0,
            },
            "visual_features": {
                "ran": False,
                "skipped": not bool(effective_visual_feature_types),
                "failed": False,
                "region_count": 0,
                "error": None,
                "duration_ms": 0,
            },
        }
        self.last_pipeline_status = pipeline_status
        self.last_duration_ms = duration_ms
        self.last_warnings: list[str] = []

        async def invoke_detector(func, page_no: int, types: list | None):
            kwargs = {}
            try:
                if "draw_result" in inspect.signature(func).parameters:
                    kwargs["draw_result"] = False
            except (TypeError, ValueError):
                pass
            image = await get_image_data()
            return await func(image, page_no, types, **kwargs)

        async def timed(label: str, coro):
            start = time.perf_counter()
            try:
                return await coro
            finally:
                elapsed_ms = _elapsed_ms(start)
                duration_ms[label] = elapsed_ms
                pipeline_status.setdefault(label, {})["duration_ms"] = elapsed_ms
                logger.info("%s finished in %.2fs", label, elapsed_ms / 1000)

        jobs = []
        if effective_ocr_has_types:
            logger.info("Running OCR+HaS with %d types...", len(effective_ocr_has_types))

            async def run_ocr_has_job():
                if (
                    file_type not in [FileType.PDF, FileType.PDF_SCANNED]
                    or not settings.PDF_TEXT_LAYER_VISION_ENABLED
                ):
                    return await invoke_detector(self._detect_with_ocr_has, page, effective_ocr_has_types)

                async def attempt_pdf_text_layer() -> tuple[list[BoundingBox], str | None] | None:
                    if seal_requested_via_visual_features:
                        return None
                    if _should_skip_sparse_pdf_text_layer(file_path, file_type):
                        duration_ms["pdf_text_layer_skipped_sparse_file"] = True
                        return None
                    try:
                        return await self._detect_with_pdf_text_layer(file_path, page, effective_ocr_has_types)
                    except ValueError as exc:
                        _record_sparse_pdf_text_layer_probe(
                            file_path,
                            file_type,
                            stats=self.last_pdf_text_layer_stats,
                        )
                        logger.info("PDF text layer not used for page %d: %s", page, exc)
                    except Exception:
                        logger.exception("PDF text layer detection failed; falling back to image OCR")
                    return None

                probe_lock = _get_pdf_text_layer_probe_lock(file_path, file_type)
                if probe_lock is not None:
                    async with probe_lock:
                        pdf_text_layer_result = await attempt_pdf_text_layer()
                else:
                    pdf_text_layer_result = await attempt_pdf_text_layer()
                if pdf_text_layer_result is not None:
                    return pdf_text_layer_result
                return await invoke_detector(self._detect_with_ocr_has, page, effective_ocr_has_types)

            jobs.append(
                (
                    "ocr_has",
                    lambda: timed(
                        "ocr_has",
                        run_ocr_has_job(),
                    ),
                )
            )
        else:
            logger.info("OCR+HaS skipped (no types enabled)")

        if effective_visual_feature_types:
            logger.info("Running visual features with %d types...", len(effective_visual_feature_types))
            jobs.append(
                (
                    "visual_features",
                    lambda: timed(
                        "visual_features",
                        invoke_detector(self._detect_with_visual_features, page, effective_visual_feature_types),
                    ),
                )
            )
        else:
            logger.info("Visual features skipped (no types enabled)")

        signature_ocr_context_attempted = False
        signature_ocr_fast_path_added = 0

        def only_signature_visual_features() -> bool:
            return bool(effective_visual_feature_types) and all(
                normalize_visual_slug(getattr(item, "id", item)) == "signature"
                for item in effective_visual_feature_types
            )

        async def add_ocr_signature_supplements(reason: str) -> int:
            nonlocal signature_ocr_context_attempted, signature_ocr_fast_path_added
            if signature_ocr_context_attempted:
                return 0
            signature_ocr_context_attempted = True
            if (
                not visual_signature_requested
                or not bool(getattr(settings, "VISUAL_FEATURES_SIGNATURE_LOCAL_SUPPLEMENTS_ENABLED", False))
                or ocr_blocks_for_signature is None
            ):
                return 0
            image = await get_image_data()
            img = Image.open(io.BytesIO(image))
            img = ImageOps.exif_transpose(img).convert("RGB")
            anchor_items = self._signature_anchor_items_from_ocr_blocks(ocr_blocks_for_signature, img.size)
            if not anchor_items:
                return 0
            supplements = await self._supplement_signatures_from_ocr_context(
                img,
                image,
                page,
                all_boxes,
                anchor_items=anchor_items,
            )
            if not supplements:
                return 0
            all_boxes.extend(supplements)
            signature_ocr_fast_path_added += len(supplements)
            logger.info("Signature OCR-anchor %s added %d regions", reason, len(supplements))
            return len(supplements)

        async def record_pipeline_result(label: str, result) -> None:
            nonlocal ocr_blocks_for_signature
            status = pipeline_status.setdefault(
                label,
                {
                    "ran": False,
                    "skipped": False,
                    "failed": False,
                    "region_count": 0,
                    "error": None,
                    "duration_ms": int(duration_ms.get(label, 0) or 0),
                },
            )
            status["ran"] = True
            status["skipped"] = False
            status["duration_ms"] = int(duration_ms.get(label, 0) or 0)
            if isinstance(result, Exception):
                logger.error("%s failed: %s", label, result)
                status["failed"] = True
                status["error"] = str(result)
                self.last_warnings.append(f"{label} failed: {result}")
                return
            boxes, _ = result
            all_boxes.extend(boxes)
            status["region_count"] = len(boxes)
            if label == "ocr_has":
                ocr_has_service = getattr(self, "ocr_has_service", None)
                stage_duration_ms = dict(getattr(ocr_has_service, "last_duration_ms", {}) or {})
                cached_ocr_blocks = getattr(ocr_has_service, "last_ocr_blocks", None)
                if cached_ocr_blocks is not None:
                    ocr_blocks_for_signature = list(cached_ocr_blocks)
                if stage_duration_ms:
                    status["stage_duration_ms"] = stage_duration_ms
            elif label == "visual_features" and getattr(self, "last_visual_feature_stage_duration_ms", None):
                status["stage_duration_ms"] = dict(self.last_visual_feature_stage_duration_ms)
            logger.info("%s found %d regions", label, len(boxes))

        if not jobs:
            logger.info("No vision pipeline jobs enabled; returning empty results")
        elif settings.VISION_DUAL_PIPELINE_PARALLEL and len(jobs) > 1:
            logger.info("Dual pipeline scheduling: parallel")
            labels = [label for label, _factory in jobs]
            tasks = [asyncio.create_task(factory()) for _label, factory in jobs]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for label, result in zip(labels, results, strict=False):
                await record_pipeline_result(label, result)
        else:
            logger.info("Dual pipeline scheduling: sequential")
            skip_visual_features = False
            for label, factory in jobs:
                if label == "visual_features" and skip_visual_features:
                    status = pipeline_status.setdefault(label, {})
                    status.update(
                        {
                            "ran": False,
                            "skipped": True,
                            "failed": False,
                            "error": None,
                            "duration_ms": 0,
                            "skip_reason": "signature_ocr_fast_path",
                        }
                    )
                    duration_ms[label] = 0
                    logger.info("Visual features skipped: signature OCR fast path already produced regions")
                    continue
                try:
                    result = await factory()
                except Exception as exc:
                    result = exc
                await record_pipeline_result(label, result)
                if (
                    label == "ocr_has"
                    and not isinstance(result, Exception)
                    and bool(getattr(settings, "VISUAL_FEATURES_SIGNATURE_OCR_FAST_PATH", False))
                    and bool(getattr(settings, "VISUAL_FEATURES_SIGNATURE_SKIP_WHEN_OCR_ANCHOR_FOUND", False))
                    and only_signature_visual_features()
                ):
                    added = await add_ocr_signature_supplements("fast path")
                    skip_visual_features = added > 0

        if visual_signature_requested and bool(
            getattr(settings, "VISUAL_FEATURES_SIGNATURE_LOCAL_SUPPLEMENTS_ENABLED", False)
        ):
            image_data = await get_image_data()
            img = Image.open(io.BytesIO(image_data))
            img = ImageOps.exif_transpose(img).convert("RGB")
            cached_anchor_items = (
                self._signature_anchor_items_from_ocr_blocks(ocr_blocks_for_signature, img.size)
                if ocr_blocks_for_signature is not None
                else None
            )
            local_signature_count = 0
            signature_supplements = self._supplement_signatures_from_seal_context(img, all_boxes, page)
            if signature_supplements:
                logger.info("Signature seal-context supplement added %d regions", len(signature_supplements))
                all_boxes.extend(signature_supplements)
                local_signature_count += len(signature_supplements)
            if not signature_ocr_context_attempted:
                ocr_signature_supplements = await self._supplement_signatures_from_ocr_context(
                    img,
                    image_data,
                    page,
                    all_boxes,
                    anchor_items=cached_anchor_items,
                )
                if ocr_signature_supplements:
                    logger.info("Signature OCR-anchor supplement added %d regions", len(ocr_signature_supplements))
                    all_boxes.extend(ocr_signature_supplements)
                    local_signature_count += len(ocr_signature_supplements)


        all_boxes = self._filter_visual_artifacts(all_boxes)
        all_boxes = self._deduplicate_boxes(all_boxes)
        all_boxes = self._expand_signature_boxes(all_boxes)

        result_image_base64 = None
        if include_result_image:
            image_data = await get_image_data()
            img = Image.open(io.BytesIO(image_data))
            img = ImageOps.exif_transpose(img)
            result_image_base64 = self._draw_boxes_on_image(img, all_boxes)

        duration_ms["total"] = _elapsed_ms(total_start)
        if self.last_pdf_text_layer_stats:
            duration_ms["pdf_text_layer_ms"] = int(self.last_pdf_text_layer_duration_ms)
            duration_ms["pdf_text_layer"] = dict(self.last_pdf_text_layer_stats or {})
        self.last_duration_ms = duration_ms
        logger.info("Dual pipeline total: %d regions, %.2fs", len(all_boxes), duration_ms["total"] / 1000)
        return all_boxes, result_image_base64

    @staticmethod
    def _signature_requested(visual_feature_types: list | None) -> bool:
        return any(
            str(getattr(item, "id", "") or getattr(item, "type", "") or item).strip().lower() == "signature"
            for item in (visual_feature_types or [])
        )

    def _supplement_signatures_from_seal_context(
        self,
        image: Image.Image,
        boxes: list[BoundingBox],
        page: int,
    ) -> list[BoundingBox]:
        seal_boxes = [
            box
            for box in boxes
            if self._norm_box_type(box.type) in {"official_seal", "seal", "stamp"}
            and box.y >= 0.65
            and box.width >= 0.10
            and box.height >= 0.08
        ]
        if not seal_boxes:
            return []

        existing = [
            box
            for box in boxes
            if self._norm_box_type(box.type) in {"signature", "handwriting", "approval_mark"}
        ]
        supplements: list[BoundingBox] = []
        for seal in seal_boxes:
            candidate = self._signature_candidate_near_seal(image, seal, page)
            if candidate is None:
                continue
            if any(
                self._calculate_iou(candidate, box) > 0.08
                or self._calculate_smaller_overlap(candidate, box) >= 0.45
                for box in [*existing, *supplements]
            ):
                continue
            supplements.append(candidate)
        return supplements

    def _signature_candidate_near_seal(
        self,
        image: Image.Image,
        seal: BoundingBox,
        page: int,
    ) -> BoundingBox | None:
        width, height = image.size
        if width <= 0 or height <= 0:
            return None

        x1 = max(0, int((seal.x + seal.width * 0.25) * width))
        x2 = min(width, int((seal.x + seal.width * 1.48) * width))
        y1 = max(0, int((seal.y + seal.height * 0.30) * height))
        y2 = min(height, int((seal.y + seal.height * 1.12) * height))
        if x2 - x1 < 24 or y2 - y1 < 18:
            return None

        crop = np.asarray(image.crop((x1, y1, x2, y2)).convert("RGB"))
        mask = signature_stroke_mask(crop)
        if int(mask.sum()) < max(18, int(mask.size * 0.0005)):
            return None

        row_clusters = self._active_mask_clusters(mask.sum(axis=1), max(2, int(mask.shape[1] * 0.006)), max_gap=5)
        if not row_clusters:
            return None

        anchor_x = (seal.x + seal.width * 0.72) * width - x1
        best: tuple[float, tuple[int, int], tuple[int, int], np.ndarray] | None = None
        for row_start, row_end, row_pixels in row_clusters:
            if row_start > mask.shape[0] * 0.82:
                continue
            row_mask = mask[row_start: row_end + 1, :]
            col_clusters = self._active_mask_clusters(
                row_mask.sum(axis=0),
                max(2, int(row_mask.shape[0] * 0.05)),
                max_gap=10,
            )
            for col_start, col_end, col_pixels in col_clusters:
                center = (col_start + col_end) / 2
                if center < anchor_x + max(16.0, seal.width * width * 0.05):
                    continue
                component = row_mask[:, col_start: col_end + 1]
                ys, xs = np.where(component)
                if len(xs) < 16 or len(ys) < 8:
                    continue
                component_width = int(xs.max() - xs.min() + 1)
                component_height = int(ys.max() - ys.min() + 1)
                if component_width < 18 or component_height < 8:
                    continue
                score = (
                    float(col_pixels)
                    + component_width * 4.0
                    + component_height * 2.0
                    - abs(center - anchor_x) * 0.15
                    + float(row_pixels) * 0.05
                )
                if best is None or score > best[0]:
                    best = (score, (row_start, row_end), (col_start, col_end), component)

        if best is None:
            return None

        _score, (row_start, _row_end), (col_start, _col_end), component = best
        ys, xs = np.where(component)
        if len(xs) == 0 or len(ys) == 0:
            return None

        nx1 = max(0, x1 + col_start + int(xs.min()) - 8)
        ny1 = max(0, y1 + row_start + int(ys.min()) - 8)
        nx2 = min(width, x1 + col_start + int(xs.max()) + 12)
        ny2 = min(height, y1 + row_start + int(ys.max()) + 12)
        if nx2 <= nx1 or ny2 <= ny1:
            return None
        if (nx2 - nx1) < 18 or (ny2 - ny1) < 8:
            return None

        return BoundingBox(
            id=f"signature_seal_{uuid.uuid4().hex[:8]}",
            x=nx1 / width,
            y=ny1 / height,
            width=(nx2 - nx1) / width,
            height=(ny2 - ny1) / height,
            type="signature",
            text="签字",
            page=page,
            confidence=0.78,
            source="visual_features",
            source_detail="signature#seal_context:stroke_refined",
            evidence_source="local_fallback",
        )

    async def _supplement_signatures_from_ocr_context(
        self,
        image: Image.Image,
        image_data: bytes,
        page: int,
        existing_boxes: list[BoundingBox],
        anchor_items: list[tuple[str, int, object]] | None = None,
    ) -> list[BoundingBox]:
        """Find signatures anchored by OCR/Structure signing labels.

        This is a PaddleOCR-VL/PP-Structure fallback for signature-only runs or
        visual feature service outages. It uses signing-role text as an anchor, then extracts the
        dark handwritten components to the right of that label instead of
        trusting the OCR text box itself.
        """
        if anchor_items is None:
            try:
                anchor_items = await asyncio.to_thread(self._load_signature_ocr_anchor_items, image_data)
            except Exception:
                logger.exception("Signature OCR-anchor supplement failed while loading OCR items")
                return []
        if not anchor_items:
            return []

        page_width, page_height = image.size
        supplements: list[BoundingBox] = []
        for source_name, index, item in anchor_items:
            pixel_box = self._signature_box_from_ocr_anchor(image, item)
            if pixel_box is None:
                continue
            x1, y1, x2, y2 = pixel_box
            if x2 <= x1 or y2 <= y1:
                continue
            candidate = BoundingBox(
                id=f"ocr_signature_{uuid.uuid4().hex[:8]}",
                x=x1 / page_width,
                y=y1 / page_height,
                width=(x2 - x1) / page_width,
                height=(y2 - y1) / page_height,
                type="signature",
                text="签字",
                page=page,
                confidence=max(0.72, min(0.92, float(getattr(item, "confidence", 0.82) or 0.82))),
                source="ocr_has",
                source_detail=f"ocr_signature_anchor:{source_name}#{index}",
                evidence_source="ocr_has",
            )
            if any(self._is_duplicate_visual_box(candidate, existing) for existing in existing_boxes + supplements):
                continue
            supplements.append(candidate)
        return supplements

    @staticmethod
    def _signature_anchor_items_from_ocr_blocks(
        ocr_blocks: list | None,
        image_size: tuple[int, int],
    ) -> list[tuple[str, int, object]]:
        if not ocr_blocks:
            return []
        page_width, page_height = image_size
        if page_width <= 0 or page_height <= 0:
            return []
        collected: list[tuple[str, int, object]] = []
        for index, block in enumerate(ocr_blocks, start=1):
            text = str(getattr(block, "text", "") or "")
            if not VisionService._is_signature_anchor_text(text):
                continue
            left = float(getattr(block, "left", 0) or 0)
            top = float(getattr(block, "top", 0) or 0)
            width = float(getattr(block, "width", 0) or 0)
            height = float(getattr(block, "height", 0) or 0)
            if width <= 0 or height <= 0:
                continue
            collected.append(
                (
                    "cached_ocr",
                    index,
                    SimpleNamespace(
                        text=text,
                        x=left / page_width,
                        y=top / page_height,
                        width=width / page_width,
                        height=height / page_height,
                        confidence=float(getattr(block, "confidence", 0.82) or 0.82),
                    ),
                )
            )
        return sorted(collected, key=VisionService._signature_anchor_priority)

    @staticmethod
    def _signature_anchor_priority(anchor: tuple[str, int, object]) -> tuple[int, float, int]:
        item = anchor[2]
        text = "".join(str(getattr(item, "text", "") or "").split())
        width = float(getattr(item, "width", 0.0) or 0.0)
        height = float(getattr(item, "height", 0.0) or 0.0)
        area = max(0.0, width) * max(0.0, height)
        coarse = width >= 0.25 or height >= 0.08 or len(text) > 24
        return (1 if coarse else 0, area, len(text))

    @staticmethod
    def _load_signature_ocr_anchor_items(image_data: bytes) -> list[tuple[str, int, object]]:
        from app.services.ocr_service import ocr_service

        if not ocr_service.is_available():
            return []

        collected: list[tuple[str, int, object]] = []
        loaders = []
        if bool(getattr(settings, "OCR_STRUCTURE_ENABLED", False)):
            loaders.append(("structure", ocr_service.extract_structure_boxes))
        loaders.append(("ocr", ocr_service.extract_text_boxes))

        for source_name, loader in loaders:
            try:
                items = loader(image_data)
            except Exception:
                logger.exception("Signature OCR-anchor %s extraction failed", source_name)
                continue
            for index, item in enumerate(items, start=1):
                if VisionService._is_signature_anchor_text(str(getattr(item, "text", "") or "")):
                    collected.append((source_name, index, item))
        return sorted(collected, key=VisionService._signature_anchor_priority)

    @staticmethod
    def _is_signature_anchor_text(text: str) -> bool:
        compact = "".join(str(text or "").split())
        if not compact:
            return False
        anchor_terms = (
            "签名",
            "签字",
            "签署",
            "签章",
            "医师",
            "医生",
            "护士",
            "代表",
            "负责人",
            "经办人",
            "审核人",
            "审批人",
            "确认人",
        )
        if not any(term in compact for term in anchor_terms):
            return False
        role_terms = (
            "医师",
            "医生",
            "护士",
            "代表",
            "负责人",
            "经办",
            "审核",
            "审批",
            "确认",
        )
        contract_prose_terms = (
            "后生效",
            "法律效力",
            "传真件",
            "扫描件",
            "双方各执",
            "争议",
            "协商",
            "诉讼",
        )
        # Long prose that merely says someone signs or seals a document is not
        # a signing field label. Short labels like "签字" and role labels like
        # "麻醉医师" remain valid anchors.
        if len(compact) > 16 and not any(term in compact for term in role_terms):
            return False
        if (
            len(compact) > 6
            and any(term in compact for term in contract_prose_terms)
            and not any(term in compact for term in role_terms)
        ):
            return False
        return True

    def _signature_box_from_ocr_anchor(self, image: Image.Image, item: object) -> tuple[int, int, int, int] | None:
        page_width, page_height = image.size
        text = str(getattr(item, "text", "") or "")
        x1 = int(float(getattr(item, "x", 0.0) or 0.0) * page_width)
        y1 = int(float(getattr(item, "y", 0.0) or 0.0) * page_height)
        x2 = int((float(getattr(item, "x", 0.0) or 0.0) + float(getattr(item, "width", 0.0) or 0.0)) * page_width)
        y2 = int((float(getattr(item, "y", 0.0) or 0.0) + float(getattr(item, "height", 0.0) or 0.0)) * page_height)
        x1 = max(0, min(page_width - 1, x1))
        y1 = max(0, min(page_height - 1, y1))
        x2 = max(x1 + 1, min(page_width, x2))
        y2 = max(y1 + 1, min(page_height, y2))
        box_width = max(1, x2 - x1)
        box_height = max(1, y2 - y1)

        if "签名" in text or "签字" in text or "签章" in text:
            sx1 = x1 + int(box_width * 0.62)
            sx2 = min(page_width, x2 + max(60, int(box_width * 0.35)))
            sy1 = max(0, y1 - int(box_height * 0.15))
            sy2 = min(page_height, y2 + int(box_height * 0.10))
        else:
            sx1 = max(0, x2 - int(box_width * 0.08))
            sx2 = min(page_width, x2 + max(160, int(box_width * 1.8)))
            sy1 = max(0, y1 - int(box_height * 1.15))
            sy2 = min(page_height, y2 + int(box_height * 2.0))
        if sx2 <= sx1 or sy2 <= sy1:
            return None

        crop = image.crop((sx1, sy1, sx2, sy2)).convert("RGB")
        mask = self._signature_anchor_stroke_mask(crop)
        components = self._mask_components(mask)
        good_components: list[tuple[int, int, int, int, int]] = []
        for component in components:
            cx1, cy1, cx2, cy2, area = component
            component_width = cx2 - cx1 + 1
            component_height = cy2 - cy1 + 1
            if area < 8:
                continue
            if component_width > mask.shape[1] * 0.85 and component_height <= 4:
                continue
            if component_width / max(1, component_height) > 14 and component_height < 10:
                continue
            if area >= 14 or component_height >= 12 or component_width >= 12:
                good_components.append(component)
        if not good_components:
            return None

        selected = self._select_signature_anchor_components(good_components)
        if not selected:
            return None
        nx1 = max(0, sx1 + min(component[0] for component in selected) - 6)
        ny1 = max(0, sy1 + min(component[1] for component in selected) - 6)
        nx2 = min(page_width, sx1 + max(component[2] for component in selected) + 7)
        ny2 = min(page_height, sy1 + max(component[3] for component in selected) + 7)
        if nx2 - nx1 < 8 or ny2 - ny1 < 6:
            return None
        return nx1, ny1, nx2, ny2

    @staticmethod
    def _signature_anchor_stroke_mask(image: Image.Image) -> np.ndarray:
        arr = np.asarray(image.convert("RGB")).astype(np.int16, copy=False)
        red = arr[:, :, 0]
        green = arr[:, :, 1]
        blue = arr[:, :, 2]
        gray = (red * 30 + green * 59 + blue * 11) / 100
        mask = gray < 170
        mask = VisionService._remove_ocr_rule_lines(mask)
        if mask.size:
            row_counts = mask.sum(axis=1)
            mask[row_counts > mask.shape[1] * 0.50, :] = False
            col_counts = mask.sum(axis=0)
            mask[:, col_counts > mask.shape[0] * 0.78] = False
        return mask

    @staticmethod
    def _mask_components(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
        if mask.ndim != 2 or mask.size == 0:
            return []
        height, width = mask.shape
        seen = np.zeros(mask.shape, dtype=bool)
        components: list[tuple[int, int, int, int, int]] = []
        for y in range(height):
            active_xs = np.where(mask[y] & ~seen[y])[0]
            for raw_x in active_xs:
                x = int(raw_x)
                if seen[y, x] or not mask[y, x]:
                    continue
                stack = [(y, x)]
                seen[y, x] = True
                min_x = max_x = x
                min_y = max_y = y
                area = 0
                while stack:
                    current_y, current_x = stack.pop()
                    area += 1
                    min_x = min(min_x, current_x)
                    max_x = max(max_x, current_x)
                    min_y = min(min_y, current_y)
                    max_y = max(max_y, current_y)
                    for next_y in range(max(0, current_y - 1), min(height, current_y + 2)):
                        for next_x in range(max(0, current_x - 1), min(width, current_x + 2)):
                            if not seen[next_y, next_x] and mask[next_y, next_x]:
                                seen[next_y, next_x] = True
                                stack.append((next_y, next_x))
                components.append((min_x, min_y, max_x, max_y, area))
        return components

    @staticmethod
    def _select_signature_anchor_components(
        components: list[tuple[int, int, int, int, int]],
    ) -> list[tuple[int, int, int, int, int]]:
        base = max(components, key=lambda item: item[4] + (item[3] - item[1]) * 2 + (item[2] - item[0]))
        selected = [base]
        changed = True
        while changed:
            changed = False
            x1 = min(component[0] for component in selected)
            y1 = min(component[1] for component in selected)
            x2 = max(component[2] for component in selected)
            y2 = max(component[3] for component in selected)
            for component in components:
                if component in selected:
                    continue
                gap = max(component[0] - x2, x1 - component[2], 0)
                vertical_gap = max(component[1] - y2, y1 - component[3], 0)
                vertical_overlap = min(component[3], y2) - max(component[1], y1)
                if gap <= 36 and vertical_gap <= 18 and vertical_overlap >= -12:
                    selected.append(component)
                    changed = True
        return selected

    @staticmethod
    def _active_mask_clusters(values: np.ndarray, min_value: int, max_gap: int) -> list[tuple[int, int, int]]:
        active = np.where(values >= min_value)[0]
        if len(active) == 0:
            return []
        clusters: list[tuple[int, int, int]] = []
        start = prev = int(active[0])
        for raw_index in active[1:]:
            index = int(raw_index)
            if index - prev <= max_gap:
                prev = index
                continue
            clusters.append((start, prev, int(values[start: prev + 1].sum())))
            start = prev = index
        clusters.append((start, prev, int(values[start: prev + 1].sum())))
        return clusters

    def _filter_visual_artifacts(self, boxes: list[BoundingBox]) -> list[BoundingBox]:
        """Drop visual false positives that lack enough target-specific evidence.

        This is deliberately evidence based rather than filename/document based:
        local seal fallbacks are useful for real copied stamps, but edge scanner
        marks and tiny partial arcs can produce the same color/ink signal. Keep
        model-backed seals and full local seal regions; reject local fallback
        fragments that look like page-edge machine-code watermarks.
        """
        if not boxes:
            return boxes

        machine_code_boxes = [
            box
            for box in boxes
            if self._norm_box_type(box.type) in {"qr_code", "qrcode", "barcode"}
        ]
        seal_boxes = [
            box
            for box in boxes
            if self._norm_box_type(box.type) in {"official_seal", "seal", "stamp"}
        ]
        seal_context_signature_boxes = [
            box
            for box in boxes
            if self._norm_box_type(box.type) in {"signature", "handwriting", "approval_mark"}
            and "seal_context" in str(box.source_detail or "").lower()
        ]
        filtered: list[BoundingBox] = []
        removed = 0
        for box in boxes:
            if self._is_scanner_mark_seal_artifact(box, machine_code_boxes) or self._is_signature_artifact(
                box,
                seal_boxes,
                seal_context_signature_boxes,
            ):
                removed += 1
                logger.info(
                    "Filtered visual artifact type=%s detail=%s box=(%.4f, %.4f, %.4f, %.4f)",
                    box.type,
                    box.source_detail,
                    box.x,
                    box.y,
                    box.width,
                    box.height,
                )
                continue
            filtered.append(box)

        if removed:
            self.last_warnings.append(f"visual artifact filter removed {removed} local seal candidate(s)")
        return filtered

    @staticmethod
    def _expand_signature_boxes(
        boxes: list[BoundingBox],
        margin: float = 0.18,
    ) -> list[BoundingBox]:
        """Pad handwritten-signature boxes so redaction covers the full stroke.

        LocateAnything often boxes only the densest part of a signature, leaving
        the rest of the handwritten mark uncovered ("signature not fully boxed").
        For redaction we want the whole mark covered, so expand signature /
        handwriting boxes by ``margin`` of their own size on each side, clamped
        to the page. Other region types are returned unchanged.
        """
        if not boxes or margin <= 0:
            return boxes
        sig_types = {"signature", "handwriting", "approval_mark"}
        result: list[BoundingBox] = []
        for box in boxes:
            if VisionService._norm_box_type(box.type) in sig_types:
                dx = box.width * margin
                dy = box.height * margin
                nx = max(0.0, box.x - dx)
                ny = max(0.0, box.y - dy)
                nx2 = min(1.0, box.x + box.width + dx)
                ny2 = min(1.0, box.y + box.height + dy)
                box = box.model_copy(
                    update={"x": nx, "y": ny, "width": nx2 - nx, "height": ny2 - ny}
                )
            result.append(box)
        return result

    @staticmethod
    def _norm_box_type(value: str | None) -> str:
        return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    def _is_scanner_mark_seal_artifact(
        self,
        box: BoundingBox,
        machine_code_boxes: list[BoundingBox],
    ) -> bool:
        if self._norm_box_type(box.type) not in {"official_seal", "seal", "stamp"}:
            return False
        if box.source != "visual_features" or not str(box.source_detail or "").startswith("local_"):
            return False

        source_detail = str(box.source_detail or "").lower()
        is_red_fallback = "red_seal_fallback" in source_detail
        x2 = box.x + box.width
        y2 = box.y + box.height
        area = box.width * box.height
        edge = box.x <= 0.035 or box.y <= 0.035 or x2 >= 0.965 or y2 >= 0.965
        bottom_band = box.y >= 0.88
        skinny = min(box.width, box.height) <= 0.045
        narrow_vertical = box.width <= 0.045 and box.height >= 0.09
        shallow_horizontal = box.height <= 0.045 and box.width <= 0.18

        # Red fallback candidates have already passed saturated-ink and
        # curved-fragment checks in the detector. Keep isolated edge/bottom
        # red seal fragments; only scanner-code-coupled strips are weak enough
        # to suppress here.
        if (
            not is_red_fallback
            and (bottom_band or edge)
            and shallow_horizontal
            and area < 0.010
        ):
            return True

        # Scanner-app watermarks commonly couple a machine code with a narrow
        # edge text strip. A real official seal should not be accepted from that
        # weak local-fallback evidence alone.
        if narrow_vertical and edge:
            for code_box in machine_code_boxes:
                horizontal_close = (
                    box.x <= code_box.x + code_box.width + 0.025
                    and code_box.x <= x2 + 0.025
                )
                vertical_gap = max(code_box.y - y2, box.y - (code_box.y + code_box.height), 0.0)
                if horizontal_close and vertical_gap <= 0.030:
                    return True

        return bool(not is_red_fallback and edge and skinny and area < 0.003)

    def _is_signature_artifact(
        self,
        box: BoundingBox,
        seal_boxes: list[BoundingBox],
        seal_context_signature_boxes: list[BoundingBox] | None = None,
    ) -> bool:
        if self._norm_box_type(box.type) not in {"signature", "handwriting", "approval_mark"}:
            return False
        if box.source != "visual_features":
            return False
        source_detail = str(box.source_detail or "").lower()
        if (
            "seal_context" not in source_detail
            and ":full" in source_detail
            and box.height < 0.022
            and seal_context_signature_boxes
        ):
            center = box.x + box.width / 2
            for context_box in seal_context_signature_boxes:
                context_center = context_box.x + context_box.width / 2
                if context_box.page == box.page and abs(center - context_center) <= 0.22:
                    return True
        stroke_refined = "stroke_refined" in source_detail or "signature_stroke_adjusted" in source_detail
        if stroke_refined and box.width >= 0.025 and box.height >= 0.006:
            return False
        # Printed text lines are usually very shallow; handwritten signatures
        # should have enough vertical stroke extent to be reviewed as a region.
        if box.height < 0.010:
            return True
        for seal in seal_boxes:
            if self._norm_box_type(seal.type) not in {"official_seal", "seal", "stamp"}:
                continue
            if self._calculate_smaller_overlap(box, seal) >= 0.65:
                return True
        return False

    def _calculate_iou(self, box1: BoundingBox, box2: BoundingBox) -> float:
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

    def _calculate_smaller_overlap(self, box1: BoundingBox, box2: BoundingBox) -> float:
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

    def _is_duplicate_visual_box(
        self,
        candidate: BoundingBox,
        existing: BoundingBox,
        *,
        iou_threshold: float = 0.25,
        smaller_overlap_threshold: float = 0.72,
    ) -> bool:
        if str(candidate.type or "").lower() != str(existing.type or "").lower():
            return False
        return (
            self._calculate_iou(candidate, existing) > iou_threshold
            or self._calculate_smaller_overlap(candidate, existing) >= smaller_overlap_threshold
        )

    def _deduplicate_boxes(
        self,
        boxes: list[BoundingBox],
        iou_threshold: float = 0.3,
    ) -> list[BoundingBox]:
        """Deduplicate boxes efficiently after sorting by x position."""
        if len(boxes) <= 1:
            return boxes

        ocr_boxes = [b for b in boxes if b.source == "ocr_has"]
        visual_boxes = [b for b in boxes if b.source == "visual_features"]
        other_boxes = [b for b in boxes if b.source not in ("ocr_has", "visual_features")]

        def _norm_type(value: str | None) -> str:
            normalized = str(value or "").strip().lower()
            return normalized.replace("-", "_").replace(" ", "_")

        def _is_signature_box(box: BoundingBox) -> bool:
            return _norm_type(box.type) in {"signature", "handwriting", "approval_mark"}

        def _is_ocr_name_like(box: BoundingBox) -> bool:
            box_type = _norm_type(box.type)
            return box.source == "ocr_has" and box_type in {
                "person",
                "name",
                "姓名",
                "人名",
                "signer",
                "legal_representative",
                "representative",
            }

        def _compact_text(value: str | None) -> str:
            return "".join(str(value or "").split())

        target_families = {
            "seal": "seal",
            "official_seal": "seal",
            "stamp": "seal",
            "face": "face",
            "photo": "face",
            "portrait": "face",
            "qr_code": "machine_code",
            "qrcode": "machine_code",
            "barcode": "machine_code",
            "id_card": "identity_document",
            "passport": "identity_document",
            "driver_license": "identity_document",
            "hk_macau_permit": "identity_document",
            "employee_badge": "identity_document",
            "medical_wristband": "identity_document",
            "bank_card": "payment_card",
            "license_plate": "vehicle_plate",
            "receipt": "logistics_or_receipt",
            "shipping_label": "logistics_or_receipt",
            "fingerprint": "biometric",
            "palmprint": "biometric",
            "mobile_screen": "screen",
            "monitor_screen": "screen",
            "whiteboard": "display_surface",
            "sticky_note": "display_surface",
            "physical_key": "physical_key",
            "signature": "handwritten_mark",
            "handwriting": "handwritten_mark",
            "approval_mark": "handwritten_mark",
        }

        def _target_family(box: BoundingBox) -> str:
            box_type = _norm_type(box.type)
            return target_families.get(box_type, box_type)

        def _same_semantic_target(a: BoundingBox, b: BoundingBox) -> bool:
            """Only spatially dedupe boxes that describe the same target family.

            OCR text spans and visual feature regions can
            validly overlap on document pages. Spatial overlap alone is therefore
            not enough evidence for dedupe; the semantic target family must also
            match.
            """
            return _target_family(a) == _target_family(b)

        same_line_text_targets = {
            "person",
            "name",
            "姓名",
            "人名",
            "age",
            "gender",
            "date",
            "time",
            "birth_date",
            "org",
            "organization",
            "institution_name",
            "company_name",
            "government_agency",
            "work_unit",
            "department_name",
            "project_name",
            "case_number",
        }

        def _vertical_overlap_ratio(a: BoundingBox, b: BoundingBox) -> float:
            y1 = max(a.y, b.y)
            y2 = min(a.y + a.height, b.y + b.height)
            if y2 <= y1:
                return 0.0
            return (y2 - y1) / max(1e-6, min(a.height, b.height))

        def _same_text_line_duplicate(a: BoundingBox, b: BoundingBox) -> bool:
            if a.page != b.page or not _same_semantic_target(a, b):
                return False
            target = _target_family(a)
            if target not in same_line_text_targets:
                return False
            text = _compact_text(a.text)
            if not text or text != _compact_text(b.text):
                return False
            if _vertical_overlap_ratio(a, b) < 0.55:
                return False
            if self._calculate_smaller_overlap(a, b) >= 0.25:
                return True
            same_center_line = abs((a.y + a.height / 2) - (b.y + b.height / 2)) <= max(a.height, b.height) * 0.65
            if not same_center_line:
                return False
            return len(text) <= 6 or len(text) >= 4

        def _ocr_box_rank(box: BoundingBox) -> tuple[int, int, int, float]:
            detail = str(box.source_detail or "").lower()
            detail_rank = (
                3
                if "form_field_ocr" in detail
                else 2
                if "text_match" in detail
                else 1
                if "visual_line" in detail or "table" in detail
                else 0
            )
            text = _compact_text(box.text)
            odd_chars = sum(1 for char in text if char in "'`’\"?？")
            if _norm_type(box.type) in {"person", "name", "姓名", "人名"}:
                return (detail_rank, -odd_chars, -int((box.width * box.height) * 1_000_000), -len(text))
            return (detail_rank, -odd_chars, min(len(text), 24), -(box.width * box.height))

        def _dedupe_ocr_same_target_boxes(items: list[BoundingBox]) -> list[BoundingBox]:
            kept: list[BoundingBox] = []
            for candidate in sorted(items, key=lambda item: (item.page, _target_family(item), item.x, item.y)):
                duplicate_index: int | None = None
                for index, existing in enumerate(kept):
                    if existing.page != candidate.page or not _same_semantic_target(candidate, existing):
                        continue
                    if (
                        self._calculate_iou(candidate, existing) > iou_threshold
                        or self._calculate_smaller_overlap(candidate, existing) >= 0.72
                        or _same_text_line_duplicate(candidate, existing)
                    ):
                        duplicate_index = index
                        break
                if duplicate_index is None:
                    kept.append(candidate)
                    continue
                existing = kept[duplicate_index]
                if _ocr_box_rank(candidate) > _ocr_box_rank(existing):
                    kept[duplicate_index] = candidate
            return kept

        ocr_boxes = _dedupe_ocr_same_target_boxes(ocr_boxes)
        signature_boxes = [b for b in other_boxes if _is_signature_box(b)]
        visual_signature_boxes = [b for b in signature_boxes if b.source == "visual_features"]
        suppressed_ocr_ids: set[str] = set()
        enhanced_signatures: dict[str, BoundingBox] = {}

        for ocr in ocr_boxes:
            if not _is_signature_box(ocr):
                continue
            for sig in visual_signature_boxes:
                if sig.page != ocr.page:
                    continue
                vertical_center_gap = abs((sig.y + sig.height / 2) - (ocr.y + ocr.height / 2))
                horizontal_gap = max(sig.x - (ocr.x + ocr.width), ocr.x - (sig.x + sig.width), 0.0)
                tiny_ocr_anchor = ocr.height < 0.012 or (ocr.width * ocr.height) < 0.0005
                if (
                    self._calculate_iou(sig, ocr) > 0.05
                    or self._calculate_smaller_overlap(sig, ocr) >= 0.35
                    or (tiny_ocr_anchor and vertical_center_gap <= 0.045 and horizontal_gap <= 0.070)
                ):
                    suppressed_ocr_ids.add(ocr.id)
                    break

        for sig in signature_boxes:
            evidence: list[str] = []
            for ocr in ocr_boxes:
                if not _is_ocr_name_like(ocr):
                    continue
                if (
                    self._calculate_iou(sig, ocr) > 0.05
                    or self._calculate_smaller_overlap(sig, ocr) >= 0.35
                ):
                    suppressed_ocr_ids.add(ocr.id)
                    text = _compact_text(ocr.text)
                    if text and text not in evidence:
                        evidence.append(text)
            if evidence:
                base_text = _compact_text(sig.text)
                merged_text = base_text if base_text and base_text != _compact_text(sig.type) else "签字"
                enhanced_signatures[sig.id] = sig.model_copy(
                    update={
                        "text": f"{merged_text}（OCR: {'、'.join(evidence[:3])}）",
                        "source_detail": f"{sig.source_detail}:ocr_name_suppressed",
                    },
                )

        if suppressed_ocr_ids:
            logger.info(
                "DEDUP suppressed %d OCR name boxes covered by visual feature signature",
                len(suppressed_ocr_ids),
            )

        ocr_boxes = [b for b in ocr_boxes if b.id not in suppressed_ocr_ids]
        other_boxes = [enhanced_signatures.get(b.id, b) for b in other_boxes]
        result = list(ocr_boxes)

        def _overlaps_any(
            candidate: BoundingBox,
            existing: list[BoundingBox],
            *,
            require_same_visual_target: bool = False,
        ) -> bool:
            """Return whether candidate overlaps any existing box above threshold."""
            cx_end = candidate.x + candidate.width
            for eb in existing:
                # Skip boxes that cannot overlap on the x axis.
                if eb.x > cx_end or eb.x + eb.width < candidate.x:
                    continue
                if require_same_visual_target and not _same_semantic_target(candidate, eb):
                    continue
                if (
                    self._calculate_iou(candidate, eb) > iou_threshold
                    or self._calculate_smaller_overlap(candidate, eb) >= 0.72
                ):
                    return True
            return False

        visual_boxes.sort(key=lambda b: b.x)
        for visual_box in visual_boxes:
            if _overlaps_any(visual_box, ocr_boxes, require_same_visual_target=True):
                logger.debug("DEDUP visual feature '%s' overlaps same visual OCR box, skipping", visual_box.type)
            else:
                result.append(visual_box)

        other_boxes.sort(key=lambda b: b.x)
        for other_box in other_boxes:
            if not _overlaps_any(other_box, result, require_same_visual_target=True):
                result.append(other_box)

        removed_count = len(boxes) - len(result)
        if removed_count > 0:
            logger.info("DEDUP removed %d duplicate boxes", removed_count)

        return result

    async def _detect_with_pdf_text_layer(
        self,
        file_path: str,
        page: int,
        pipeline_types: list = None,
    ) -> tuple[list[BoundingBox], str | None]:
        text_layer_start = time.perf_counter()
        blocks, width, height = await self.file_parser.get_pdf_page_text_blocks(file_path, page)
        text_chars = sum(len(str(block.text or "").strip()) for block in blocks)
        self.last_pdf_text_layer_duration_ms = _elapsed_ms(text_layer_start)
        self.last_pdf_text_layer_stats = {
            "block_count": len(blocks),
            "char_count": text_chars,
            "page_width": width,
            "page_height": height,
            "cache_hit": bool(
                getattr(self.file_parser, "last_pdf_page_text_blocks_cache_hit", False)
            ),
        }
        if text_chars < int(settings.PDF_TEXT_LAYER_MIN_CHARS):
            raise ValueError(
                f"sparse native text layer ({text_chars} chars < {settings.PDF_TEXT_LAYER_MIN_CHARS})"
            )

        regions = await self.ocr_has_service.detect_from_text_blocks(blocks, pipeline_types)
        if getattr(self.ocr_has_service, "last_duration_ms", None):
            self.ocr_has_service.last_duration_ms["pdf_text_layer_extract"] = int(
                self.last_pdf_text_layer_duration_ms
            )

        bounding_boxes = []
        for index, region in enumerate(regions):
            if not self._should_keep_ocr_has_region(region.entity_type, region.text):
                logger.debug("Skipping PDF text-layer semantic false positive: %s %s", region.entity_type, region.text)
                continue
            left, top, box_width, box_height = self._expand_ocr_region(
                region.left,
                region.top,
                region.width,
                region.height,
                width,
                height,
                region.entity_type,
            )
            bbox = BoundingBox(
                id=f"pdf_text_{index}_{uuid.uuid4().hex[:8]}",
                x=left / width,
                y=top / height,
                width=box_width / width,
                height=box_height / height,
                type=region.entity_type,
                text=region.text,
                page=page,
                confidence=float(getattr(region, "confidence", 1.0) or 1.0),
                source="ocr_has",
                source_detail="pdf_text_layer",
                evidence_source="ocr_has",
            )
            bounding_boxes.append(bbox)

        return bounding_boxes, None

    async def _detect_with_ocr_has(
        self,
        image_data: bytes,
        page: int,
        pipeline_types: list = None,
        draw_result: bool = True,
    ) -> tuple[list[BoundingBox], str | None]:
        regions, result_image_base64 = await self.ocr_has_service.detect_and_draw(
            image_data,
            vision_types=pipeline_types,
            draw_result=draw_result,
        )

        img = Image.open(io.BytesIO(image_data))
        img = ImageOps.exif_transpose(img)
        width, height = img.size

        bounding_boxes = []
        for i, region in enumerate(regions):
            normalized_region_type = self._norm_box_type(region.entity_type)
            is_ocr_visual_seal = normalized_region_type in {"seal", "official_seal", "stamp"}
            if not self._should_keep_ocr_has_region(region.entity_type, region.text):
                logger.debug("Skipping OCR-HaS semantic false positive: %s %s", region.entity_type, region.text)
                continue
            if is_page_edge_ocr_artifact(
                region.left,
                region.top,
                region.width,
                region.height,
                width,
                height,
                region.entity_type,
            ):
                logger.debug("Skipping OCR region on page edge artifact: %s %s", region.entity_type, region.text)
                continue
            if not region_has_visible_ink(img, region.left, region.top, region.width, region.height):
                logger.debug("Skipping OCR region on blank/low-ink area: %s %s", region.entity_type, region.text)
                continue
            if is_ocr_visual_seal:
                left = max(0, min(width - 1, int(region.left)))
                top = max(0, min(height - 1, int(region.top)))
                right = max(left + 1, min(width, int(region.left + region.width)))
                bottom = max(top + 1, min(height, int(region.top + region.height)))
                box_width = right - left
                box_height = bottom - top
                bounding_boxes.append(
                    BoundingBox(
                        id=f"ocr_seal_{i}_{uuid.uuid4().hex[:8]}",
                        x=left / width,
                        y=top / height,
                        width=box_width / width,
                        height=box_height / height,
                        type="official_seal",
                        text=SLUG_TO_NAME_ZH.get("official_seal", "official_seal"),
                        page=page,
                        confidence=float(getattr(region, "confidence", 0.9) or 0.9),
                        source="visual_features",
                        source_detail=str(getattr(region, "source", "") or "paddleocr_vl:seal"),
                        evidence_source="ocr_has",
                    )
                )
                continue
            refined_left, refined_top, refined_width, refined_height = self._refine_ocr_region_to_ink(
                img,
                region.left,
                region.top,
                region.width,
                region.height,
            )
            left, top, box_width, box_height = self._expand_ocr_region(
                refined_left,
                refined_top,
                refined_width,
                refined_height,
                width,
                height,
                region.entity_type,
            )
            bbox = BoundingBox(
                id=f"ocr_{i}_{uuid.uuid4().hex[:8]}",
                x=left / width,
                y=top / height,
                width=box_width / width,
                height=box_height / height,
                type=region.entity_type,
                text=region.text,
                page=page,
                confidence=float(getattr(region, "confidence", 1.0) or 1.0),
                source="ocr_has",
                source_detail=str(getattr(region, "source", "") or "ocr_has"),
                evidence_source="ocr_has",
            )
            bounding_boxes.append(bbox)

        return bounding_boxes, result_image_base64

    @staticmethod
    def _should_keep_ocr_has_region(entity_type: str, text: str | None) -> bool:
        """Keep non-empty HaS Text results; semantic filtering belongs to HaS."""
        return bool(str(text or "").strip())

    @staticmethod
    def _true_runs(values: np.ndarray) -> list[tuple[int, int]]:
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

    @staticmethod
    def _remove_ocr_rule_lines(mask: np.ndarray) -> np.ndarray:
        if mask.ndim != 2 or mask.size == 0:
            return mask

        cleaned = mask.copy()
        height, width = cleaned.shape
        row_run_min = max(24, int(width * 0.38))
        col_run_min = max(24, int(height * 0.55))

        for row in range(height):
            for start, end in VisionService._true_runs(mask[row, :]):
                if end - start + 1 >= row_run_min:
                    cleaned[max(0, row - 1) : min(height, row + 2), start : end + 1] = False

        column_source = cleaned.copy()
        for col in range(width):
            for start, end in VisionService._true_runs(column_source[:, col]):
                if end - start + 1 >= col_run_min:
                    cleaned[start : end + 1, max(0, col - 1) : min(width, col + 2)] = False
        return cleaned

    @staticmethod
    def _refine_ocr_region_to_ink(
        image: Image.Image,
        left: int,
        top: int,
        region_width: int,
        region_height: int,
    ) -> tuple[int, int, int, int]:
        page_width, page_height = image.size
        x1 = max(0, min(page_width, int(left)))
        y1 = max(0, min(page_height, int(top)))
        x2 = max(x1 + 1, min(page_width, int(left + region_width)))
        y2 = max(y1 + 1, min(page_height, int(top + region_height)))
        crop = image.crop((x1, y1, x2, y2)).convert("RGB")
        arr = np.asarray(crop).astype(np.int16, copy=False)
        red = arr[:, :, 0]
        green = arr[:, :, 1]
        blue = arr[:, :, 2]
        gray = (red * 30 + green * 59 + blue * 11) / 100
        span = arr.max(axis=2) - arr.min(axis=2)
        red_mark = (red > 120) & (red > green * 1.18) & (red > blue * 1.12)
        mask = ((gray < 122) | ((gray < 168) & (span < 55))) & ~red_mark
        mask = VisionService._remove_ocr_rule_lines(mask)

        ys, xs = np.where(mask)
        if len(xs) < max(8, int(mask.size * 0.002)):
            return x1, y1, max(1, x2 - x1), max(1, y2 - y1)

        pad = max(1, min(4, int(min(region_width, region_height) * 0.04)))
        nx1 = max(x1, x1 + int(xs.min()) - pad)
        nx2 = min(x2, x1 + int(xs.max()) + 1 + pad)
        ny1 = max(y1, y1 + int(ys.min()) - pad)
        ny2 = min(y2, y1 + int(ys.max()) + 1 + pad)

        if nx2 <= nx1 or ny2 <= ny1:
            return x1, y1, max(1, x2 - x1), max(1, y2 - y1)
        if nx2 - nx1 < max(6, min(region_width, region_height) * 0.18):
            return x1, y1, max(1, x2 - x1), max(1, y2 - y1)
        return nx1, ny1, nx2 - nx1, ny2 - ny1

    @staticmethod
    def _expand_ocr_region(
        left: int,
        top: int,
        region_width: int,
        region_height: int,
        page_width: int,
        page_height: int,
        entity_type: str,
    ) -> tuple[int, int, int, int]:
        horizontal_ratio = {
            "PHONE": 0.04,
            "BANK_ACCOUNT": 0.045,
            "ACCOUNT_NUMBER": 0.045,
            "BANK_CARD": 0.045,
            "ID_CARD": 0.014,
            "AMOUNT": 0.008,
            "PERSON": 0.02,
            "NICKNAME": 0.02,
            "PROPERTY": 0.04,
            "ADDRESS": 0.008,
            "ORG": 0.02,
            "COMPANY": 0.02,
            "DATE": 0.008,
        }.get(entity_type, 0.006)
        pad_x = max(3, int(page_width * horizontal_ratio))
        if region_width <= max(region_height * 5, page_width * 0.12):
            geometry_pad = max(3, min(int(region_width * 0.10), int(region_height * 0.35)))
            pad_x = min(pad_x, geometry_pad)
        pad_y = max(2, int(region_height * 0.25))
        x1 = max(0, int(left) - pad_x)
        y1 = max(0, int(top) - pad_y)
        x2 = min(page_width, int(left + region_width) + pad_x)
        y2 = min(page_height, int(top + region_height) + pad_y)
        return x1, y1, max(1, x2 - x1), max(1, y2 - y1)

    async def _detect_with_visual_features(
        self,
        image_data: bytes,
        page: int,
        pipeline_types: list = None,
        draw_result: bool = True,
    ) -> tuple[list[BoundingBox], str | None]:
        fixed_types, checklist_types = self._split_visual_feature_types(pipeline_types)
        paddle_seal_boxes, paddle_seal_duration_ms = await self._detect_official_seals_with_paddle(
            image_data,
            page,
            fixed_types,
        )
        locate_boxes, stage_duration_ms = await self.visual_grounding.detect_categories(
            image_data,
            page,
            fixed_types,
        )
        checklist_boxes: list[BoundingBox] = []
        checklist_duration_ms: dict[str, int] = {}
        if checklist_types:
            checklist_boxes, checklist_duration_ms = await self.visual_grounding.detect_checklist(
                image_data,
                page,
                checklist_types,
            )
        boxes = [*paddle_seal_boxes, *locate_boxes, *checklist_boxes]
        self.last_visual_feature_stage_duration_ms = {
            **stage_duration_ms,
            **{f"custom_{key}": value for key, value in checklist_duration_ms.items()},
            "paddle_seal": paddle_seal_duration_ms,
            "total": (
                int(stage_duration_ms.get("total", 0) or 0)
                + int(checklist_duration_ms.get("total", 0) or 0)
                + paddle_seal_duration_ms
            ),
        }
        if draw_result:
            img = Image.open(io.BytesIO(image_data))
            img = ImageOps.exif_transpose(img)
            return boxes, self._draw_boxes_on_image(img, boxes)
        return boxes, None

    @staticmethod
    def _split_visual_feature_types(pipeline_types: list | None) -> tuple[list | None, list]:
        if pipeline_types is None:
            return None, []
        fixed: list = []
        checklist: list = []
        for item in pipeline_types:
            slug = normalize_visual_slug(getattr(item, "id", item))
            if slug in LOCATE_ANYTHING_VISUAL_SLUGS or slug in OCR_FALLBACK_ONLY_VISUAL_SLUGS:
                fixed.append(item)
            else:
                checklist.append(item)
        return fixed, checklist

    @staticmethod
    def _visual_slug_requested(pipeline_types: list | None, slug: str) -> bool:
        target = normalize_visual_slug(slug)
        if pipeline_types is None:
            return True
        return any(normalize_visual_slug(getattr(item, "id", item)) == target for item in pipeline_types)

    async def _detect_official_seals_with_paddle(
        self,
        image_data: bytes,
        page: int,
        pipeline_types: list | None,
    ) -> tuple[list[BoundingBox], int]:
        if not self._visual_slug_requested(pipeline_types, "official_seal"):
            return [], 0

        start = time.perf_counter()
        img = Image.open(io.BytesIO(image_data))
        img = ImageOps.exif_transpose(img).convert("RGB")
        page_width, page_height = img.size
        if page_width <= 0 or page_height <= 0:
            return [], _elapsed_ms(start)

        def _run() -> list:
            from app.services.ocr_service import ocr_service

            return ocr_service.extract_text_boxes(image_data)

        try:
            items = await asyncio.to_thread(_run)
        except Exception as exc:
            logger.warning("PaddleOCR-VL seal detection failed: %s", exc)
            return [], _elapsed_ms(start)

        boxes: list[BoundingBox] = []
        for index, item in enumerate(items):
            label = self._norm_box_type(str(getattr(item, "label", "") or ""))
            text = str(getattr(item, "text", "") or "").strip()
            compact_text = "".join(text.split())
            if label not in {"seal", "official_seal", "stamp"} and compact_text not in {"[公章]", "公章", "印章"}:
                continue
            left = max(0, min(page_width - 1, int(round(float(getattr(item, "x", 0) or 0) * page_width))))
            top = max(0, min(page_height - 1, int(round(float(getattr(item, "y", 0) or 0) * page_height))))
            right = max(
                left + 1,
                min(page_width, int(round((float(getattr(item, "x", 0) or 0) + float(getattr(item, "width", 0) or 0)) * page_width))),
            )
            bottom = max(
                top + 1,
                min(page_height, int(round((float(getattr(item, "y", 0) or 0) + float(getattr(item, "height", 0) or 0)) * page_height))),
            )
            box_width = right - left
            box_height = bottom - top
            norm_w = box_width / page_width
            norm_h = box_height / page_height
            area = norm_w * norm_h
            if norm_w < 0.006 or norm_h < 0.006 or area > 0.45:
                continue
            if not region_has_visible_ink(img, left, top, box_width, box_height):
                continue
            boxes.append(
                BoundingBox(
                    id=f"paddle_seal_{index}_{uuid.uuid4().hex[:8]}",
                    x=left / page_width,
                    y=top / page_height,
                    width=norm_w,
                    height=norm_h,
                    type="official_seal",
                    text=SLUG_TO_NAME_ZH.get("official_seal", "official_seal"),
                    page=page,
                    confidence=max(0.0, min(1.0, float(getattr(item, "confidence", 0.9) or 0.9))),
                    source="visual_features",
                    source_detail="paddleocr_vl:seal",
                    evidence_source="ocr_has",
                )
            )
        elapsed = _elapsed_ms(start)
        logger.info("PaddleOCR-VL seal stage parsed %d boxes in %.2fs", len(boxes), elapsed / 1000)
        return boxes, elapsed

    @staticmethod
    def _expand_normalized_visual_box(
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        pad_x: float,
        pad_y: float,
    ) -> tuple[float, float, float, float]:
        x1 = max(0.0, x - pad_x)
        y1 = max(0.0, y - pad_y)
        x2 = min(1.0, x + width + pad_x)
        y2 = min(1.0, y + height + pad_y)
        return x1, y1, max(0.0, x2 - x1), max(0.0, y2 - y1)

    @staticmethod
    def _clamp_normalized_visual_box(
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> tuple[float, float, float, float]:
        x1 = max(0.0, min(1.0, x))
        y1 = max(0.0, min(1.0, y))
        x2 = max(0.0, min(1.0, x + width))
        y2 = max(0.0, min(1.0, y + height))
        return x1, y1, max(0.0, x2 - x1), max(0.0, y2 - y1)

    @staticmethod
    def _expand_fallback_seal_box(
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> tuple[float, float, float, float]:
        """Use restrained padding for local seal fallback boxes.

        The fallback detector already tightens to visible ink and adds a small
        pixel pad. A second large API-layer pad makes side seam stamps and
        corner seals cover nearby text. Keep only a small safety margin here.
        """
        aspect = width / max(height, 1e-6)
        edge_or_seam = x <= 0.04 or x + width >= 0.96 or y <= 0.04 or y + height >= 0.96
        narrow_seam = edge_or_seam and (width <= 0.07 or aspect < 0.35)
        pad_x = 0.004 if narrow_seam else 0.006
        pad_y = 0.003 if narrow_seam else 0.004
        return VisionService._expand_normalized_visual_box(
            x,
            y,
            width,
            height,
            pad_x=pad_x,
            pad_y=pad_y,
        )

    @staticmethod
    def _should_keep_fallback_seal_box(x: float, y: float, width: float, height: float) -> bool:
        area = width * height
        if area >= 0.00035:
            return True
        right = x + width
        bottom = y + height
        touches_edge = x <= 0.025 or y <= 0.025 or right >= 0.975 or bottom >= 0.975
        return touches_edge and max(width, height) >= 0.08 and min(width, height) >= 0.006

    @staticmethod
    def _fallback_seal_warnings(
        x: float,
        y: float,
        width: float,
        height: float,
        confidence: float = 1.0,
    ) -> list[str]:
        warnings = ["fallback_detector"]
        right = x + width
        bottom = y + height
        if x <= 0.04 or y <= 0.04 or right >= 0.96 or bottom >= 0.96:
            warnings.append("edge_seal")
        if x <= 0.025 or right >= 0.975 or (width <= 0.07 and height >= 0.10):
            warnings.append("seam_seal")
        if confidence < 0.70:
            warnings.append("low_confidence")
        return warnings

    @staticmethod
    def _refine_normalized_official_seal_box(
        image: Image.Image,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> tuple[float, float, float, float]:
        """Tighten model seal boxes around visible red ink when possible.

        LocateAnything and OCR-derived seal boxes can be broader than the
        visible ink. Red seals have a strong color signal, so we shrink only
        when enough red pixels are present inside the model box. If the crop is
        grayscale, copied, or ambiguous, keep the original box and let the
        dedicated fallback detectors handle it.
        """
        img = ImageOps.exif_transpose(image).convert("RGB")
        page_width, page_height = img.size
        if page_width <= 0 or page_height <= 0 or width <= 0 or height <= 0:
            return x, y, width, height

        x1 = max(0, min(page_width - 1, int(x * page_width)))
        y1 = max(0, min(page_height - 1, int(y * page_height)))
        x2 = max(x1 + 1, min(page_width, int((x + width) * page_width)))
        y2 = max(y1 + 1, min(page_height, int((y + height) * page_height)))
        crop = img.crop((x1, y1, x2, y2))
        raw = crop.tobytes()
        red_xs: list[int] = []
        red_ys: list[int] = []
        crop_width, crop_height = crop.size
        for py in range(crop_height):
            row_offset = py * crop_width * 3
            for px in range(crop_width):
                idx = row_offset + px * 3
                r, g, b = raw[idx], raw[idx + 1], raw[idx + 2]
                if (
                    r >= 115
                    and r - g >= 30
                    and r - b >= 30
                    and g <= max(145, int(r * 0.82))
                    and b <= max(145, int(r * 0.82))
                ):
                    red_xs.append(px)
                    red_ys.append(py)

        red_pixels = len(red_xs)
        crop_area = max(1, crop_width * crop_height)
        if red_pixels < max(24, int(crop_area * 0.006)):
            return x, y, width, height

        rx1, rx2 = min(red_xs), max(red_xs)
        ry1, ry2 = min(red_ys), max(red_ys)
        refined_width = rx2 - rx1 + 1
        refined_height = ry2 - ry1 + 1
        if refined_width < max(8, crop_width * 0.12) or refined_height < max(8, crop_height * 0.12):
            return x, y, width, height

        pad = max(3, int(max(refined_width, refined_height) * 0.08))
        nx1 = max(0, x1 + rx1 - pad)
        ny1 = max(0, y1 + ry1 - pad)
        nx2 = min(page_width, x1 + rx2 + pad + 1)
        ny2 = min(page_height, y1 + ry2 + pad + 1)
        if nx2 <= nx1 or ny2 <= ny1:
            return x, y, width, height

        return (
            nx1 / page_width,
            ny1 / page_height,
            (nx2 - nx1) / page_width,
            (ny2 - ny1) / page_height,
        )

    def _draw_boxes_on_image(
        self,
        image: Image.Image,
        bounding_boxes: list[BoundingBox],
    ) -> str:

        draw_image = image.copy()
        draw = ImageDraw.Draw(draw_image)
        width, height = draw_image.size

        font = None
        font_paths = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simsun.ttc",
        ]
        try:
            from PIL import ImageFont

            for fp in font_paths:
                if os.path.exists(fp):
                    font = ImageFont.truetype(fp, 16)
                    break
        except OSError:
            pass

        type_colors = {
            "face": "#EF4444",
            "qr_code": "#10B981",
            "official_seal": "#DC2626",
            "id_card": "#F97316",
            "bank_card": "#EC4899",
            "PERSON": "#3B82F6",
            "ID_CARD": "#EF4444",
        }

        for bbox in bounding_boxes:
            x1 = int(bbox.x * width)
            y1 = int(bbox.y * height)
            x2 = int((bbox.x + bbox.width) * width)
            y2 = int((bbox.y + bbox.height) * height)

            color = type_colors.get(bbox.type, "#6B7280")

            draw.rectangle([x1, y1, x2, y2], outline=color, width=2)

            label_zh = bbox.text or VISUAL_TYPE_LABELS_ZH.get(bbox.type, bbox.type)
            if len(label_zh) > 12:
                label_zh = label_zh[:12] + "..."
            label = f"{label_zh}"
            if font:
                draw.text((x1, max(0, y1 - 20)), label, fill=color, font=font)
            else:
                draw.text((x1, max(0, y1 - 12)), label, fill=color)

        buffer = io.BytesIO()
        draw_image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    @staticmethod
    def _hex_to_rgb(fill_color: str) -> tuple[int, int, int]:
        h = (fill_color or "#000000").strip().lstrip("#")
        if len(h) == 6:
            try:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            except ValueError:
                pass
        return (0, 0, 0)

    def _apply_region_effect(
        self,
        img: Image.Image,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        image_method: str,
        strength: int,
        fill_color: str,
    ) -> None:
        """Apply the configured redaction fill to rectangular image regions."""
        W, H = img.size
        x1 = max(0, min(W, x1))
        y1 = max(0, min(H, y1))
        x2 = max(0, min(W, x2))
        y2 = max(0, min(H, y2))
        if x2 <= x1 or y2 <= y1:
            return
        s = max(1, min(100, strength))
        roi = img.crop((x1, y1, x2, y2))
        w, h = roi.size
        if w < 1 or h < 1:
            return

        if image_method == "fill":
            rgb = self._hex_to_rgb(fill_color)
            draw = ImageDraw.Draw(img)
            draw.rectangle([x1, y1, x2, y2], fill=rgb)
            return

        if image_method == "mosaic":
            min_edge = min(w, h)
            # Text detections are often long but very short rectangles. The old
            # 2px floor left small characters readable at the default strength,
            # so keep a real privacy floor even for thin OCR boxes.
            block = max(8, int(4 + (s / 100.0) * min_edge * 0.6))
            block = min(block, max(1, min_edge))
            small_w = max(1, w // block)
            small_h = max(1, h // block)
            # Downsample by area before expanding. Nearest-neighbor downsampling
            # can sample the white paper around thin red seal strokes and make
            # the stamp look erased instead of explicitly mosaicked.
            small = roi.resize((small_w, small_h), Image.Resampling.BOX)
            mosaic = small.resize((w, h), Image.Resampling.NEAREST)
            img.paste(mosaic, (x1, y1))
            return

        if image_method == "blur":
            radius = max(1, int(1 + (s / 100.0) * 24))
            blurred = roi.filter(ImageFilter.GaussianBlur(radius=radius))
            img.paste(blurred, (x1, y1))
            return

        rgb = self._hex_to_rgb(fill_color)
        draw = ImageDraw.Draw(img)
        draw.rectangle([x1, y1, x2, y2], fill=rgb)

    def _apply_box_effect(
        self,
        img: Image.Image,
        bbox: BoundingBox,
        page_width: int,
        page_height: int,
        image_method: str,
        strength: int,
        fill_color: str,
    ) -> None:
        x1 = int(bbox.x * page_width)
        y1 = int(bbox.y * page_height)
        x2 = int((bbox.x + bbox.width) * page_width)
        y2 = int((bbox.y + bbox.height) * page_height)
        self._apply_region_effect(img, x1, y1, x2, y2, image_method, strength, fill_color)

    async def apply_redaction(
        self,
        file_path: str,
        file_type: FileType,
        bounding_boxes: list[BoundingBox],
        output_path: str,
        image_method: str = "fill",
        strength: int = 75,
        fill_color: str = "#000000",
    ) -> str:
        if file_type == FileType.IMAGE:
            return await self._redact_image(
                file_path, bounding_boxes, output_path, image_method, strength, fill_color
            )
        if file_type in [FileType.PDF, FileType.PDF_SCANNED]:
            return await self._redact_pdf(
                file_path, bounding_boxes, output_path, image_method, strength, fill_color
            )
        raise ValueError(f"不支持的文件类型进行匿名化: {file_type}")

    async def _redact_image(
        self,
        file_path: str,
        bounding_boxes: list[BoundingBox],
        output_path: str,
        image_method: str,
        strength: int,
        fill_color: str,
    ) -> str:
        image = Image.open(file_path).convert("RGB")
        width, height = image.size

        for bbox in bounding_boxes:
            if not bbox.selected:
                continue
            self._apply_box_effect(image, bbox, width, height, image_method, strength, fill_color)

        image.save(output_path)
        return output_path

    async def _redact_pdf(
        self,
        file_path: str,
        bounding_boxes: list[BoundingBox],
        output_path: str,
        image_method: str,
        strength: int,
        fill_color: str,
    ) -> str:
        import fitz

        doc = fitz.open(file_path)
        new_doc = fitz.open()
        mat = fitz.Matrix(2.0, 2.0)

        for page_index in range(len(doc)):
            page = doc[page_index]
            page_no = page_index + 1
            page_boxes = [b for b in bounding_boxes if b.selected and (b.page or 1) == page_no]
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            for bbox in page_boxes:
                self._apply_box_effect(img, bbox, pix.width, pix.height, image_method, strength, fill_color)
            buf = io.BytesIO()
            # Scanned PDFs are redacted by rasterizing each page and applying
            # the selected explicit masking effect to each selected region.
            # Embedding those page rasters as PNGs bloats delivery PDFs badly;
            # high-quality JPEG keeps exported packages practical for real scans.
            img.save(buf, format="JPEG", quality=settings.REDACTION_PDF_JPEG_QUALITY, optimize=True)
            buf.seek(0)
            new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, stream=buf.read())

        doc.close()
        new_doc.save(output_path, garbage=4, deflate=True, clean=True)
        new_doc.close()

        return output_path

    async def preview_redaction(
        self,
        file_path: str,
        file_type: FileType,
        bounding_boxes: list[BoundingBox],
        page: int = 1,
        image_method: str = "fill",
        strength: int = 75,
        fill_color: str = "#000000",
    ) -> bytes:
        if file_type == FileType.IMAGE:
            image_data = await self.file_parser.read_image(file_path)
        else:
            image_data = await self.file_parser.get_pdf_page_image(file_path, page)

        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        width, height = image.size

        page_boxes = [b for b in bounding_boxes if b.page == page and b.selected]

        for bbox in page_boxes:
            self._apply_box_effect(
                image,
                bbox,
                width,
                height,
                image_method,
                max(1, min(100, strength)),
                fill_color,
            )

        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)

        return output.getvalue()


