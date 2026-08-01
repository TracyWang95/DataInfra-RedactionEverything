"""Vision recognition service.
视觉识别服务
The runtime combines OCR/HaS semantic regions with LocateAnything visual
feature grounding.
"""
import asyncio
import base64
import hashlib
import inspect
import io
import logging
from collections import OrderedDict
import re
import time
import uuid
from types import SimpleNamespace

logger = logging.getLogger(__name__)

from PIL import Image, ImageOps

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
from app.services.vision.image_pipeline import (
    PreviewBox,
    SourcePipeline,
    draw_preview_boxes,
)
from app.services.vision.box_geometry import (
    _calculate_iou,
    _calculate_smaller_overlap,
    _center_inside,
    _doc_line_height,
    _has_vertically_disjoint_pair,
    _higher_confidence,
    _norm_box_type,
    _x_overlap_fraction,
)
from app.services.vision.redaction_effects import _apply_box_effect
from app.services.vision.la_consensus import consensus_boxes
from app.services.vision.locate_grounding import (
    _HANDWRITING_GROUNDING_QUERIES,
    LocateAnythingGroundingService,
)
from app.services.vision.machine_code_detector import (
    BARCODE_SLUG,
    QR_CODE_SLUG,
    detect_machine_code_regions,
)
from app.services.vision.ocr_artifact_filter import (
    ink_foreground_mask,
    is_page_edge_ocr_artifact,
    region_has_visible_ink,
    text_evidence_hull,
)
from app.services.vision.pdf_text_layer_probe import (
    _get_pdf_text_layer_probe_lock,
    _record_sparse_pdf_text_layer_probe,
    _should_skip_sparse_pdf_text_layer,
)

VISUAL_TYPE_LABELS_ZH = {
    **SLUG_TO_NAME_ZH,
}

# LA 多采样共识结果缓存: key=sha256(image)+types+page -> (boxes, timings)。
# 同一图重新识别返回同一共识结果(彻底稳定); 有界 LRU 防内存涨。
_LA_CONSENSUS_CACHE: "OrderedDict[str, tuple]" = OrderedDict()
_LA_CONSENSUS_CACHE_MAX = 128

# --- Merge / dedup parameters (NOT detection filters) -------------------------
# Two boxes describe the SAME physical region when they overlap beyond these
# thresholds; this is how the merge layer collapses duplicates within and across
# the OCR and LA channels. They are merge geometry, not per-category acceptance
# filters second-guessing LA's detections.
_DEDUP_IOU = 0.3
_DEDUP_CONTAINMENT = 0.72
# LA boxes the dense stroke core of a signature; pad it so redaction covers the
# whole handwritten mark.
_SIGNATURE_REDACTION_PAD = 0.18


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

# A text region this fraction inside a larger same-type region is a redundant
# duplicate (OCR line-wrap makes HaS return a heading both whole and as line
# fragments). IoU dedup misses it because the size gap keeps IoU low.
_CONTAINED_TEXT_DROP_RATIO = 0.85

# Ink-hull measurement: a scan row is a printed horizontal rule (underline)
# when its single longest contiguous ink run covers at least this fraction of
# the value's field width. This is a SHAPE identity — a rule underlines the
# whole field, so it is one full-width run, while a row of handwriting is
# broken into short strokes whose longest run is a small fraction of the field.
# Excluding such rows (printed furniture, never PII) keeps the measured hull on
# the handwritten strokes; the 0.2 tolerance below full width absorbs scan gaps.
_RULE_MIN_RUN_WIDTH_FRAC = 0.8


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


def _normalize_file_type(file_type: FileType | str) -> FileType | str:
    try:
        return FileType(file_type) if isinstance(file_type, str) else file_type
    except ValueError:
        return file_type


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

        # fingerprint: the YOLO 捺印 detector REPLACES the LA channel, so LA is
        # skipped for it (LA would ground it ~2-3s only to be discarded — wasted
        # latency; the detector runs unconditionally below, recall unchanged).
        # signature: YOLO ∪ LA — the signature detector SUPPLEMENTS LA rather than
        # replacing it (a handwritten name one model misses the other often
        # catches: the red 陈晨 receipt signature, the doctor's 诊断 scrawl), so
        # signature STAYS in the LA request and both boxes union + dedup below.
        _detector_slugs: set[str] = set()
        if str(getattr(settings, "FINGERPRINT_DETECTOR_URL", "") or "").strip():
            _detector_slugs.add("fingerprint")

        effective_visual_feature_types: list | None = None
        if visual_feature_types:
            effective_visual_feature_types = [
                item
                for item in visual_feature_items
                if normalize_visual_slug(getattr(item, "id", item)) not in OCR_FALLBACK_ONLY_VISUAL_SLUGS
                and normalize_visual_slug(getattr(item, "id", item)) not in _detector_slugs
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
        # independent recall channels, but they run SEQUENTIALLY on purpose:
        # OCR (PP-Structure) and LA (MoonViT) contend hard for one card's VRAM
        # if run concurrently. Measured on the dual 5090s: parallel inflated
        # ocr_has 0.5s -> 5-10s AND the combined memory pressure OOM'd LA's
        # 2048 forward, silently dropping the visual (signature/seal) boxes.
        # Serial keeps each model alone on the GPU; the cross-GPU win is in
        # LocateAnything itself (per-category fan-out across both cards).
        run_parallel = (
            len(jobs) > 1
            and bool(getattr(settings, "VISION_DUAL_PIPELINE_PARALLEL", False))
        )
        if not jobs:
            logger.info("No vision pipeline jobs enabled; returning empty results")
        elif run_parallel:
            # OCR+HaS and LA run concurrently. Safe now that PaddleOCR-VL
            # recognition is REMOTE (off the OCR card) and LA runs at 1280, so
            # same-card OCR+LA no longer OOMs. Toggle off via the flag to revert.
            outcomes = await asyncio.gather(
                *(factory() for _label, factory in jobs), return_exceptions=True
            )
            for (label, _factory), result in zip(jobs, outcomes, strict=False):
                await record_pipeline_result(label, result)
        else:
            for label, factory in jobs:
                try:
                    result = await factory()
                except Exception as exc:
                    result = exc
                await record_pipeline_result(label, result)

        # Specialized signature detector (conditional-detr) REPLACES the LA
        # signature grounding when configured — single-class, never fires on
        # printed labels, deterministic. The OCR-prune inside it + the seal absorb
        # below kill its two residual FP classes (printed org name, seal script).
        if bool(visual_feature_types) and self._visual_slug_requested(visual_feature_items, "signature"):
            try:
                all_boxes = await self._detect_signatures_via_detector(
                    all_boxes, await get_image_data(), page
                )
            except Exception:
                logger.warning("signature detector stage skipped; kept LA signatures", exc_info=True)

        # Specialized inked-fingerprint detector (YOLO11, locally trained on
        # synthetic 捺印-on-document data) REPLACES the LA/YOLO fingerprint channel
        # when configured. It recalls the pale/red prints the grounding VLM missed
        # and — trained with bare-hand backgrounds as hard negatives, on grayscale
        # — does NOT fire on the page-holding finger / seals / red text that the old
        # channel FP'd on. Fails open (keeps the LA fingerprints on any error).
        if bool(visual_feature_types) and self._visual_slug_requested(visual_feature_items, "fingerprint"):
            try:
                all_boxes = await self._detect_fingerprints_via_detector(
                    all_boxes, await get_image_data(), page
                )
            except Exception:
                logger.warning("fingerprint detector stage skipped; kept LA fingerprints", exc_info=True)

        all_boxes = self._drop_full_page_seals(all_boxes)
        all_boxes = self._prefer_vl_seals(all_boxes)
        all_boxes = self._prefer_yolo_machine_codes(all_boxes)
        all_boxes = self._merge_seal_shards(all_boxes)
        # LocateAnything misread stamp content (seal script, inked dates) as
        # phantom "signatures", which this absorb pass folds into the seal hull.
        # Gated because absorbing also swallows a REAL signature stamped over a
        # seal (签字盖章重叠) — turn it OFF when those must survive.
        if bool(getattr(settings, "ABSORB_SIGNATURES_IN_SEALS", True)):
            all_boxes = self._absorb_signatures_in_seals(all_boxes)
        # Small images are upscaled before LA now, which makes LA hallucinate
        # the whole document as an id_card (立案告知书 upscaled: 5/5). Drop a
        # card box that swallows all OCR text yet shows no card face evidence.
        ocr_page_blocks = list(getattr(self, "_page_ocr_blocks", None) or [])
        if ocr_page_blocks:
            try:
                with Image.open(io.BytesIO(await get_image_data())) as _pg:
                    page_size = ImageOps.exif_transpose(_pg).size
                all_boxes = self._drop_page_hallucinated_cards(all_boxes, ocr_page_blocks, page_size)
            except Exception:
                logger.warning("page-hallucinated card filter skipped", exc_info=True)
        all_boxes = self._deduplicate_boxes(all_boxes)
        # R7w: coverage-preservingly tighten over-tall OCR value boxes using LA
        # handwriting-grounding row geometry + measured ink hulls (env-gated,
        # exception-swallowing). Placed after dedup / before signature padding.
        all_boxes = await self._tighten_la_vertical_geometry(all_boxes, get_image_data, page)
        all_boxes = self._expand_signature_boxes(all_boxes)
        # The text pipeline (OCR+HaS) and the vision pipeline (signature detector)
        # are INDEPENDENT: each marks its own finding even where they cross. The old
        # cross-channel fold collapsed a signature into an overlapping OCR box ("OCR
        # wins"), which coupled the STABLE vision signature to a FLAKY OCR reading —
        # a handwritten name over a red seal (张伟/李强, 图片_20260511183513) is read
        # by OCR as PERSON only intermittently (0/1/2 across runs), so the folded
        # signature flickered "时灵时不灵" while the detector itself was rock-steady
        # (LA 2/2 every run). A signature is a visual feature; it stays boxed as one
        # regardless of what the text channel did on the same ink (redaction over-
        # covers, never leaks). Symmetric with dropping the reverse suppression
        # (_suppress_text_in_signature): neither pipeline erases the other's box.
        all_boxes = self._suppress_ocr_text_inside_visual_regions(all_boxes)
        all_boxes = self._present_seals_as_visual(all_boxes)

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
            # The dedicated signature detector (YOLO11) is trained end-to-end to
            # box the WHOLE handwritten mark, so its box is already complete —
            # padding it only bloats it over adjacent document text (a 日期 printed
            # just above the signature got swallowed, and the box read "很大").
            # Only LocateAnything's grounding boxes capture just the densest stroke
            # and need this coverage pad.
            is_detector_box = "signature_detector" in str(getattr(box, "source_detail", "") or "")
            if _norm_box_type(box.type) in sig_types and not is_detector_box:
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

    def _adopt_la_vertical_geometry(
        self,
        boxes: list[BoundingBox],
        la_boxes: list[BoundingBox],
        doc_line_h: float,
        ink_hulls: dict[str, tuple[float, float]] | None = None,
    ) -> list[BoundingBox]:
        """Tighten an OCR text-value box's *virtual* vertical height using the
        LA handwriting box that grounds its row — coverage-preservingly.

        On photographed forms PaddleOCR-VL emits per-glyph char boxes that all
        carry the merged block's full y-range (no true per-glyph vertical
        geometry), so a handwritten value's box is too tall and, on a tilted
        multi-column form, spans into a neighbouring row. LocateAnything grounds
        the handwriting as a real 2D box — tight y, tilt-correct.

        The old version bare-replaced y/height with LA's, which is unsafe two
        ways: LA frames only the densest strokes (undercovering a descender /
        flourish), and on a wrong/ambiguous match it could re-anchor to the
        wrong row (a reverse leak). This version is a *coverage consumer*:

          (a) Error-row guard: a candidate LA must contain the OCR box's
              y-center (``la.y <= cy <= la.y+la.h``); among valid candidates
              take the one whose center is nearest cy. If cy falls in the gutter
              between LA rows (no LA row contains it) -> refuse to correct and
              keep the original over-covering OCR box (failure = don't correct,
              never re-anchor).
          (b) Ambiguity: if the column holds >=2 vertically-disjoint LA
              candidates (two distinct rows), the value's row can't be
              determined -> keep the original OCR box.
          (c) Coverage-preserving height (core): do NOT bare-replace. The new
              vertical extent is the hull of the LA box's y-range UNION the
              entity's *proven* ink hull (``ink_hulls[box.id]`` = the measured
              y-range of the entity's own dark strokes, floor). New
              ``y1 = min(la.y, ink_top)``, ``y2 = max(la.y+la.h, ink_bottom)``;
              the OCR box's x (char-crop, proven) is kept. This drops LA-external
              virtual height while never shrinking below real ink — any
              descender/flourish inside the ink hull stays covered.
          (d) Only *confirmed* over-tall boxes are touched: those with
              ``height >= 2 * doc_line_h`` (``doc_line_h`` = the document's own
              self-calibrated line height, e.g. ``text_evidence_hull``'s median
              text-region em). Normal-height boxes are returned unchanged so we
              never disturb a box that is already right.

        Every failure path (no LA match / no ink floor / ambiguity / gutter /
        not over-tall) returns the original over-covering box, so coverage is
        monotone non-decreasing versus the bare-replace it supersedes.

        Pure geometry only. WIRING TODO (human, in the dual pipeline):
          1. Measure each candidate text box's ink y-hull from the image (dark
             pixels of that entity's strokes) and pass it in ``ink_hulls`` keyed
             by ``box.id``; ``region_has_visible_ink`` / ``text_evidence_hull``
             are the existing per-entity ink probes to build it from.
          2. Source ``la_boxes`` by cropping the over-tall box's column strip and
             running LA grounding on it (GPU).
          3. On LA empty / miss for a box, pass no candidate — this function
             keeps the original box.
          4. Pass ``doc_line_h`` = the self-calibrated line em (e.g.
             ``text_evidence_hull(regions)[1]``), never a fixed pixel constant.
        """
        if not la_boxes or doc_line_h <= 0:
            return boxes
        ink_hulls = ink_hulls or {}
        oversize_floor = 2.0 * doc_line_h
        result: list[BoundingBox] = []
        for box in boxes:
            if box.source != "ocr_has" or not str(box.text or "").strip():
                result.append(box)
                continue
            # (d) only confirmed-oversize boxes are candidates for tightening
            if box.height < oversize_floor:
                result.append(box)
                continue
            top, bottom = box.y, box.y + box.height
            # same-column candidates: horizontal overlap AND vertical intersection
            column = [
                la
                for la in la_boxes
                if _x_overlap_fraction(box, la) > 0.0
                and min(bottom, la.y + la.height) - max(top, la.y) > 1e-9
            ]
            if not column:
                result.append(box)
                continue
            # (b) two distinct rows in the column -> ambiguous
            if _has_vertically_disjoint_pair(column):
                result.append(box)
                continue
            # (a) error-row guard: keep only LA rows containing the OCR y-center
            cy = box.y + box.height / 2.0
            valid = [la for la in column if la.y <= cy <= la.y + la.height]
            if not valid:
                result.append(box)  # cy in gutter / no row contains it
                continue
            best = min(valid, key=lambda la: abs((la.y + la.height / 2.0) - cy))
            # (c) coverage-preserving height: hull(LA y-range ∪ proven ink hull)
            ink = ink_hulls.get(box.id)
            if ink is None:
                result.append(box)  # no measured ink floor -> cannot safely tighten
                continue
            ink_top, ink_bottom = ink
            new_top = min(best.y, ink_top)
            new_bottom = max(best.y + best.height, ink_bottom)
            result.append(
                box.model_copy(update={"y": new_top, "height": new_bottom - new_top})
            )
        return result

    @staticmethod
    def _full_width_rule_rows(mask: "np.ndarray") -> "np.ndarray":
        """Per-row boolean selector marking rows that are a solid horizontal rule.

        A printed underline underlines the whole field, so in its row the ink is
        ONE contiguous run spanning ~the full crop width; a row of handwriting is
        broken into short strokes whose longest contiguous run is a small
        fraction of the field. The cut is on the longest run being essentially
        the entire width (``_RULE_MIN_RUN_WIDTH_FRAC``) — a shape identity of
        "a line", not a tuned score.
        """
        import numpy as np

        h, w = mask.shape
        out = np.zeros(h, dtype=bool)
        if w == 0:
            return out
        floor = _RULE_MIN_RUN_WIDTH_FRAC * w
        for i in range(h):
            row = mask[i]
            if not row.any():
                continue
            # longest contiguous run of True via run boundaries on a 0-padded row
            edges = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
            runs = edges[1::2] - edges[0::2]
            if runs.size and int(runs.max()) >= floor:
                out[i] = True
        return out

    def _measure_ink_hulls(
        self,
        image: "Image.Image",
        boxes: list[BoundingBox],
        la_boxes: list[BoundingBox],
    ) -> dict[str, tuple[float, float]]:
        """Measure each OCR text-value box's real ink y-extent from the image.

        Feeds ``_adopt_la_vertical_geometry``'s coverage-preserving floor: the
        tighten is ``hull(LA-row ∪ measured-ink)`` and can never collapse below
        proven strokes. For each ``ocr_has`` value box we find the LA handwriting
        box that grounds its row (x-overlap AND contains the box's y-center). In
        that box's x span (the OCR value's proven char-crop), over a row window
        self-calibrated to the LA box height ``[la.y - la.h, la.y + 2*la.h]``
        (keeps the measurement on THIS row so a neighbouring row's ink can't
        inflate the hull), we take the y upper/lower bound of foreground (ink)
        pixels using the SAME ink identity as the density gate
        (``ink_foreground_mask``), after excluding full-width horizontal rules
        (printed underlines — see ``_full_width_rule_rows``).

        Returns ``{box.id: (ink_top_norm, ink_bottom_norm)}`` only for boxes with
        a matching LA row AND measurable stroke ink. A box absent from the dict
        keeps its original (over-covering) geometry in the consumer — so any
        analysis gap fails toward over-coverage, never a leak.
        """
        if not la_boxes:
            return {}
        try:
            import numpy as np

            rgb = np.asarray(image.convert("RGB"))
        except Exception:
            logger.warning("ink hull measurement unavailable; skipping", exc_info=True)
            return {}
        if rgb.ndim != 3 or rgb.shape[0] < 2 or rgb.shape[1] < 2:
            return {}
        ph, pw = rgb.shape[0], rgb.shape[1]
        hulls: dict[str, tuple[float, float]] = {}
        for box in boxes:
            if box.source != "ocr_has" or not str(box.text or "").strip():
                continue
            cy = box.y + box.height / 2.0
            candidates = [
                la
                for la in la_boxes
                if _x_overlap_fraction(box, la) > 0.0
                and la.y <= cy <= la.y + la.height
            ]
            if not candidates:
                continue
            la = min(candidates, key=lambda l: abs((l.y + l.height / 2.0) - cy))
            x0 = max(0, int(box.x * pw))
            x1 = min(pw, int((box.x + box.width) * pw))
            win_top = max(0, int((la.y - la.height) * ph))
            win_bottom = min(ph, int((la.y + 2.0 * la.height) * ph))
            if x1 - x0 < 1 or win_bottom - win_top < 1:
                continue
            crop = rgb[win_top:win_bottom, x0:x1]
            mask = ink_foreground_mask(crop)
            # exclude printed full-width underlines; strokes drive the hull
            stroke_mask = mask.copy()
            stroke_mask[self._full_width_rule_rows(mask)] = False
            rows_with_ink = np.flatnonzero(stroke_mask.any(axis=1))
            if rows_with_ink.size == 0:
                continue
            ink_top = (win_top + int(rows_with_ink.min())) / ph
            ink_bottom = (win_top + int(rows_with_ink.max()) + 1) / ph
            hulls[box.id] = (ink_top, ink_bottom)
        return hulls

    async def _tighten_la_vertical_geometry(
        self,
        all_boxes: list[BoundingBox],
        get_image_data,
        page: int,
    ) -> list[BoundingBox]:
        """Wire the R7c core into the pipeline: LA handwriting grounding + measured
        ink hulls -> coverage-preserving vertical tighten of over-tall OCR value
        boxes. Gated behind ``VISION_LA_VERTICAL_TIGHTEN`` (default off) and fully
        exception-swallowing — any failure returns ``all_boxes`` untouched so the
        main redaction path is never affected. GPU/image work is deferred until a
        genuine over-tall candidate exists.
        """
        if not bool(getattr(settings, "VISION_LA_VERTICAL_TIGHTEN", False)):
            return all_boxes
        try:
            doc_line_h = _doc_line_height(all_boxes)
            if doc_line_h <= 0:
                return all_boxes
            oversize_floor = 2.0 * doc_line_h
            needs = [
                b
                for b in all_boxes
                if b.source == "ocr_has"
                and str(b.text or "").strip()
                and b.height >= oversize_floor
            ]
            if not needs:
                return all_boxes
            image_data = await get_image_data()
            la_hw = await self.visual_grounding.ground_handwriting(
                image_data, list(_HANDWRITING_GROUNDING_QUERIES), page=page
            )
            if not la_hw:
                return all_boxes
            with Image.open(io.BytesIO(image_data)) as _img:
                image = ImageOps.exif_transpose(_img).convert("RGB")
            ink_hulls = self._measure_ink_hulls(image, all_boxes, la_hw)
            return self._adopt_la_vertical_geometry(all_boxes, la_hw, doc_line_h, ink_hulls)
        except Exception:
            logger.warning("LA vertical tighten skipped", exc_info=True)
            return all_boxes

    @staticmethod
    def _drop_full_page_seals(boxes: list[BoundingBox]) -> list[BoundingBox]:
        """A visual box spanning the whole page is degenerate — drop it.

        No stamp, card, signature or code is the entire page; a box reaching all
        four page edges is a detector or a stale cache painting the page as one
        region (the scene-flood / ink-snap failure mode, and LA hallucinating the
        whole document as an id_card when a small crop is upscaled). Reject any
        visual_features box by that topology so it can never survive whatever
        produced it. "At the edge" is LocateAnything's own coordinate quantum — it
        emits integer thousandths, so its last cell (0 or 0.999) IS the page
        border, not a tuned tolerance. Text boxes (words/lines) are never
        page-sized, so this is scoped to the visual channel.
        """
        quantum = 1.0 / 1000.0  # LA emits coordinates as integer/1000
        kept = []
        for b in boxes:
            if (
                b.source == "visual_features"
                and b.x <= quantum and b.y <= quantum
                and b.x + b.width >= 1.0 - quantum
                and b.y + b.height >= 1.0 - quantum
            ):
                logger.info("Dropped a full-page %s box (degenerate)", b.type)
                continue
            kept.append(b)
        return kept

    def _prefer_vl_seals(self, boxes: list[BoundingBox]) -> list[BoundingBox]:
        """PaddleOCR-VL is the authority on 公章 — trust its seal boxes as primary.

        VL's layout seal detection is deterministic and reliable, so every VL seal
        (source_detail=paddleocr_vl:seal — a visual feature, NOT the OCR+HaS text
        channel) is kept as the canonical box for its stamp. LA/YOLO seals only
        SUPPLEMENT it: one whose center falls inside a VL seal is the SAME stamp VL
        already boxed — a duplicate — and is dropped in favour of VL's box. Keeping
        it let the looser, stochastic LA box win the later shard merge, so the seal
        flickered run-to-run (时灵时不灵). An LA/YOLO seal whose center lies outside
        every VL seal is a distinct stamp VL did not find and is kept (recall
        preserved). If VL produced no seals, every LA/YOLO seal is kept unchanged.
        Center-inside is the parameter-free identity test already used across this
        merge layer — no threshold, no magic number.
        """
        vl_seals = [
            b for b in boxes
            if b.type == "official_seal" and "paddleocr_vl" in str(b.source_detail or "")
        ]
        if not vl_seals:
            return boxes
        kept: list[BoundingBox] = []
        dropped = 0
        for b in boxes:
            if (
                b.type == "official_seal"
                and "paddleocr_vl" not in str(b.source_detail or "")
                and any(_center_inside(b, v) for v in vl_seals)
            ):
                dropped += 1
                continue
            kept.append(b)
        if dropped:
            logger.info("Dropped %d LA/YOLO seal(s) duplicating a PaddleOCR-VL seal", dropped)
        return kept

    def _prefer_yolo_machine_codes(self, boxes: list[BoundingBox]) -> list[BoundingBox]:
        """For qr_code/barcode, prefer the HaS-Image YOLO box over the VLM's.

        The specialist detector boxes machine codes at pixel accuracy; the
        grounding model's 0-1000 quantized boxes run visibly loose (its QR box
        swallows the serial number printed below the code). Where both detect a
        code at the same spot (centers mutually contained, the merge layer's
        standard identity test), keep the tight specialist box. YOLO is also the
        authority on the code's TYPE: one physical machine code is a QR OR a
        barcode, never both, so a VLM box of EITHER code type overlapping a YOLO
        code box is the same code — the VLM often double-labels one QR as both
        qr_code AND barcode (病例5), leaving two stacked boxes. Drop the VLM box
        regardless of its type label; YOLO's box already covers the region, so
        this only resolves duplicates, never recall. VLM codes with no YOLO
        counterpart are kept untouched.
        """
        code_types = {"qr_code", "barcode"}
        yolo_codes = [
            b for b in boxes
            if b.type in code_types and str(getattr(b, "source_detail", "") or "").startswith("has_image:")
        ]
        if not yolo_codes:
            return boxes
        kept: list[BoundingBox] = []
        dropped = 0
        for b in boxes:
            if (
                b.type in code_types
                and not str(getattr(b, "source_detail", "") or "").startswith("has_image:")
                and any(
                    _center_inside(y, b) or _center_inside(b, y)
                    for y in yolo_codes
                )
            ):
                dropped += 1
                continue
            kept.append(b)
        if dropped:
            logger.info("Dropped %d VLM machine-code box(es) superseded by the YOLO code", dropped)
        return kept

    def _merge_seal_shards(self, boxes: list[BoundingBox]) -> list[BoundingBox]:
        """One physical stamp, one box.

        Detection channels can each contribute a partial box for the SAME
        stamp (offset shards on tilted camera photos slip past the
        IoU/containment dedup thresholds). Two seal boxes are shards of one
        stamp when either box's center lies inside the other - the same
        center-anchoring test used across this merge layer; distinct
        side-by-side stamps never contain each other's centers, so real
        multi-seal pages are untouched. Shards fold into their bounding hull
        to a fixpoint, keeping the identity of the largest box.
        """
        seals = [b for b in boxes if b.type == "official_seal"]
        if len(seals) < 2:
            return boxes
        seals.sort(key=lambda b: b.width * b.height, reverse=True)
        fold_count = 0
        changed = True
        while changed:
            changed = False
            out: list[BoundingBox] = []
            for s in seals:
                folded = False
                for i, t in enumerate(out):
                    if _center_inside(s, t) or _center_inside(t, s):
                        x1 = min(t.x, s.x)
                        y1 = min(t.y, s.y)
                        x2 = max(t.x + t.width, s.x + s.width)
                        y2 = max(t.y + t.height, s.y + s.height)
                        out[i] = t.model_copy(update={
                            "x": x1,
                            "y": y1,
                            "width": x2 - x1,
                            "height": y2 - y1,
                            "confidence": _higher_confidence(t.confidence, s.confidence),
                        })
                        fold_count += 1
                        folded = True
                        changed = True
                        break
                if not folded:
                    out.append(s)
            seals = out
        if not fold_count:
            return boxes
        logger.info("Merged %d seal shard box(es) into their hulls", fold_count)
        hull_by_id = {b.id: b for b in seals}
        result: list[BoundingBox] = []
        for b in boxes:
            if b.type != "official_seal":
                result.append(b)
            elif b.id in hull_by_id:
                result.append(hull_by_id.pop(b.id))
        result.extend(hull_by_id.values())
        return result

    # ID-card face evidence: the printed labels present on a real 二代身份证
    # (front or back). A page LA hallucinated as a card carries none of them.
    _ID_CARD_FACE_WORDS = (
        "居民身份证", "公民身份号码", "签发机关", "有效期限", "出生", "性别", "民族", "住址",
    )
    _ID_CARD_NUMBER_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")

    def _id_card_number_covered_elsewhere(
        self,
        card: BoundingBox,
        boxes: list[BoundingBox],
        ocr_blocks: list,
        page_size: tuple[int, int],
    ) -> bool:
        """Whether an id_card ground can be dropped because it only covers an ID
        number that is ALREADY masked by another retained ocr_has box.

        A wide axis-aligned box is a SIGNAL that LA grounded a horizontal
        "身份证号码：…" text line rather than a card face — but the aspect ratio
        never decides alone (dropping an UNcovered number is a leak). The gate is
        coverage: for every 18-digit ID number sitting inside this box's region
        (this page's own OCR blocks), a DIFFERENT retained ocr_has box that
        overlaps the region must carry the same number. Then dropping this box
        keeps every number masked — coverage is monotone. A genuine card face
        (its printed 二代证 face words appear inside the box) is never dropped:
        its name/photo would be uncovered, so any face word inside keeps the box.
        """
        page_w, page_h = page_size
        if page_w <= 0 or page_h <= 0:
            return False
        cx1, cy1 = card.x * page_w, card.y * page_h
        cx2, cy2 = (card.x + card.width) * page_w, (card.y + card.height) * page_h
        numbers_inside: list[str] = []
        interior_text: list[str] = []
        for b in ocr_blocks:
            try:
                bcx = b.left + b.width / 2.0
                bcy = b.top + b.height / 2.0
            except AttributeError:
                continue
            if not (cx1 <= bcx <= cx2 and cy1 <= bcy <= cy2):
                continue
            text = str(getattr(b, "text", "") or "")
            interior_text.append(text)
            numbers_inside.extend(m.group() for m in self._ID_CARD_NUMBER_RE.finditer(text))
        joined_interior = " ".join(interior_text)
        if any(word in joined_interior for word in self._ID_CARD_FACE_WORDS):
            return False  # a genuine card face — dropping it would uncover name/photo
        retained_ocr = [
            o
            for o in boxes
            if o is not card
            and o.source == "ocr_has"
            and not (
                o.x + o.width <= card.x
                or card.x + card.width <= o.x
                or o.y + o.height <= card.y
                or card.y + card.height <= o.y
            )
        ]
        # OCR already TYPED this region as an ID number: a retained ID_CARD box
        # masks the digits even when a HANDWRITTEN number does not parse as a clean
        # 18-digit string (保姆合同: the 身份证号 OCR'd as '4102/1989010…' with a
        # slash). No card face here (guarded above), so the visual card only
        # re-masks what OCR already covers — redundant, drop it.
        if any(str(o.type) == "ID_CARD" for o in retained_ocr):
            return True
        # Otherwise require clean-number coverage: every 18-digit number inside the
        # region must be carried by a retained box, or dropping would leak it.
        if not numbers_inside:
            return False
        for number in numbers_inside:
            if not any(number in str(o.text or "") for o in retained_ocr):
                return False
        return True

    async def _detect_fingerprints_via_detector(
        self, boxes: list[BoundingBox], image_data: bytes, page: int
    ) -> list[BoundingBox]:
        """Replace the LA/YOLO fingerprint channel with the specialized YOLO11
        inked-print detector (locally trained on synthetic 捺印-on-document data,
        grayscale inference). It recalls the pale/red prints the grounding VLM
        missed and does NOT fire on the page-holding finger / seals / red text
        (bare-hand backgrounds were hard negatives in training). The service
        returns normalized boxes; we retag them as fingerprint and drop the old
        visual fingerprint boxes. Fails OPEN: any error keeps the existing boxes,
        because a missed print is a leak.
        """
        url = str(getattr(settings, "FINGERPRINT_DETECTOR_URL", "") or "").strip()
        if not url:
            return boxes
        try:
            import httpx

            body = {"image_base64": base64.b64encode(image_data).decode("utf-8")}
            timeout = float(getattr(settings, "VISUAL_FEATURES_TIMEOUT", 60) or 60)
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(f"{url.rstrip('/')}/detect", json=body)
                resp.raise_for_status()
            raw = resp.json().get("boxes") or []
        except Exception:
            logger.warning("fingerprint detector unavailable; keeping LA fingerprints", exc_info=True)
            return boxes
        dets: list[BoundingBox] = []
        for r in raw:
            try:
                x, y, w, h = float(r["x"]), float(r["y"]), float(r["width"]), float(r["height"])
            except (KeyError, TypeError, ValueError):
                continue
            if w <= 0 or h <= 0:
                continue
            dets.append(BoundingBox(
                id=f"inkdet_{uuid.uuid4().hex[:8]}", x=x, y=y, width=w, height=h,
                type="fingerprint", text=SLUG_TO_NAME_ZH.get("fingerprint", "指纹"), page=page,
                confidence=r.get("confidence"), source="visual_features",
                source_detail="fingerprint_detector:yolo11",
                evidence_source="visual_feature_model",
            ))
        kept = [b for b in boxes if not (b.source == "visual_features" and b.type == "fingerprint")]
        if dets:
            logger.info("fingerprint detector: %d print box(es) replace the LA channel", len(dets))
        return kept + dets

    async def _detect_signatures_via_detector(
        self, boxes: list[BoundingBox], image_data: bytes, page: int
    ) -> list[BoundingBox]:
        """SUPPLEMENT the LA signature channel with the specialized YOLO11 signature
        detector (locally trained on ChiSig 中文 synthetic + Mels22 西文 real
        doc-domain signatures — the conditional-DETR is retired: it false-fired on
        receipt creases and under-boxed). Single-class, doc-domain, deterministic;
        it does NOT fire on printed 乙方:/甲方: labels, seals, or folds.

        YOLO ∪ LA (union), NOT replace: a handwritten name one model misses the
        other often catches, so both boxes are kept and the same-type IoU dedup
        downstream merges the overlaps. The false-positive class both can show on a
        busy page (a signature box landing on a company-name line) is killed by the
        org-line filter below, applied to BOTH sources. Fails OPEN: any detector
        error keeps the LA signatures untouched, because a missed signature is a leak.
        """
        url = str(getattr(settings, "SIGNATURE_DETECTOR_URL", "") or "").strip()
        if not url:
            return boxes
        try:
            import httpx

            body = {"image_base64": base64.b64encode(image_data).decode("utf-8")}
            timeout = float(getattr(settings, "VISUAL_FEATURES_TIMEOUT", 60) or 60)
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(f"{url.rstrip('/')}/detect", json=body)
                resp.raise_for_status()
            raw = resp.json().get("boxes") or []
        except Exception:
            logger.warning("signature detector unavailable; keeping LA signatures", exc_info=True)
            return boxes
        detr: list[BoundingBox] = []
        for r in raw:
            try:
                x, y, w, h = float(r["x"]), float(r["y"]), float(r["width"]), float(r["height"])
            except (KeyError, TypeError, ValueError):
                continue
            if w <= 0 or h <= 0:
                continue
            detr.append(BoundingBox(
                id=f"sigdet_{uuid.uuid4().hex[:8]}", x=x, y=y, width=w, height=h,
                type="signature", text=SLUG_TO_NAME_ZH.get("signature", "签字"), page=page,
                confidence=r.get("confidence"), source="visual_features",
                source_detail="signature_detector:yolo11",
                evidence_source="visual_feature_model",
            ))
        # The YOLO signature detector is the trusted PRIMARY; LA only SUPPLEMENTS.
        # LA now grounds signature too — it is no longer skipped when the detector
        # is configured — but an LA box whose center lies inside any detector box
        # is the SAME handwritten mark the detector already boxed (a duplicate),
        # dropped in favour of the detector's deterministic whole-mark box (the LA
        # box only frames the densest strokes, so the old IoU dedup let the thin LA
        # box survive next to the fat YOLO box and the signature flickered). An LA
        # box centered outside every detector box is a mark the detector missed and
        # is kept (recall preserved). No detector box -> every LA signature kept.
        # Center-inside, no threshold, no magic number — same as _prefer_vl_seals.
        la_sigs = [b for b in boxes if b.source == "visual_features" and b.type == "signature"]
        others = [b for b in boxes if not (b.source == "visual_features" and b.type == "signature")]
        if detr:
            kept_la = [s for s in la_sigs if not any(_center_inside(s, d) for d in detr)]
            if len(kept_la) < len(la_sigs):
                logger.info(
                    "signature: dropped %d LA box(es) duplicating a detector signature",
                    len(la_sigs) - len(kept_la),
                )
            la_sigs = kept_la
        sigs = la_sigs + detr
        # Both cleanup filters below run on the noisy LA supplement only — the trained
        # YOLO detector is the trusted PRIMARY (doc-domain, with printed labels/seals/
        # folds as hard negatives), so a box it fires IS handwriting and a text-channel
        # heuristic must not override it (a dropped real signature is a leak; the 乙方
        # 法定代表人签字 scrawl, which OCR misreads as label-tail chars carrying no PII,
        # was being killed here). _is_detector_sig gates the exemption.
        def _is_detector_sig(s: BoundingBox) -> bool:
            return "signature_detector" in str(getattr(s, "source_detail", "") or "")

        # A signature is a PERSON's handwriting — never a company designation. An LA
        # box on the SAME LINE as a company name (its y-centre inside an
        # INSTITUTION_NAME box's y-span) is the party line — "乙方：信尔胜机械…" —
        # read as a false signature; the false box sits on the "乙方：" label just
        # left of the org text, same line. Real signatures are on their OWN lines
        # (the 法定代表人签字 line, far below any org name).
        # Model-centric (the NER already typed that line as an org) and 0-miss safe:
        # the org text on that line is redacted regardless, so a real signature
        # sharing the line loses nothing.
        orgs = [b for b in boxes if b.type == "INSTITUTION_NAME"]
        if orgs and sigs:
            def _on_org_line(s: BoundingBox) -> bool:
                cy = s.y + s.height / 2
                return any(o.y <= cy <= o.y + o.height for o in orgs)
            before = len(sigs)
            sigs = [s for s in sigs if _is_detector_sig(s) or not _on_org_line(s)]
            if len(sigs) < before:
                logger.info(
                    "signature: dropped %d false signature(s) on a company-name line",
                    before - len(sigs),
                )
        # Generalize the org-line rule (LA boxes only, per _is_detector_sig): an LA box
        # whose CENTER sits inside an OCR text block that the NER produced NO PII on is a
        # false fire on printed boilerplate — a title ("立案告知书"), a sentence ("本告知书
        # 已收到") — that LA occasionally grounds at low confidence. Drop it. Model-centric:
        # the arbiter is the text channel's own output (OCR read that block as text, NER
        # found no entity there). 0-miss: a block with no PII has nothing to redact, so
        # removing an LA box over it can never uncover PII. NOTE this can't gate on a
        # signature whose OWN scrawl OCR misread as no-PII label-tail chars — that is why
        # the YOLO detector, trained to fire only on real handwriting, is exempted.
        ocr_blocks = list(getattr(self, "_page_ocr_blocks", None) or [])
        if ocr_blocks and sigs:
            with Image.open(io.BytesIO(image_data)) as _im:
                _w, _h = ImageOps.exif_transpose(_im).size
            pii = [
                b for b in boxes
                if str(b.source) == "ocr_has"
                and b.type not in ("official_seal", "signature", "fingerprint")
            ]

            def _overlaps_pii(nx1: float, ny1: float, nx2: float, ny2: float) -> bool:
                return any(
                    not (p.x + p.width <= nx1 or p.x >= nx2 or p.y + p.height <= ny1 or p.y >= ny2)
                    for p in pii
                )

            printed: list[tuple[float, float, float, float]] = []
            for blk in ocr_blocks:
                text = str(getattr(blk, "text", "") or "").strip()
                if not text or text.startswith("<"):
                    continue
                bx1, by1, bx2, by2 = blk.bbox
                rect = (bx1 / _w, by1 / _h, bx2 / _w, by2 / _h)
                if not _overlaps_pii(*rect):
                    printed.append(rect)
            if printed:
                def _on_printed(s: BoundingBox) -> bool:
                    cx, cy = s.x + s.width / 2, s.y + s.height / 2
                    return any(a <= cx <= c and b <= cy <= d for a, b, c, d in printed)
                before = len(sigs)
                sigs = [s for s in sigs if _is_detector_sig(s) or not _on_printed(s)]
                if len(sigs) < before:
                    logger.info(
                        "signature: dropped %d false signature(s) on printed no-PII text",
                        before - len(sigs),
                    )
        if detr or la_sigs:
            logger.info(
                "signature: YOLO %d box(es) ∪ LA %d box(es)", len(detr), len(la_sigs)
            )
        return others + sigs

    def _drop_page_hallucinated_cards(
        self,
        boxes: list[BoundingBox],
        ocr_blocks: list,
        page_size: tuple[int, int],
    ) -> list[BoundingBox]:
        """Drop an id_card visual box that is really the document hallucinated
        as a card (立案告知书 upscaled: LA grounds the page as "ID card"). Zero
        tuned numbers — pure identity signals. An id_card box is a hallucination
        when it shows NO card evidence (no 二代身份证 face word AND no 18-digit
        ID number in its interior OCR) AND EITHER:
          - it contains an official_seal box — a real 身份证 never encloses a
            red 公章 (semantic identity), or
          - it covers the whole OCR text hull — the box IS the document.
        A real card (face words readable, OR — a blurred copy — the 18-digit
        number survives OCR) escapes on the evidence test and is kept. No OCR /
        no id_card -> unchanged (fail toward keeping the mask). Failure
        direction: any escape condition true -> keep (over-mask, never a
        missed real card).
        """
        page_w, page_h = page_size
        if not ocr_blocks or page_w <= 0 or page_h <= 0:
            return boxes
        rects = []
        for b in ocr_blocks:
            try:
                left, top, right, bottom = b.left, b.top, b.left + b.width, b.top + b.height
            except AttributeError:
                continue
            rects.append((left, top, right, bottom))
        if not rects:
            return boxes
        hull = (
            min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects),
        )
        all_text = " ".join(str(getattr(b, "text", "") or "") for b in ocr_blocks)
        has_face_evidence = (
            any(word in all_text for word in self._ID_CARD_FACE_WORDS)
            or bool(self._ID_CARD_NUMBER_RE.search(all_text))
        )
        seals = [b for b in boxes if b.type == "official_seal"]
        out = []
        for box in boxes:
            if box.type == "id_card" and box.source == "visual_features":
                if self._id_card_number_covered_elsewhere(box, boxes, ocr_blocks, page_size):
                    logger.info(
                        "Dropped id_card ground: its id number is already masked by a retained OCR box"
                    )
                    continue
            if box.type == "id_card" and box.source == "visual_features" and not has_face_evidence:
                bx1, by1 = box.x * page_w, box.y * page_h
                bx2, by2 = (box.x + box.width) * page_w, (box.y + box.height) * page_h
                covers_all_text = bx1 <= hull[0] and by1 <= hull[1] and bx2 >= hull[2] and by2 >= hull[3]
                encloses_seal = any(_center_inside(s, box) for s in seals)
                if covers_all_text or encloses_seal:
                    logger.info("Dropped page-hallucinated id_card box (no card evidence; seal=%s)", encloses_seal)
                    continue
            out.append(box)
        return out

    def _absorb_signatures_in_seals(self, boxes: list[BoundingBox]) -> list[BoundingBox]:
        """A 'signature' OR 'fingerprint' centered inside an official_seal box
        is the stamp's own content (seal script, star, inked date — all red
        ink, so the fingerprint interior-ink gate legitimately passes it)
        misread by the model, not an independent mark. Absorb it: expand the
        seal box to the hull of both and drop the inner box. Coverage can
        only grow - a genuine mark overlapping the stamp keeps every pixel
        masked, only the redundant box disappears. (0713 contract19: the top
        electronic seal came back as 4 tile "fingerprints".)
        """
        seal_indexes = [i for i, b in enumerate(boxes) if b.type == "official_seal"]
        if not seal_indexes:
            return boxes
        out = list(boxes)
        absorbed: set[int] = set()
        for j, b in enumerate(boxes):
            if b.type not in ("signature", "fingerprint"):
                continue
            for i in seal_indexes:
                seal = out[i]
                if _center_inside(b, seal):
                    x1 = min(seal.x, b.x)
                    y1 = min(seal.y, b.y)
                    x2 = max(seal.x + seal.width, b.x + b.width)
                    y2 = max(seal.y + seal.height, b.y + b.height)
                    out[i] = seal.model_copy(update={
                        "x": x1,
                        "y": y1,
                        "width": x2 - x1,
                        "height": y2 - y1,
                    })
                    absorbed.add(j)
                    break
        if not absorbed:
            return boxes
        logger.info("Absorbed %d signature/fingerprint box(es) into seal hulls", len(absorbed))
        return [b for j, b in enumerate(out) if j not in absorbed]

    @staticmethod
    def _suppress_ocr_text_inside_visual_regions(boxes: list[BoundingBox]) -> list[BoundingBox]:
        """Drop an OCR text entity whose box sits FULLY inside a signature or a seal.

        Both kinds of stamp swallow OCR'd ink that is not the document's data:
        - A handwritten SIGNATURE's strokes get OCR'd and typed as a spurious entity (a
          scrawl read as 机构名称 "Tregy"). Always dropped — it is signature ink and the
          mask already covers those pixels (0-leak).
        - A SEAL carries its own engraved ARC text (弧文 "…服务有限公司" → garbage "R公司"),
          which OCR reads as an institution name floating on a faint margin stamp.

        But a seal is also routinely stamped OVER a party's real printed name (乙方 章下
        "上海云芯计算机有限公司"), which the user DOES want listed. The two are told apart
        model-centrically by document-wide occurrence, not by content: a value that also
        appears in a text box NOT swallowed by any seal is real data the stamp happens to
        cover — that same name prints elsewhere (e.g. at the top), so keep the under-seal
        copy. A value that exists ONLY inside seals is the seal's own engraving — drop it.
        Either way it is 0-leak: the seal box masks those pixels too (double cover). Full
        containment (all four corners), not centre, so a name merely clipping a stamp edge
        (海南工程服务有限公司, wider than the stamp) is never touched. No rule, regex, wordlist.
        """
        signatures = [b for b in boxes if b.type == "signature"]
        seals = [b for b in boxes if b.type == "official_seal"]
        if not signatures and not seals:
            return boxes

        def _fully_inside(b: BoundingBox, s: BoundingBox) -> bool:
            return (
                s.x <= b.x
                and s.y <= b.y
                and b.x + b.width <= s.x + s.width
                and b.y + b.height <= s.y + s.height
            )

        def _norm(b: BoundingBox) -> str:
            return str(getattr(b, "text", "") or "").strip()

        # Values that also print OUTSIDE every seal — real document data a stamp covers.
        outside_seal_values = {
            _norm(b)
            for b in boxes
            if str(b.source) == "ocr_has"
            and b.type not in ("signature", "official_seal")
            and _norm(b)
            and not any(_fully_inside(b, s) for s in seals)
        }

        kept: list[BoundingBox] = []
        dropped_sig = dropped_seal = 0
        for b in boxes:
            if str(b.source) != "ocr_has" or b.type in ("signature", "official_seal"):
                kept.append(b)
                continue
            if any(_fully_inside(b, s) for s in signatures):
                dropped_sig += 1
                continue
            if seals and _norm(b) not in outside_seal_values and any(
                _fully_inside(b, s) for s in seals
            ):
                dropped_seal += 1
                continue
            kept.append(b)
        if dropped_sig or dropped_seal:
            logger.info(
                "Suppressed %d OCR text box(es) inside a signature, %d inside a seal "
                "(the masks cover them)",
                dropped_sig,
                dropped_seal,
            )
        return kept

    @staticmethod
    def _present_seals_as_visual(boxes: list[BoundingBox]) -> list[BoundingBox]:
        """A seal is a visual feature whatever engine found it. Seals already carry
        source=visual_features (PaddleOCR-VL as source_detail=paddleocr_vl:seal, LA
        as locate_anything, YOLO as has_image); this final pass normalizes their
        source_detail to a uniform 'visual_feature_model' so the UI shows one
        'visual feature' and never reveals which engine detected the stamp. Runs
        AFTER _prefer_vl_seals, which needs the engine-specific source_detail.
        """
        out: list[BoundingBox] = []
        for b in boxes:
            if b.type == "official_seal" and b.source_detail != "visual_feature_model":
                out.append(b.model_copy(update={
                    "source": "visual_features",
                    "source_detail": "visual_feature_model",
                    "evidence_source": "visual_feature_model",
                }))
            else:
                out.append(b)
        return out

    def _deduplicate_boxes(
        self,
        boxes: list[BoundingBox],
        iou_threshold: float | None = None,
    ) -> list[BoundingBox]:
        """Geometric dedup scoped to one entity type at a time.

        "Duplicate" means the SAME OBJECT detected twice; a differing type is
        the model asserting a DIFFERENT entity, so cross-type boxes are never
        merged however tightly they overlap - a thumbprint pressed onto a
        handwritten name (0710 农业合同实证: same pixels, two entities) must
        keep both boxes; the old type-blind pass ate the fingerprint on one
        line and the signature on the other. Type equality is a string
        identity, so user-defined custom types participate as their own
        entities with no enumeration. Within one (page, type) group it stays
        a pure IoU pass - the larger box is kept so redaction coverage never
        shrinks, and no source/text/ranking rule is ever consulted (each such
        removed rule could drop a genuine PII box).
        """
        if len(boxes) <= 1:
            return boxes
        from app.services.vision.region_merger import deduplicate_by_iou

        kwargs = {} if iou_threshold is None else {"iou_threshold": iou_threshold}
        kept_ids: set[int] = set()
        groups: dict[tuple, list[BoundingBox]] = {}
        for b in boxes:
            groups.setdefault((b.page, b.type), []).append(b)
        for group in groups.values():
            for b in deduplicate_by_iou(group, lambda b: (b.x, b.y, b.width, b.height), **kwargs):
                kept_ids.add(id(b))
        result = [b for b in boxes if id(b) in kept_ids]
        removed_count = len(boxes) - len(result)
        if removed_count > 0:
            logger.info("DEDUP removed %d duplicate boxes (IoU within same type only)", removed_count)
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
        # This page's text blocks (local, off the singleton) for the same per-call
        # hallucinated-card gate the image path feeds.
        self._page_ocr_blocks = list(blocks)
        if getattr(self.ocr_has_service, "last_duration_ms", None):
            self.ocr_has_service.last_duration_ms["pdf_text_layer_extract"] = int(
                self.last_pdf_text_layer_duration_ms
            )

        bounding_boxes = []
        for index, region in enumerate(regions):
            if not self._should_keep_ocr_has_region(region.entity_type, region.text):
                logger.debug("Skipping PDF text-layer semantic false positive: %s %s", region.entity_type, region.text)
                continue
            left = max(0, int(region.left))
            top = max(0, int(region.top))
            box_width = max(1, int(region.width))
            box_height = max(1, int(region.height))
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
        page_blocks: list = []
        regions, result_image_base64 = await self.ocr_has_service.detect_and_draw(
            image_data,
            vision_types=pipeline_types,
            draw_result=draw_result,
            blocks_out=page_blocks,
        )
        # This call's OCR blocks, captured off the process-wide singleton so the
        # hallucinated-card gate never judges against a concurrent page's blocks.
        self._page_ocr_blocks = page_blocks

        img = Image.open(io.BytesIO(image_data))
        img = ImageOps.exif_transpose(img)

        # 像素级过滤/收紧是纯 CPU 工作，放 worker 线程避免阻塞事件循环。
        bounding_boxes = await asyncio.to_thread(
            self._filter_ocr_has_regions, img, regions, page
        )
        bounding_boxes = self._drop_contained_same_type_text(bounding_boxes)
        return bounding_boxes, result_image_base64

    def _drop_contained_same_type_text(self, boxes: list[BoundingBox]) -> list[BoundingBox]:
        """Drop a text region mostly contained within a larger same-type region.

        OCR line-wrap makes HaS return a wrapped heading both whole and as line
        fragments (19合同 标题 "...供货合同" also emits a "货合同" tail), so the
        matcher lays a small box inside the larger same-type box. IoU dedup
        misses it — the size gap keeps IoU below threshold — but containment
        catches it. The larger box is kept so redaction coverage never shrinks.
        Same-type only: a different type is a different entity the model asserts.
        """
        if len(boxes) <= 1:
            return boxes
        drop: set[int] = set()
        for smaller in boxes:
            area_s = smaller.width * smaller.height
            for larger in boxes:
                if larger is smaller or larger.type != smaller.type:
                    continue
                if larger.width * larger.height <= area_s:
                    continue
                if _calculate_smaller_overlap(smaller, larger) >= _CONTAINED_TEXT_DROP_RATIO:
                    drop.add(id(smaller))
                    break
        if drop:
            logger.info("Dropped %d text region(s) contained in a larger same-type box", len(drop))
        return [b for b in boxes if id(b) not in drop]

    def _filter_ocr_has_regions(
        self,
        img: Image.Image,
        regions: list,
        page: int,
    ) -> list[BoundingBox]:
        width, height = img.size
        # Self-calibrate the page body extent from the regions that decoded real
        # text; the edge filter judges margin artifacts against this hull rather
        # than a fixed normalized offset.
        text_hull, page_em = text_evidence_hull(regions)
        bounding_boxes = []
        for i, region in enumerate(regions):
            normalized_region_type = _norm_box_type(region.entity_type)
            is_ocr_visual_seal = normalized_region_type in {"seal", "official_seal", "stamp"}
            if not self._should_keep_ocr_has_region(region.entity_type, region.text):
                logger.debug("Skipping OCR-HaS semantic false positive: %s %s", region.entity_type, region.text)
                continue
            # A region is dropped ONLY when it carries no visible ink — an inked
            # margin note or handwriting value is always kept, even outside the
            # body-text hull. The page-edge/hull test may NOT short-circuit ahead
            # of the ink gate (R9 verify): it only qualifies the drop reason, it
            # can never remove an inked (potential-PII) region.
            if not region_has_visible_ink(img, region.left, region.top, region.width, region.height, region.entity_type):
                artifact = is_page_edge_ocr_artifact(
                    region.left,
                    region.top,
                    region.width,
                    region.height,
                    width,
                    height,
                    region.entity_type,
                    region.text,
                    text_hull,
                    page_em,
                )
                logger.debug(
                    "Skipping inkless OCR region (%s): %s %s",
                    "page-edge/outside-body" if artifact else "blank",
                    region.entity_type,
                    region.text,
                )
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
                        # 公章是视觉特征, 从诞生就走视觉来源 — 绝不挂 OCR+HaS 文本链路
                        # (那会让文本过滤器把它当"章内文字"误杀, 也概念混乱). PaddleOCR-VL
                        # 的 Seal 检测是公章主力, _prefer_vl_seals 按 source_detail 认出它、
                        # 让它压过 LA/YOLO 补充框。OCR 调用虽与文本共用一次推理, 但产物归视觉。
                        source="visual_features",
                        source_detail="paddleocr_vl:seal",
                        evidence_source="visual_feature_model",
                    )
                )
                continue
            # Use the match/split geometry as-is: its X is the proven char-box
            # span and its Y is the uniform document line grid. The old
            # refine-to-ink then pad-by-ratio pair re-derived the box from each
            # glyph's ink extent (digits read taller than CJK, so DATE rows
            # towered) and then re-inflated it by a magic 0.25 height ratio,
            # destroying the upstream uniformity. A charless slab that never got
            # a tight char-box span stays a safe whole-block cover.
            left = max(0, int(region.left))
            top = max(0, int(region.top))
            box_width = max(1, int(region.width))
            box_height = max(1, int(region.height))
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

        return bounding_boxes

    @staticmethod
    def _should_keep_ocr_has_region(entity_type: str, text: str | None) -> bool:
        """Keep non-empty HaS Text results; semantic filtering belongs to HaS."""
        return bool(str(text or "").strip())

    def _supplement_machine_codes(
        self,
        image_data: bytes,
        page: int,
        existing_boxes: list[BoundingBox],
        requested_slugs: list[str],
    ) -> list[BoundingBox]:
        """Add decoded QR/barcode boxes only where LocateAnything missed one.

        cv2 only reports a machine code once its payload actually decodes, which
        is a deterministic format proof — zero false positives, no thresholds.
        A pure SUPPLEMENT: it only appends
        boxes that do NOT overlap an already-known box of the same category,
        using the shared merge-layer overlap constants.
        """
        try:
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_data)))
            regions = detect_machine_code_regions(img)
        except Exception:
            logger.warning("cv2 machine-code decoder failed on page %d", page, exc_info=True)
            return []
        requested = {normalize_visual_slug(slug) for slug in requested_slugs}
        extra: list[BoundingBox] = []
        for index, region in enumerate(regions):
            category = normalize_visual_slug(region.code_type)
            if category not in requested:
                continue
            candidate = BoundingBox(
                id=f"machine_code_{category}_{page}_{index}_{uuid.uuid4().hex[:8]}",
                x=region.x,
                y=region.y,
                width=region.width,
                height=region.height,
                type=category,
                text=SLUG_TO_NAME_ZH.get(category, category),
                page=page,
                confidence=float(region.confidence),
                source="visual_features",
                source_detail=f"qr_decoder:{category}",
                evidence_source="visual_feature_model",
            )
            known_same_type = [
                b for b in (*existing_boxes, *extra) if normalize_visual_slug(b.type) == category
            ]
            if any(
                _calculate_smaller_overlap(candidate, known) >= _DEDUP_CONTAINMENT
                or _calculate_iou(candidate, known) > _DEDUP_IOU
                for known in known_same_type
            ):
                continue
            extra.append(candidate)
        if extra:
            logger.info(
                "cv2 machine-code decoder added %d decoded box(es) LA missed on page %d", len(extra), page
            )
        return extra

    async def _detect_categories_consensus(
        self,
        image_data: bytes,
        page: int,
        fixed_types: list,
    ) -> tuple[list[BoundingBox], dict]:
        """LA 多采样共识包装 detect_categories。SAMPLES<=1 时直通(默认零开销)。
        SAMPLES>1 时同图跑 N 次 seedless 采样取多数框(压 temp0.7 波动、保召回), 并按
        图片hash缓存(重新识别返回同一结果、彻底稳定)。N 次串行, 避免 N×并发压垮 LA。"""
        samples = int(getattr(settings, "LOCATE_ANYTHING_CONSENSUS_SAMPLES", 1) or 1)
        if samples <= 1:
            return await self.visual_grounding.detect_categories(image_data, page, fixed_types)
        type_key = ",".join(sorted(str(getattr(t, "id", t)) for t in (fixed_types or [])))
        cache_key = f"{hashlib.sha256(image_data).hexdigest()}:{page}:{type_key}"
        cached = _LA_CONSENSUS_CACHE.get(cache_key)
        if cached is not None:
            _LA_CONSENSUS_CACHE.move_to_end(cache_key)
            return cached[0], {**cached[1], "consensus_cache_hit": 1}
        # N seedless passes run SERIALLY: concurrent samples contend for the two
        # LA cards and each pass loses boxes (measured: concurrent union-3 dropped
        # 病例5 to 3/4 vs serial 4/4), the same card-contention that forces the
        # dual pipeline sequential. Serial ~15s for 3 passes; the per-image hash
        # cache makes every re-detect after the first instant + identical.
        runs: list[list[BoundingBox]] = []
        first_timings: dict = {}
        for i in range(samples):
            boxes, timings = await self.visual_grounding.detect_categories(
                image_data, page, fixed_types
            )
            runs.append(boxes)
            if i == 0:
                first_timings = timings
        min_votes = int(getattr(settings, "LOCATE_ANYTHING_CONSENSUS_MIN_VOTES", 0) or 0)
        if min_votes <= 0:
            min_votes = samples // 2 + 1
        iou = float(getattr(settings, "LOCATE_ANYTHING_CONSENSUS_IOU", 0.5))
        merged = consensus_boxes(runs, min_votes, iou)
        timings_out = {
            **first_timings,
            "consensus_samples": samples,
            "consensus_min_votes": min_votes,
        }
        _LA_CONSENSUS_CACHE[cache_key] = (merged, timings_out)
        while len(_LA_CONSENSUS_CACHE) > _LA_CONSENSUS_CACHE_MAX:
            _LA_CONSENSUS_CACHE.popitem(last=False)
        return merged, timings_out

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
        locate_boxes, stage_duration_ms = await self._detect_categories_consensus(
            image_data,
            page,
            fixed_types,
        )
        checklist_boxes: list[BoundingBox] = []
        checklist_duration_ms: dict[str, int] = {}
        if checklist_types:
            try:
                checklist_boxes, checklist_duration_ms = await self.visual_grounding.detect_checklist(
                    image_data,
                    page,
                    checklist_types,
                )
            except Exception as e:
                # 自定义 checklist 失败不应连带丢掉已算出的固定类目框。
                logger.warning("LocateAnything checklist stage failed on page %d: %s", page, e)
                self.last_warnings.append(f"visual checklist failed on page {page}: {e}")
        boxes = [*locate_boxes, *checklist_boxes]
        machine_code_slugs = [
            slug for slug in (QR_CODE_SLUG, BARCODE_SLUG) if self._visual_slug_requested(pipeline_types, slug)
        ]
        if machine_code_slugs:
            # cv2 解码是同步 CPU 工作，放 worker 线程避免阻塞事件循环。
            supplemental_codes = await asyncio.to_thread(
                self._supplement_machine_codes, image_data, page, boxes, machine_code_slugs
            )
            boxes = [*boxes, *supplemental_codes]
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
        """Thin adapter: normalized boxes -> pixel PreviewBoxes -> shared core."""
        width, height = image.size
        preview_boxes = []
        for bbox in bounding_boxes:
            pipeline = (
                SourcePipeline.VISUAL
                if bbox.source == "visual_features"
                else SourcePipeline.TEXT
            )
            preview_boxes.append(PreviewBox(
                left=int(bbox.x * width),
                top=int(bbox.y * height),
                right=int((bbox.x + bbox.width) * width),
                bottom=int((bbox.y + bbox.height) * height),
                label=bbox.text or VISUAL_TYPE_LABELS_ZH.get(bbox.type, bbox.type),
                pipeline=pipeline,
            ))
        draw_image = draw_preview_boxes(image, preview_boxes)

        buffer = io.BytesIO()
        draw_image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

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
            _apply_box_effect(image, bbox, width, height, image_method, strength, fill_color)

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
        try:
            new_doc = fitz.open()
            try:
                mat = fitz.Matrix(_PDF_REDACTION_RENDER_SCALE, _PDF_REDACTION_RENDER_SCALE)

                for page_index in range(len(doc)):
                    page = doc[page_index]
                    page_no = page_index + 1
                    page_boxes = [b for b in bounding_boxes if b.selected and (b.page or 1) == page_no]
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    for bbox in page_boxes:
                        _apply_box_effect(img, bbox, pix.width, pix.height, image_method, strength, fill_color)
                    buf = io.BytesIO()
                    # Scanned PDFs are redacted by rasterizing each page and applying
                    # the selected explicit masking effect to each selected region.
                    # Embedding those page rasters as PNGs bloats delivery PDFs badly;
                    # high-quality JPEG keeps exported packages practical for real scans.
                    img.save(buf, format="JPEG", quality=settings.REDACTION_PDF_JPEG_QUALITY, optimize=True)
                    buf.seek(0)
                    new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                    new_page.insert_image(new_page.rect, stream=buf.read())

                new_doc.save(output_path, garbage=4, deflate=True, clean=True)
            finally:
                new_doc.close()
        finally:
            doc.close()

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
            _apply_box_effect(
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


