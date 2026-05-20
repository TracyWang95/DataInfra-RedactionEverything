"""
瑙嗚璇嗗埆鏈嶅姟
- OCR + HaS锛氭枃瀛楃被
- HaS Image锛?081 YOLO 寰湇鍔★紝闅愮鍖哄煙鍒嗗壊
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

import httpx

logger = logging.getLogger(__name__)

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.core.config import settings
from app.core.has_image_categories import (
    SLUG_TO_NAME_ZH,
    filter_has_image_model_slugs,
    is_has_image_model_slug,
    normalize_visual_slug,
)
from app.core.has_image_client import detect_privacy_regions
from app.models.schemas import BoundingBox, FileType
from app.services.file_parser import FileParser
from app.services.hybrid_vision_service import get_hybrid_vision_service
from app.services.vision.ocr_artifact_filter import (
    is_page_edge_ocr_artifact,
    region_has_visible_ink,
)
from app.services.vision.seal_detector import (
    detect_dark_seal_regions,
    detect_red_seal_regions,
)
from app.services.vlm_vision_service import VlmVisionService

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
    """瑙嗚璇嗗埆鏈嶅姟"""

    def __init__(self):
        self.file_parser = FileParser()
        self.hybrid_service = get_hybrid_vision_service()
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
        duration_ms: dict[str, int | dict[str, int]] = {"ocr_has": 0, "has_image": 0}
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
        if pipeline_mode == "has_image":
            image_data = await get_image_data()
            bounding_boxes, result_image_base64 = await self._detect_with_has_image(
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
        hybrid_service = getattr(self, "hybrid_service", None)
        if pipeline_mode == "ocr_has" and getattr(hybrid_service, "last_duration_ms", None):
            self.last_pipeline_status[pipeline_mode]["stage_duration_ms"] = dict(
                hybrid_service.last_duration_ms
            )
        elif pipeline_mode == "has_image" and getattr(self, "last_has_image_stage_duration_ms", None):
            self.last_pipeline_status[pipeline_mode]["stage_duration_ms"] = dict(
                self.last_has_image_stage_duration_ms
            )

        logger.info("Vision detect done (%s): %d regions", pipeline_mode, len(bounding_boxes))
        return bounding_boxes, result_image_base64

    async def detect_with_dual_pipeline(
        self,
        file_path: str,
        file_type: FileType,
        page: int = 1,
        ocr_has_types: list = None,
        has_image_types: list = None,
        vlm_types: list = None,
        include_result_image: bool = True,
    ) -> tuple[list[BoundingBox], str | None]:
        total_start = time.perf_counter()
        duration_ms: dict[str, int | dict[str, int]] = {"ocr_has": 0, "has_image": 0, "vlm": 0}
        self.last_has_image_stage_duration_ms = {}
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

        all_boxes: list[BoundingBox] = []
        pipeline_status: dict[str, dict] = {
            "ocr_has": {
                "ran": False,
                "skipped": not bool(ocr_has_types),
                "failed": False,
                "region_count": 0,
                "error": None,
                "duration_ms": 0,
            },
            "has_image": {
                "ran": False,
                "skipped": not bool(has_image_types),
                "failed": False,
                "region_count": 0,
                "error": None,
                "duration_ms": 0,
            },
            "vlm": {
                "ran": False,
                "skipped": not bool(vlm_types),
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
        if ocr_has_types:
            logger.info("Running OCR+HaS with %d types...", len(ocr_has_types))

            async def run_ocr_has_job():
                if (
                    file_type not in [FileType.PDF, FileType.PDF_SCANNED]
                    or not settings.PDF_TEXT_LAYER_VISION_ENABLED
                ):
                    return await invoke_detector(self._detect_with_ocr_has, page, ocr_has_types)

                async def attempt_pdf_text_layer() -> tuple[list[BoundingBox], str | None] | None:
                    if _should_skip_sparse_pdf_text_layer(file_path, file_type):
                        duration_ms["pdf_text_layer_skipped_sparse_file"] = True
                        return None
                    try:
                        return await self._detect_with_pdf_text_layer(file_path, page, ocr_has_types)
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
                return await invoke_detector(self._detect_with_ocr_has, page, ocr_has_types)

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

        if has_image_types:
            logger.info("Running HaS Image with %d types...", len(has_image_types))
            jobs.append(
                (
                    "has_image",
                    lambda: timed(
                        "has_image",
                        invoke_detector(self._detect_with_has_image, page, has_image_types),
                    ),
                )
            )
        else:
            logger.info("HaS Image skipped (no types enabled)")

        if vlm_types:
            logger.info("Running VLM with %d checklist types...", len(vlm_types))
            jobs.append(
                (
                    "vlm",
                    lambda: timed(
                        "vlm",
                        invoke_detector(self._detect_with_vlm, page, vlm_types),
                    ),
                )
            )
        else:
            logger.info("VLM skipped (no types enabled)")

        labels: list[str] = []
        results = []
        if not jobs:
            logger.info("No vision pipeline jobs enabled; returning empty results")
        elif settings.VISION_DUAL_PIPELINE_PARALLEL and len(jobs) > 1:
            if any(label == "vlm" for label, _factory in jobs):
                logger.info("Dual pipeline scheduling: parallel non-VLM, VLM sequential")
                non_vlm_jobs = [(label, factory) for label, factory in jobs if label != "vlm"]
                vlm_jobs = [(label, factory) for label, factory in jobs if label == "vlm"]
                labels = [label for label, _factory in non_vlm_jobs]
                tasks = [asyncio.create_task(factory()) for _label, factory in non_vlm_jobs]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for label, factory in vlm_jobs:
                    labels.append(label)
                    try:
                        results.append(await factory())
                    except Exception as exc:
                        results.append(exc)
            else:
                logger.info("Dual pipeline scheduling: parallel")
                labels = [label for label, _factory in jobs]
                tasks = [asyncio.create_task(factory()) for _label, factory in jobs]
                results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            logger.info("Dual pipeline scheduling: sequential")
            for label, factory in jobs:
                labels.append(label)
                try:
                    results.append(await factory())
                except Exception as exc:
                    results.append(exc)

        for label, result in zip(labels, results, strict=False):
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
                continue
            boxes, _ = result
            all_boxes.extend(boxes)
            status["region_count"] = len(boxes)
            if label == "ocr_has":
                hybrid_service = getattr(self, "hybrid_service", None)
                stage_duration_ms = dict(getattr(hybrid_service, "last_duration_ms", {}) or {})
                if stage_duration_ms:
                    status["stage_duration_ms"] = stage_duration_ms
            elif label == "has_image" and getattr(self, "last_has_image_stage_duration_ms", None):
                status["stage_duration_ms"] = dict(self.last_has_image_stage_duration_ms)
            logger.info("%s found %d regions", label, len(boxes))

        all_boxes = self._filter_visual_artifacts(all_boxes)
        all_boxes = self._deduplicate_boxes(all_boxes)

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
        filtered: list[BoundingBox] = []
        removed = 0
        for box in boxes:
            if self._is_scanner_mark_seal_artifact(box, machine_code_boxes) or self._is_signature_artifact(box, seal_boxes):
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
    def _norm_box_type(value: str | None) -> str:
        return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    def _is_scanner_mark_seal_artifact(
        self,
        box: BoundingBox,
        machine_code_boxes: list[BoundingBox],
    ) -> bool:
        if self._norm_box_type(box.type) not in {"official_seal", "seal", "stamp"}:
            return False
        if box.source != "has_image" or not str(box.source_detail or "").startswith("local_"):
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
    ) -> bool:
        if self._norm_box_type(box.type) not in {"signature", "handwriting", "approval_mark"}:
            return False
        if box.source != "vlm":
            return False
        # Printed text lines are usually very shallow; handwritten signatures
        # should have enough vertical stroke extent to be reviewed as a region.
        if box.height < 0.025:
            return True
        for seal in seal_boxes:
            if self._norm_box_type(seal.type) not in {"official_seal", "seal", "stamp"}:
                continue
            if self._calculate_smaller_overlap(box, seal) >= 0.25:
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
        hi_boxes = [b for b in boxes if b.source == "has_image"]
        other_boxes = [b for b in boxes if b.source not in ("ocr_has", "has_image")]

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

        signature_boxes = [b for b in other_boxes if _is_signature_box(b)]
        suppressed_ocr_ids: set[str] = set()
        enhanced_signatures: dict[str, BoundingBox] = {}

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
                "DEDUP suppressed %d OCR name boxes covered by VLM signature",
                len(suppressed_ocr_ids),
            )

        ocr_boxes = [b for b in ocr_boxes if b.id not in suppressed_ocr_ids]
        other_boxes = [enhanced_signatures.get(b.id, b) for b in other_boxes]
        result = list(ocr_boxes)

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

            OCR text spans, object detector regions, and VLM semantic regions can
            validly overlap on document pages. Spatial overlap alone is therefore
            not enough evidence for dedupe; the semantic target family must also
            match.
            """
            return _target_family(a) == _target_family(b)

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

        # 鎸?x 鎺掑簭鍔犻€熷壀鏋?        hi_boxes.sort(key=lambda b: b.x)
        for hi_box in hi_boxes:
            if _overlaps_any(hi_box, ocr_boxes, require_same_visual_target=True):
                logger.debug("DEDUP HaS-Image '%s' overlaps same visual OCR box, skipping", hi_box.type)
            else:
                result.append(hi_box)

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

        regions = await self.hybrid_service.detect_from_text_blocks(blocks, pipeline_types)
        if getattr(self.hybrid_service, "last_duration_ms", None):
            self.hybrid_service.last_duration_ms["pdf_text_layer_extract"] = int(
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
        regions, result_image_base64 = await self.hybrid_service.detect_and_draw(
            image_data,
            vision_types=pipeline_types,
            draw_result=draw_result,
        )

        img = Image.open(io.BytesIO(image_data))
        img = ImageOps.exif_transpose(img)
        width, height = img.size

        bounding_boxes = []
        for i, region in enumerate(regions):
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
        pad_y = max(2, int(region_height * 0.25))
        x1 = max(0, int(left) - pad_x)
        y1 = max(0, int(top) - pad_y)
        x2 = min(page_width, int(left + region_width) + pad_x)
        y2 = min(page_height, int(top + region_height) + pad_y)
        return x1, y1, max(1, x2 - x1), max(1, y2 - y1)

    async def _detect_with_has_image(
        self,
        image_data: bytes,
        page: int,
        pipeline_types: list = None,
        draw_result: bool = True,
    ) -> tuple[list[BoundingBox], str | None]:
        total_start = time.perf_counter()
        stage_duration_ms: dict[str, int] = {}
        self.last_has_image_stage_duration_ms = stage_duration_ms
        slugs = [t.id for t in pipeline_types] if pipeline_types else None
        model_slugs = filter_has_image_model_slugs(slugs)
        raw_boxes = []
        if model_slugs is None or len(model_slugs) > 0:
            try:
                model_start = time.perf_counter()
                raw_boxes = await detect_privacy_regions(
                    image_data,
                    conf=settings.HAS_IMAGE_CONF,
                    category_slugs=model_slugs,
                )
                stage_duration_ms["model"] = _elapsed_ms(model_start)
            except Exception:
                stage_duration_ms["model"] = _elapsed_ms(model_start)
                logger.exception("HaS Image detect failed; falling back to local visual heuristics where available")
        else:
            stage_duration_ms["model"] = 0
            logger.info("HaS Image model skipped: selected visual types are local fallback-only")

        prepare_start = time.perf_counter()
        img = Image.open(io.BytesIO(image_data))
        img = ImageOps.exif_transpose(img)
        stage_duration_ms["prepare"] = _elapsed_ms(prepare_start)

        bounding_boxes: list[BoundingBox] = []
        for i, b in enumerate(raw_boxes):
            raw_slug = b.get("category", "")
            slug = normalize_visual_slug(raw_slug)
            if not is_has_image_model_slug(slug):
                logger.warning("Skipping unsupported HaS Image category from model response: %s", raw_slug)
                continue
            name_zh = VISUAL_TYPE_LABELS_ZH.get(slug, slug)
            x = float(b["x"])
            y = float(b["y"])
            box_width = float(b["width"])
            box_height = float(b["height"])
            if slug == "official_seal":
                x, y, box_width, box_height = self._refine_normalized_official_seal_box(
                    img,
                    x,
                    y,
                    box_width,
                    box_height,
                )
                x, y, box_width, box_height = self._expand_normalized_visual_box(
                    x,
                    y,
                    box_width,
                    box_height,
                    pad_x=0.006,
                    pad_y=0.004,
                )
            x, y, box_width, box_height = self._clamp_normalized_visual_box(
                x,
                y,
                box_width,
                box_height,
            )
            if box_width <= 0.0 or box_height <= 0.0:
                logger.warning("Skipping degenerate HaS Image box after clamping: %s", b)
                continue
            bbox = BoundingBox(
                id=f"hi_{i}_{uuid.uuid4().hex[:8]}",
                x=x,
                y=y,
                width=box_width,
                height=box_height,
                type=slug,
                text=name_zh,
                page=page,
                confidence=float(b.get("confidence", 1.0) or 1.0),
                source="has_image",
                source_detail="has_image",
                evidence_source="has_image_model",
            )
            bounding_boxes.append(bbox)

        wants_official_seal = slugs is None or "official_seal" in slugs
        fallback_start = time.perf_counter()
        if wants_official_seal:
            fallback_regions = [
                ("red_seal_fallback", region) for region in detect_red_seal_regions(img)
            ] + [
                ("dark_seal_fallback", region) for region in detect_dark_seal_regions(img)
            ]
            for source_detail, region in fallback_regions:
                x, y, box_width, box_height = self._expand_fallback_seal_box(
                    region.x,
                    region.y,
                    region.width,
                    region.height,
                )
                if not self._should_keep_fallback_seal_box(x, y, box_width, box_height):
                    logger.debug(
                        "Skipping tiny fallback seal fragment: %.4f %.4f %.4f %.4f",
                        x,
                        y,
                        box_width,
                        box_height,
                    )
                    continue
                bbox = BoundingBox(
                    id=f"local_seal_{uuid.uuid4().hex[:8]}",
                    x=x,
                    y=y,
                    width=box_width,
                    height=box_height,
                    type="official_seal",
                    text=VISUAL_TYPE_LABELS_ZH.get("official_seal", "鍏珷"),
                    page=page,
                    confidence=float(region.confidence),
                    source="has_image",
                    source_detail=f"local_{source_detail}",
                    evidence_source="local_fallback",
                    warnings=self._fallback_seal_warnings(x, y, box_width, box_height, region.confidence),
                )
                if not any(self._is_duplicate_visual_box(bbox, existing) for existing in bounding_boxes):
                    bounding_boxes.append(bbox)
        stage_duration_ms["local_fallback"] = _elapsed_ms(fallback_start)

        draw_start = time.perf_counter()
        result_image_base64 = self._draw_boxes_on_image(img, bounding_boxes) if draw_result else None
        stage_duration_ms["draw"] = _elapsed_ms(draw_start) if draw_result else 0
        stage_duration_ms["total"] = _elapsed_ms(total_start)
        return bounding_boxes, result_image_base64

    async def _detect_with_vlm(
        self,
        image_data: bytes,
        page: int,
        pipeline_types: list = None,
        draw_result: bool = True,
    ) -> tuple[list[BoundingBox], str | None]:
        detector = VlmVisionService()
        try:
            boxes = await detector.detect(image_data, page, pipeline_types or [])
        except httpx.TimeoutException as exc:
            logger.warning("VLM timed out after %.1fs; returning without VLM boxes", settings.VLM_TIMEOUT)
            raise TimeoutError(f"VLM timeout ({settings.VLM_TIMEOUT:.0f}s)") from exc
        if draw_result:
            img = Image.open(io.BytesIO(image_data))
            img = ImageOps.exif_transpose(img)
            return boxes, self._draw_boxes_on_image(img, boxes)
        return boxes, None

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

        HaS Image sometimes returns a coarse region around a red seal that also
        contains table headers or nearby text. Red seals have a strong color
        signal, so we can safely shrink only when enough red pixels are present
        inside the model box. If the crop is grayscale, copied, or ambiguous,
        keep the original box and let the dedicated fallback detectors handle it.
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
        raise ValueError(f"涓嶆敮鎸佺殑鏂囦欢绫诲瀷杩涜鍖垮悕鍖? {file_type}")

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
