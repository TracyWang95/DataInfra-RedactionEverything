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
import re
import time
import uuid
from types import SimpleNamespace

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
from app.services.vision.image_pipeline import (
    PreviewBox,
    SourcePipeline,
    draw_preview_boxes,
)
from app.services.vision.locate_grounding import LocateAnythingGroundingService
from app.services.vision.machine_code_detector import (
    BARCODE_SLUG,
    QR_CODE_SLUG,
    detect_machine_code_regions,
)
from app.services.vision.ocr_artifact_filter import (
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

        all_boxes = self._suppress_text_in_signature(all_boxes)
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
        all_boxes = self._expand_signature_boxes(all_boxes)
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

    @staticmethod
    def _center_inside(inner: BoundingBox, outer: BoundingBox) -> bool:
        """True if the center point of ``inner`` lies within ``outer``."""
        cx = inner.x + inner.width / 2.0
        cy = inner.y + inner.height / 2.0
        return outer.x <= cx <= outer.x + outer.width and outer.y <= cy <= outer.y + outer.height

    @staticmethod
    def _x_overlap_fraction(a: BoundingBox, b: BoundingBox) -> float:
        """Horizontal overlap as a fraction of the narrower box (0..1)."""
        lo = max(a.x, b.x)
        hi = min(a.x + a.width, b.x + b.width)
        return max(0.0, hi - lo) / max(1e-9, min(a.width, b.width))

    def _adopt_la_vertical_geometry(
        self,
        boxes: list[BoundingBox],
        la_boxes: list[BoundingBox],
    ) -> list[BoundingBox]:
        """Replace each OCR text-value box's vertical extent with the LA
        handwriting box that shares its column.

        On photographed forms PaddleOCR-VL emits per-glyph char boxes that all
        carry the merged block's full y-range (no true per-glyph vertical
        geometry), so a handwritten value's box is too tall and, on a tilted
        multi-column form, sits at the wrong row. LocateAnything grounds the
        handwriting as a real 2D box — tight y, tilt-correct. A value and its
        handwriting share a column, so the LA box that overlaps the value box
        horizontally AND whose y-center falls inside the value box's (tall)
        y-span is that value's grounding — overlap is identity, no threshold.
        Adopt its y/height; keep the value box's own x (char-crop, proven). No
        matching LA box -> keep the OCR box unchanged (coverage never dropped).
        """
        if not la_boxes:
            return boxes
        result: list[BoundingBox] = []
        for box in boxes:
            if box.source != "ocr_has" or not str(box.text or "").strip():
                result.append(box)
                continue
            top, bottom = box.y, box.y + box.height
            candidates = [
                la
                for la in la_boxes
                if top <= la.y + la.height / 2.0 <= bottom
                and self._x_overlap_fraction(box, la) > 0.0
            ]
            if not candidates:
                result.append(box)
                continue
            best = max(candidates, key=lambda la: self._x_overlap_fraction(box, la))
            result.append(box.model_copy(update={"y": best.y, "height": best.height}))
        return result

    def _suppress_text_in_signature(self, boxes: list[BoundingBox]) -> list[BoundingBox]:
        """Drop OCR text boxes that coincide with a LocateAnything signature box.

        OCR reading the signature scribble as text is a false positive. An
        ocr_has text box whose center sits inside a visual signature box (or that
        contains the signature's center) is suppressed in favour of the signature
        box. Center-point anchoring is an identity-grade geometric test.
        """
        sig_types = {"signature", "handwriting", "approval_mark"}
        sigs = [b for b in boxes if b.source == "visual_features" and b.type in sig_types]
        if not sigs:
            return boxes
        kept: list[BoundingBox] = []
        dropped = 0
        for b in boxes:
            if b.source == "ocr_has" and any(
                self._center_inside(b, s) or self._center_inside(s, b) for s in sigs
            ):
                dropped += 1
                continue
            kept.append(b)
        if dropped:
            logger.info("Suppressed %d OCR text box(es) inside a signature region", dropped)
        return kept

    def _prefer_vl_seals(self, boxes: list[BoundingBox]) -> list[BoundingBox]:
        """For official_seal, prefer OCR/VL boxes over LocateAnything boxes.

        VL (ocr_has) segments stacked stamps into one box per seal; LocateAnything
        often over-merges them into a single tall strip. Where a VL seal coincides
        with an LA seal (centers mutually contain), drop the LA box so the VL split
        wins. LA seals with no VL counterpart are kept (gap-fill for stamps VL
        missed). If VL produced no seals, keep every LA seal unchanged.
        """
        vl_seals = [b for b in boxes if b.type == "official_seal" and b.source == "ocr_has"]
        if not vl_seals:
            return boxes
        kept: list[BoundingBox] = []
        dropped = 0
        for b in boxes:
            if b.type == "official_seal" and b.source == "visual_features" and any(
                self._center_inside(v, b) or self._center_inside(b, v) for v in vl_seals
            ):
                dropped += 1
                continue
            kept.append(b)
        if dropped:
            logger.info("Dropped %d LA seal box(es) superseded by VL seals", dropped)
        return kept

    def _prefer_yolo_machine_codes(self, boxes: list[BoundingBox]) -> list[BoundingBox]:
        """For qr_code/barcode, prefer the HaS-Image YOLO box over the VLM's.

        The specialist detector boxes machine codes at pixel accuracy; the
        grounding model's 0-1000 quantized boxes run visibly loose (its QR box
        swallows the serial number printed below the code). Where both detect
        the same code (centers mutually contained, the merge layer's standard
        identity test), keep the tight specialist box. VLM codes with no YOLO
        counterpart are kept — this only resolves duplicates, never recall.
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
                    y.type == b.type and (self._center_inside(y, b) or self._center_inside(b, y))
                    for y in yolo_codes
                )
            ):
                dropped += 1
                continue
            kept.append(b)
        if dropped:
            logger.info("Dropped %d loose VLM machine-code box(es) superseded by YOLO", dropped)
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
                    if self._center_inside(s, t) or self._center_inside(t, s):
                        x1 = min(t.x, s.x)
                        y1 = min(t.y, s.y)
                        x2 = max(t.x + t.width, s.x + s.width)
                        y2 = max(t.y + t.height, s.y + s.height)
                        out[i] = t.model_copy(update={
                            "x": x1,
                            "y": y1,
                            "width": x2 - x1,
                            "height": y2 - y1,
                            "confidence": max(t.confidence, s.confidence),
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
    # A physical 二代身份证 is a rectangular card (aspect ≈ 1.585, portrait ≈ 0.63);
    # perspective/rotation in a phone photo widens the axis-aligned box only
    # modestly. A box several times wider than tall is not a card at all — it is
    # LA grounding a horizontal "身份证号码：…" text line (图片_20260714 保姆合同:
    # 表单只有号码, 无实体证件). No real card orientation reaches this ratio, so
    # dropping above it never discards a genuine card.
    _ID_CARD_MAX_ASPECT = 3.0

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
                box_w_px, box_h_px = box.width * page_w, box.height * page_h
                if box_h_px > 0 and box_w_px / box_h_px > self._ID_CARD_MAX_ASPECT:
                    logger.info(
                        "Dropped id_card box shaped like a text line, not a card (aspect %.1f)",
                        box_w_px / box_h_px,
                    )
                    continue
            if box.type == "id_card" and box.source == "visual_features" and not has_face_evidence:
                bx1, by1 = box.x * page_w, box.y * page_h
                bx2, by2 = (box.x + box.width) * page_w, (box.y + box.height) * page_h
                covers_all_text = bx1 <= hull[0] and by1 <= hull[1] and bx2 >= hull[2] and by2 >= hull[3]
                encloses_seal = any(self._center_inside(s, box) for s in seals)
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
                if self._center_inside(b, seal):
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
    def _present_seals_as_visual(boxes: list[BoundingBox]) -> list[BoundingBox]:
        """A seal is a visual feature whatever engine found it. PaddleOCR-VL finds
        seals through the OCR channel (source=ocr_has); relabel every official_seal
        to the visual-features source so the UI shows a uniform 'visual feature'
        and never reveals which engine detected the stamp.
        """
        out: list[BoundingBox] = []
        for b in boxes:
            if b.type == "official_seal" and b.source != "visual_features":
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
                if self._calculate_smaller_overlap(smaller, larger) >= _CONTAINED_TEXT_DROP_RATIO:
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
                region.text,
                text_hull,
                page_em,
            ):
                logger.debug("Skipping OCR region on page edge artifact: %s %s", region.entity_type, region.text)
                continue
            if not region_has_visible_ink(img, region.left, region.top, region.width, region.height, region.entity_type):
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
                self._calculate_smaller_overlap(candidate, known) >= _DEDUP_CONTAINMENT
                or self._calculate_iou(candidate, known) > _DEDUP_IOU
                for known in known_same_type
            ):
                continue
            extra.append(candidate)
        if extra:
            logger.info(
                "cv2 machine-code decoder added %d decoded box(es) LA missed on page %d", len(extra), page
            )
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


