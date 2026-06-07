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
from app.services.vision.seal_detector import detect_dark_seal_regions, detect_red_seal_regions

VISUAL_TYPE_LABELS_ZH = {
    **SLUG_TO_NAME_ZH,
}

# --- Merge / dedup parameters (NOT detection filters) -------------------------
# Two boxes describe the SAME physical region when they overlap beyond these
# thresholds; this is how the merge layer collapses duplicates within and across
# the OCR and LA channels. They are merge geometry, not per-category acceptance
# filters second-guessing LA's detections.
_DEDUP_IOU = 0.3
_DEDUP_CONTAINMENT = 0.72
# An LA signature folds in an OCR name box it overlaps even slightly: the printed
# name is the same person and the signature is the redaction region.
_SIG_NAME_FOLD_IOU = 0.05
_SIG_NAME_FOLD_CONTAINMENT = 0.35
# LA boxes the dense stroke core of a signature; pad it so redaction covers the
# whole handwritten mark.
_SIGNATURE_REDACTION_PAD = 0.18

_PDF_TEXT_LAYER_SPARSE_SKIP_AFTER = 2
_PDF_TEXT_LAYER_SPARSE_CACHE_MAX_ITEMS = 128
_PDF_TEXT_LAYER_SPARSE_LOCK = Lock()
_PDF_TEXT_LAYER_SPARSE_COUNTS: OrderedDict[tuple[str, int, int], int] = OrderedDict()
_PDF_TEXT_LAYER_PROBE_LOCKS: dict[tuple[str, int, int], asyncio.Lock] = {}
_PDF_TEXT_LAYER_PROBE_LOCKS_LOOP: asyncio.AbstractEventLoop | None = None

# A probe whose char count is at/below this fraction of the min-char threshold
# counts as a strong sparse signal and short-circuits future probes.
_SPARSE_PROBE_STRONG_SIGNAL_DIVISOR = 4

# --- Same-text-line OCR duplicate detection -----------------------------------
# Floor to avoid divide-by-zero when normalizing vertical overlap.
_SAME_LINE_MIN_HEIGHT_EPS = 1e-6
# Two same-text boxes are a same-line duplicate only above these overlaps.
_SAME_LINE_VERTICAL_OVERLAP_MIN = 0.55
_SAME_LINE_SMALLER_OVERLAP_MIN = 0.25
# How far box centers may differ (as a fraction of the taller box) to count as
# one text line.
_SAME_LINE_CENTER_TOLERANCE_RATIO = 0.65
# Boxes farther apart than this fraction of the wider box are distinct
# occurrences, not an OCR split of one value.
_SAME_LINE_HORIZONTAL_GAP_RATIO = 0.6
# Length window distinguishing a split value from coincidental same text.
_SAME_LINE_SHORT_TEXT_MAX = 6
_SAME_LINE_MIN_MATCH_LEN = 4

# --- OCR box ranking ----------------------------------------------------------
# Scales normalized name-box area into an integer sort key.
_OCR_NAME_AREA_SORT_SCALE = 1_000_000
# Cap text length contribution when ranking non-name OCR boxes.
_OCR_TEXT_LEN_RANK_CAP = 24

# --- OCR rule-line removal ----------------------------------------------------
# Minimum run length (px floor, plus page-fraction) for a horizontal/vertical
# stroke to be treated as a table rule line rather than ink.
_RULE_LINE_RUN_MIN_PX = 24
_RULE_LINE_ROW_RUN_RATIO = 0.38
_RULE_LINE_COL_RUN_RATIO = 0.55

# --- OCR region ink refinement ------------------------------------------------
# Luminance weights (BT.601-style, /100) used to grayscale the crop.
_LUMA_WEIGHT_R = 30
_LUMA_WEIGHT_G = 59
_LUMA_WEIGHT_B = 11
_LUMA_WEIGHT_DENOM = 100
# Red-ink (seal) detection: minimum red channel and its dominance over G/B.
_RED_MARK_MIN = 120
_RED_MARK_R_OVER_G = 1.18
_RED_MARK_R_OVER_B = 1.12
# Dark-ink mask: hard darkness cutoff, plus a softer cutoff for low-chroma pixels.
_INK_GRAY_DARK_MAX = 122
_INK_GRAY_SOFT_MAX = 168
_INK_SOFT_SPAN_MAX = 55
# Minimum ink-pixel count (absolute floor, plus crop-area fraction) to refine.
_REFINE_MIN_INK_PIXELS = 8
_REFINE_MIN_INK_AREA_RATIO = 0.002
# Refinement padding: px floor/cap and fraction of the smaller region edge.
_REFINE_PAD_MIN = 1
_REFINE_PAD_MAX = 4
_REFINE_PAD_RATIO = 0.04
# Reject refinement that collapses width below this floor/fraction of region.
_REFINE_MIN_WIDTH_PX = 6
_REFINE_MIN_WIDTH_RATIO = 0.18

# --- OCR region expansion -----------------------------------------------------
# Per-entity horizontal pad as a fraction of page width (default for others).
_OCR_REGION_HORIZONTAL_PAD_RATIO = {
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
}
_OCR_REGION_DEFAULT_PAD_RATIO = 0.006
_OCR_REGION_PAD_X_MIN = 3
_OCR_REGION_PAD_Y_MIN = 2
# Apply tighter geometry-based padding only to short (non-wide) regions.
_OCR_REGION_NARROW_HEIGHT_FACTOR = 5
_OCR_REGION_NARROW_PAGE_WIDTH_RATIO = 0.12
_OCR_REGION_GEOMETRY_PAD_WIDTH_RATIO = 0.10
_OCR_REGION_GEOMETRY_PAD_HEIGHT_RATIO = 0.35
_OCR_REGION_PAD_Y_RATIO = 0.25

# --- Result image drawing -----------------------------------------------------
_DRAW_FONT_SIZE = 16
_DRAW_BOX_OUTLINE_WIDTH = 2
_DRAW_LABEL_MAX_LEN = 12
_DRAW_LABEL_OFFSET_WITH_FONT = 20
_DRAW_LABEL_OFFSET_NO_FONT = 12

# --- Redaction effects --------------------------------------------------------
# Redaction strength is a 1-100 slider.
_REDACTION_STRENGTH_MAX = 100
# Mosaic block size: px floor, base, and fraction of the smaller edge scaled by
# strength.
_MOSAIC_BLOCK_MIN = 8
_MOSAIC_BLOCK_BASE = 4
_MOSAIC_BLOCK_EDGE_RATIO = 0.6
# Gaussian blur radius: px floor, base, and strength-scaled span.
_BLUR_RADIUS_BASE = 1
_BLUR_RADIUS_MAX_SPAN = 24
# Rasterization scale for redacting PDF pages.
_PDF_REDACTION_RENDER_SCALE = 2.0


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
    if char_count <= max(1, min_chars // _SPARSE_PROBE_STRONG_SIGNAL_DIVISOR):
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

        async def record_pipeline_result(label: str, result) -> None:
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
                if stage_duration_ms:
                    status["stage_duration_ms"] = stage_duration_ms
            elif label == "visual_features" and getattr(self, "last_visual_feature_stage_duration_ms", None):
                status["stage_duration_ms"] = dict(self.last_visual_feature_stage_duration_ms)
            logger.info("%s found %d regions", label, len(boxes))

        # OCR+HaS (text PII) and LocateAnything (visual features) are two
        # independent recall channels. They run sequentially — on a single 16 GB
        # GPU parallel inference thrashes VRAM and is slower — then merge once.
        if not jobs:
            logger.info("No vision pipeline jobs enabled; returning empty results")
        else:
            for label, factory in jobs:
                try:
                    result = await factory()
                except Exception as exc:
                    result = exc
                await record_pipeline_result(label, result)

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
    def _expand_signature_boxes(
        boxes: list[BoundingBox],
        margin: float = _SIGNATURE_REDACTION_PAD,
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

    def _deduplicate_boxes(
        self,
        boxes: list[BoundingBox],
        iou_threshold: float = _DEDUP_IOU,
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

        def _same_type(a: BoundingBox, b: BoundingBox) -> bool:
            """Only dedupe boxes of the EXACT same schema type — no family grouping.

            Open-vocabulary results are presented raw: a qr_code never collapses
            into a barcode, nor a company_name into an "org". OCR text spans and
            visual regions of different schemas can validly overlap, so spatial
            overlap alone is never enough to dedupe across types.
            """
            return _norm_type(a.type) == _norm_type(b.type)

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
            return (y2 - y1) / max(_SAME_LINE_MIN_HEIGHT_EPS, min(a.height, b.height))

        def _same_text_line_duplicate(a: BoundingBox, b: BoundingBox) -> bool:
            if a.page != b.page or not _same_type(a, b):
                return False
            target = _norm_type(a.type)
            if target not in same_line_text_targets:
                return False
            text = _compact_text(a.text)
            if not text or text != _compact_text(b.text):
                return False
            if _vertical_overlap_ratio(a, b) < _SAME_LINE_VERTICAL_OVERLAP_MIN:
                return False
            if self._calculate_smaller_overlap(a, b) >= _SAME_LINE_SMALLER_OVERLAP_MIN:
                return True
            same_center_line = abs((a.y + a.height / 2) - (b.y + b.height / 2)) <= max(a.height, b.height) * _SAME_LINE_CENTER_TOLERANCE_RATIO
            if not same_center_line:
                return False
            # Only an OCR split of a SINGLE value when the boxes are horizontally
            # adjacent. Far-apart same-text boxes on one line are distinct
            # occurrences (e.g. the same date under both 甲方 and 乙方) — keep both.
            horizontal_gap = max(a.x, b.x) - min(a.x + a.width, b.x + b.width)
            if horizontal_gap > _SAME_LINE_HORIZONTAL_GAP_RATIO * max(a.width, b.width):
                return False
            return len(text) <= _SAME_LINE_SHORT_TEXT_MAX or len(text) >= _SAME_LINE_MIN_MATCH_LEN

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
                return (detail_rank, -odd_chars, -int((box.width * box.height) * _OCR_NAME_AREA_SORT_SCALE), -len(text))
            return (detail_rank, -odd_chars, min(len(text), _OCR_TEXT_LEN_RANK_CAP), -(box.width * box.height))

        def _dedupe_ocr_same_target_boxes(items: list[BoundingBox]) -> list[BoundingBox]:
            kept: list[BoundingBox] = []
            for candidate in sorted(items, key=lambda item: (item.page, _norm_type(item.type), item.x, item.y)):
                duplicate_index: int | None = None
                for index, existing in enumerate(kept):
                    if existing.page != candidate.page or not _same_type(candidate, existing):
                        continue
                    if (
                        self._calculate_iou(candidate, existing) > iou_threshold
                        or self._calculate_smaller_overlap(candidate, existing) >= _DEDUP_CONTAINMENT
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

        # An LA signature absorbs the printed name it covers: drop the overlapping
        # OCR name box and fold its text into the signature as evidence (the
        # signature is the redaction region; the printed name is the same person).
        visual_signature_boxes = [b for b in visual_boxes if _is_signature_box(b)]
        suppressed_ocr_ids: set[str] = set()
        enhanced_signatures: dict[str, BoundingBox] = {}
        for sig in visual_signature_boxes:
            evidence: list[str] = []
            for ocr in ocr_boxes:
                if not _is_ocr_name_like(ocr) or sig.page != ocr.page:
                    continue
                if (
                    self._calculate_iou(sig, ocr) > _SIG_NAME_FOLD_IOU
                    or self._calculate_smaller_overlap(sig, ocr) >= _SIG_NAME_FOLD_CONTAINMENT
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
            logger.info("DEDUP folded %d OCR name box(es) into overlapping LA signature(s)", len(suppressed_ocr_ids))

        ocr_boxes = [b for b in ocr_boxes if b.id not in suppressed_ocr_ids]
        visual_boxes = [enhanced_signatures.get(b.id, b) for b in visual_boxes]

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
                if require_same_visual_target and not _same_type(candidate, eb):
                    continue
                if (
                    self._calculate_iou(candidate, eb) > iou_threshold
                    or self._calculate_smaller_overlap(candidate, eb) >= _DEDUP_CONTAINMENT
                ):
                    return True
            return False

        # LA (visual_features) is authoritative for visual families: keep every LA
        # box, then keep only OCR boxes that do NOT overlap a same-family LA box.
        # This is the inverse of the old OCR-wins precedence — LA wins ties.
        visual_boxes.sort(key=lambda b: b.x)
        result = list(visual_boxes)
        for ocr_box in ocr_boxes:
            if not _overlaps_any(ocr_box, visual_boxes, require_same_visual_target=True):
                result.append(ocr_box)

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
                        source="ocr_has",
                        source_detail=str(getattr(region, "source", "") or "ocr_structure:seal"),
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
        row_run_min = max(_RULE_LINE_RUN_MIN_PX, int(width * _RULE_LINE_ROW_RUN_RATIO))
        col_run_min = max(_RULE_LINE_RUN_MIN_PX, int(height * _RULE_LINE_COL_RUN_RATIO))

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
        gray = (red * _LUMA_WEIGHT_R + green * _LUMA_WEIGHT_G + blue * _LUMA_WEIGHT_B) / _LUMA_WEIGHT_DENOM
        span = arr.max(axis=2) - arr.min(axis=2)
        red_mark = (red > _RED_MARK_MIN) & (red > green * _RED_MARK_R_OVER_G) & (red > blue * _RED_MARK_R_OVER_B)
        mask = ((gray < _INK_GRAY_DARK_MAX) | ((gray < _INK_GRAY_SOFT_MAX) & (span < _INK_SOFT_SPAN_MAX))) & ~red_mark
        mask = VisionService._remove_ocr_rule_lines(mask)

        ys, xs = np.where(mask)
        if len(xs) < max(_REFINE_MIN_INK_PIXELS, int(mask.size * _REFINE_MIN_INK_AREA_RATIO)):
            return x1, y1, max(1, x2 - x1), max(1, y2 - y1)

        pad = max(_REFINE_PAD_MIN, min(_REFINE_PAD_MAX, int(min(region_width, region_height) * _REFINE_PAD_RATIO)))
        nx1 = max(x1, x1 + int(xs.min()) - pad)
        nx2 = min(x2, x1 + int(xs.max()) + 1 + pad)
        ny1 = max(y1, y1 + int(ys.min()) - pad)
        ny2 = min(y2, y1 + int(ys.max()) + 1 + pad)

        if nx2 <= nx1 or ny2 <= ny1:
            return x1, y1, max(1, x2 - x1), max(1, y2 - y1)
        if nx2 - nx1 < max(_REFINE_MIN_WIDTH_PX, min(region_width, region_height) * _REFINE_MIN_WIDTH_RATIO):
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
        horizontal_ratio = _OCR_REGION_HORIZONTAL_PAD_RATIO.get(
            entity_type, _OCR_REGION_DEFAULT_PAD_RATIO
        )
        pad_x = max(_OCR_REGION_PAD_X_MIN, int(page_width * horizontal_ratio))
        if region_width <= max(
            region_height * _OCR_REGION_NARROW_HEIGHT_FACTOR,
            page_width * _OCR_REGION_NARROW_PAGE_WIDTH_RATIO,
        ):
            geometry_pad = max(
                _OCR_REGION_PAD_X_MIN,
                min(
                    int(region_width * _OCR_REGION_GEOMETRY_PAD_WIDTH_RATIO),
                    int(region_height * _OCR_REGION_GEOMETRY_PAD_HEIGHT_RATIO),
                ),
            )
            pad_x = min(pad_x, geometry_pad)
        pad_y = max(_OCR_REGION_PAD_Y_MIN, int(region_height * _OCR_REGION_PAD_Y_RATIO))
        x1 = max(0, int(left) - pad_x)
        y1 = max(0, int(top) - pad_y)
        x2 = min(page_width, int(left + region_width) + pad_x)
        y2 = min(page_height, int(top + region_height) + pad_y)
        return x1, y1, max(1, x2 - x1), max(1, y2 - y1)

    def _supplement_seals(
        self,
        image_data: bytes,
        page: int,
        existing_boxes: list[BoundingBox],
    ) -> list[BoundingBox]:
        """Add cv2 seal boxes only where LocateAnything missed one.

        LA recall is borderline on thin 骑缝章 (binding-seal) fragments at the page
        edge: the same seal is caught on some pages but dropped on others. This
        image-analysis fallback recovers those misses for both red stamps and
        dark/photocopied (black/grey) seals. It is a pure SUPPLEMENT — it only
        appends seal boxes that do NOT overlap an already-known seal, uses the
        detector's tight boxes with no geometric expansion, and never drops OCR
        text. Both prior fallback regressions (an expanded box covering a company
        name; dropping OCR text inside seal regions) are therefore structurally
        avoided.
        """
        try:
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_data))).convert("RGB")
            detections = [("red", detect_red_seal_regions(img)), ("dark", detect_dark_seal_regions(img))]
        except Exception:
            logger.warning("cv2 seal fallback failed on page %d", page, exc_info=True)
            return []
        known_seals = [b for b in existing_boxes if normalize_visual_slug(b.type) == "official_seal"]
        extra: list[BoundingBox] = []
        for kind, regions in detections:
            for index, region in enumerate(regions):
                candidate = BoundingBox(
                    id=f"seal_cv2_{kind}_{page}_{index}_{uuid.uuid4().hex[:8]}",
                    x=region.x,
                    y=region.y,
                    width=region.width,
                    height=region.height,
                    type="official_seal",
                    text=SLUG_TO_NAME_ZH.get("official_seal", "official_seal"),
                    page=page,
                    confidence=float(region.confidence),
                    source="visual_features",
                    source_detail=f"seal_detector:{kind}_fallback",
                    evidence_source="visual_feature_model",
                )
                # Skip if it overlaps an LA seal, a red-cv2 seal, or another dark box
                # already accepted this page (so one seal is never double-boxed).
                if any(
                    self._calculate_smaller_overlap(candidate, seal) >= _DEDUP_CONTAINMENT
                    or self._calculate_iou(candidate, seal) > _DEDUP_IOU
                    for seal in (*known_seals, *extra)
                ):
                    continue
                extra.append(candidate)
        if extra:
            logger.info("cv2 seal fallback added %d seal box(es) LA missed on page %d", len(extra), page)
        return extra

    async def _detect_with_visual_features(
        self,
        image_data: bytes,
        page: int,
        pipeline_types: list = None,
        draw_result: bool = True,
    ) -> tuple[list[BoundingBox], str | None]:
        fixed_types, checklist_types = self._split_visual_feature_types(pipeline_types)
        # LocateAnything owns all visual features (seals included), detected per
        # category below; its output is trusted as-is.
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
        boxes = [*locate_boxes, *checklist_boxes]
        if self._visual_slug_requested(pipeline_types, "official_seal"):
            boxes = [*boxes, *self._supplement_seals(image_data, page, boxes)]
        self.last_visual_feature_stage_duration_ms = {
            **stage_duration_ms,
            **{f"custom_{key}": value for key, value in checklist_duration_ms.items()},
            "total": (
                int(stage_duration_ms.get("total", 0) or 0)
                + int(checklist_duration_ms.get("total", 0) or 0)
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
                    font = ImageFont.truetype(fp, _DRAW_FONT_SIZE)
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

            draw.rectangle([x1, y1, x2, y2], outline=color, width=_DRAW_BOX_OUTLINE_WIDTH)

            label_zh = bbox.text or VISUAL_TYPE_LABELS_ZH.get(bbox.type, bbox.type)
            if len(label_zh) > _DRAW_LABEL_MAX_LEN:
                label_zh = label_zh[:_DRAW_LABEL_MAX_LEN] + "..."
            label = f"{label_zh}"
            if font:
                draw.text((x1, max(0, y1 - _DRAW_LABEL_OFFSET_WITH_FONT)), label, fill=color, font=font)
            else:
                draw.text((x1, max(0, y1 - _DRAW_LABEL_OFFSET_NO_FONT)), label, fill=color)

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
        s = max(1, min(_REDACTION_STRENGTH_MAX, strength))
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
            block = max(_MOSAIC_BLOCK_MIN, int(_MOSAIC_BLOCK_BASE + (s / _REDACTION_STRENGTH_MAX) * min_edge * _MOSAIC_BLOCK_EDGE_RATIO))
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
            radius = max(1, int(_BLUR_RADIUS_BASE + (s / _REDACTION_STRENGTH_MAX) * _BLUR_RADIUS_MAX_SPAN))
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
        mat = fitz.Matrix(_PDF_REDACTION_RENDER_SCALE, _PDF_REDACTION_RENDER_SCALE)

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
                max(1, min(_REDACTION_STRENGTH_MAX, strength)),
                fill_color,
            )

        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)

        return output.getvalue()


