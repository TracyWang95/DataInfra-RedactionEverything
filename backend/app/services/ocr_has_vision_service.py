"""OCR/HaS semantic vision service.

This module owns OCR block extraction, HaS Text semantic analysis, entity-to-OCR matching, and shared region dataclasses used by the visual pipeline.
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import io
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from PIL import Image

from app.core.visual_feature_categories import VISUAL_ONLY_ENTITY_TYPES
from app.models.type_mapping import canonical_type_id

IMAGE_TEXT_ENTITY_TYPE_ALIASES = {
    "DATETIME": "DATE",
    "DATE_TIME": "DATE",
    "COMPANY": "COMPANY_NAME",
}


def _canonical_image_text_type(entity_type: str | None) -> str:
    value = str(entity_type or "").strip().upper()
    return canonical_type_id(IMAGE_TEXT_ENTITY_TYPE_ALIASES.get(value, value))


def _canonicalize_image_text_types(entity_type_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(_canonical_image_text_type(type_id) for type_id in entity_type_ids))


def _semantic_entity_type_ids(entity_type_ids: list[str]) -> list[str]:
    # Any requested type that is not visual-only is a text/semantic type and is
    # sent to HaS. The channel was already decided upstream (ocr_has vs visual);
    # we no longer gate on a hardcoded whitelist — "what you check is what you get".
    return [
        type_id
        for type_id in _canonicalize_image_text_types(entity_type_ids)
        if type_id not in VISUAL_ONLY_ENTITY_TYPES
    ]


def _semantic_vision_types(vision_types: list | None) -> list | None:
    if vision_types is None:
        return None
    return [
        item
        for item in vision_types
        if _canonical_image_text_type(getattr(item, "id", "")) not in VISUAL_ONLY_ENTITY_TYPES
    ]


def _needs_has_text_analysis(entity_type_ids: list[str]) -> bool:
    """Return whether selected vision types need semantic HaS NER."""
    return any(_canonical_image_text_type(type_id) not in VISUAL_ONLY_ENTITY_TYPES for type_id in entity_type_ids)

# ---------------------------------------------------------------------------
# Shared data classes (imported by sub-modules and external consumers)
# ---------------------------------------------------------------------------

@dataclass
class SensitiveRegion:
    """Sensitive region in pixel coordinates."""
    text: str
    entity_type: str
    left: int      # 像素坐标
    top: int
    width: int
    height: int
    confidence: float = 1.0
    source: str = "unknown"  # "ocr", "visual_features", "merged"
    color: tuple[int, int, int] = (255, 0, 0)


@dataclass
class OCRTextBlock:
    """OCR text block with a cached bounding box."""
    text: str
    polygon: list[list[float]]  # 四边形顶点 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    confidence: float = 1.0
    # Per-character boxes in PIXEL coords, L→R: [{"c","x1","y1","x2","y2"}, ...].
    # Lets matching redact an entity's exact pixels instead of estimating.
    chars: list = field(default_factory=list)

    # 构造后缓存的 bbox 值
    _bbox_cache: tuple[int, int, int, int] = field(default=(0, 0, 0, 0), init=False, repr=False)

    def __post_init__(self):
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        self._bbox_cache = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return self._bbox_cache

    @property
    def left(self) -> int:
        return self._bbox_cache[0]

    @property
    def top(self) -> int:
        return self._bbox_cache[1]

    @property
    def width(self) -> int:
        return self._bbox_cache[2] - self._bbox_cache[0]

    @property
    def height(self) -> int:
        return self._bbox_cache[3] - self._bbox_cache[1]


# ---------------------------------------------------------------------------
# OCR/HaS service
# ---------------------------------------------------------------------------

class OcrHasVisionService:
    """PaddleOCR-VL, PP-StructureV3, and HaS Text semantic vision service."""

    def __init__(self):
        self._ocr_service = None   # OCR HTTP 客户端
        self._has_client = None    # HaS NER 客户端
        self._has_ready = False
        self.last_duration_ms: dict[str, Any] = {}
        self.last_ocr_blocks: list[OCRTextBlock] = []
        self.current_owner_id: str | None = None
        self._init_services()

    def _init_services(self):
        """Initialize OCR and HaS clients."""
        try:
            from app.services.ocr_service import ocr_service
            self._ocr_service = ocr_service
            logger.info("OCR client initialized (will check availability at runtime)")
        except Exception as e:
            logger.warning("OCR client init failed: %s", e)
            self._ocr_service = None

        try:
            from app.services.has_client import HaSClient
            self._has_client = HaSClient()
            self._has_ready = False
            self._has_service = True
            logger.info("HaS Client initialized (availability checked on first NER call)")
        except Exception as e:
            logger.warning("HaS Client init failed: %s", e)
            self._has_client = None
            self._has_ready = False

    # ------------------------------------------------------------------
    # Delegated helpers
    # ------------------------------------------------------------------

    def _prepare_image(self, image_bytes: bytes) -> tuple[Image.Image, int, int]:
        from app.services.vision.ocr_pipeline import prepare_image
        return prepare_image(image_bytes)

    def _run_paddle_ocr(
        self,
        image: Image.Image,
        *,
        require_visual_regions: bool = False,
        selected_entity_types: list[str] | None = None,
        stage_status: dict[str, Any] | None = None,
    ) -> tuple[list[OCRTextBlock], list[SensitiveRegion]]:
        from app.services.vision.ocr_pipeline import run_paddle_ocr
        return run_paddle_ocr(
            image,
            self._ocr_service,
            require_visual_regions=require_visual_regions,
            selected_entity_types=selected_entity_types,
            stage_status=stage_status,
        )

    async def _run_has_text_analysis(
        self,
        ocr_blocks: list[OCRTextBlock],
        vision_types: list | None = None,
        stage_status: dict[str, Any] | None = None,
    ) -> list[dict]:
        # Lazy re-init (service may have started after us)
        if not self._has_client:
            try:
                from app.services.has_client import HaSClient
                self._has_client = HaSClient()
            except Exception:
                pass
        from app.services.vision.ocr_pipeline import run_has_text_analysis
        return await run_has_text_analysis(ocr_blocks, self._has_client, vision_types, stage_status=stage_status)

    async def _invoke_has_text_analysis(
        self,
        ocr_blocks: list[OCRTextBlock],
        vision_types: list | None,
        stage_status: dict[str, Any],
    ) -> list[dict]:
        """Call HaS Text while preserving older test doubles with two args."""
        func = self._run_has_text_analysis
        try:
            signature = inspect.signature(func)
            accepts_status = (
                "stage_status" in signature.parameters
                or any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
            )
        except (TypeError, ValueError):
            accepts_status = True
        if accepts_status:
            return await func(ocr_blocks, vision_types, stage_status=stage_status)
        return await func(ocr_blocks, vision_types)

    def _extract_table_cells(self, table_html: str, block: OCRTextBlock) -> list[OCRTextBlock]:
        from app.services.vision.ocr_pipeline import extract_table_cells
        return extract_table_cells(table_html, block)

    def _expand_table_blocks(self, ocr_blocks: list[OCRTextBlock]) -> list[OCRTextBlock]:
        from app.services.vision.ocr_pipeline import expand_table_blocks
        return expand_table_blocks(ocr_blocks)

    def _match_entities_to_ocr(
        self,
        ocr_blocks: list[OCRTextBlock],
        entities: list[dict],
    ) -> list[SensitiveRegion]:
        from app.services.vision.ocr_pipeline import match_entities_to_ocr
        return match_entities_to_ocr(ocr_blocks, entities)

    def _apply_regex_fallback(
        self,
        ocr_blocks: list[OCRTextBlock],
        width: int,
        height: int,
    ) -> list[SensitiveRegion]:
        """Regex 兜底：作为文本链路最后一步，补齐 HaS Text 漏检的自定义正则类型。

        当没有配置任何带 regex_pattern 的启用类型时严格无操作（返回 []）。
        """
        from app.services import entity_type_service as ets

        regex_types = ets.get_regex_types(self.current_owner_id)
        if not regex_types:
            return []

        import re

        new_regions: list[SensitiveRegion] = []
        for item in regex_types:
            try:
                pat = re.compile(item.regex_pattern)
            except Exception as exc:  # noqa: BLE001 - never raise on bad pattern
                logger.warning("Regex fallback skipping type %s (bad pattern): %s", item.id, exc)
                continue
            for block in ocr_blocks:
                try:
                    if not pat.search(block.text or ""):
                        continue
                except Exception as exc:  # noqa: BLE001 - never raise on regex search
                    logger.warning("Regex fallback search failed for type %s: %s", item.id, exc)
                    break
                # De-dupe (block-level): skip if a region already covers this block
                # with the same custom type at the same location.
                if any(
                    region.entity_type == item.id
                    and region.left == block.left
                    and region.top == block.top
                    for region in new_regions
                ):
                    continue
                new_regions.append(SensitiveRegion(
                    text=block.text or "",
                    entity_type=item.id,
                    left=block.left,
                    top=block.top,
                    width=block.width,
                    height=block.height,
                    confidence=1.0,
                    source="regex_fallback",
                ))
        if new_regions:
            logger.info("Regex fallback added %d regions", len(new_regions))
        return new_regions

    def _draw_regions_on_image(
        self,
        image: Image.Image,
        regions: list[SensitiveRegion],
    ) -> Image.Image:
        from app.services.vision.image_pipeline import draw_regions_on_image
        return draw_regions_on_image(image, regions)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def detect_from_text_blocks(
        self,
        ocr_blocks: list[OCRTextBlock],
        vision_types: list | None = None,
    ) -> list[SensitiveRegion]:
        """Run HaS Text over already-positioned text blocks.

        This is used for born-digital PDF pages where PyMuPDF can provide
        native text coordinates. It skips image OCR but keeps semantic
        detection inside HaS Text.
        """
        perf_start = time.perf_counter()
        duration_ms: dict[str, Any] = {"prepare": 0, "ocr": 0}
        self.last_duration_ms = duration_ms
        self.last_ocr_blocks = list(ocr_blocks)

        if vision_types:
            requested_entity_type_ids = _canonicalize_image_text_types([t.id for t in vision_types])
            entity_type_ids = _semantic_entity_type_ids(requested_entity_type_ids)
            semantic_vision_types = _semantic_vision_types(vision_types)
            logger.info("PDF text layer enabled types: %s", [t.name for t in vision_types])
            ignored_types = [type_id for type_id in requested_entity_type_ids if type_id not in entity_type_ids]
            if ignored_types:
                logger.info("PDF OCR+HaS semantic path ignoring visual/non-semantic types: %s", ignored_types)
        else:
            entity_type_ids = _canonicalize_image_text_types([
                "PERSON", "ORG", "COMPANY", "PHONE", "EMAIL",
                "ID_CARD", "BANK_CARD", "ACCOUNT_NAME", "BANK_NAME",
                "ACCOUNT_NUMBER", "ADDRESS", "DATE",
            ])
            semantic_vision_types = vision_types

        entities = []
        expanded_blocks = self._expand_table_blocks(ocr_blocks)
        if expanded_blocks and _needs_has_text_analysis(entity_type_ids):
            ner_start = time.perf_counter()
            entities = await self._invoke_has_text_analysis(expanded_blocks, semantic_vision_types, duration_ms)
            duration_ms["has_ner"] = round((time.perf_counter() - ner_start) * 1000)
            logger.info(
                "PDF text layer HaS NER finished in %.2fs, entities=%d",
                duration_ms["has_ner"] / 1000,
                len(entities),
            )
        else:
            duration_ms["has_ner"] = 0
            logger.info("PDF text layer HaS NER skipped")

        if entities:
            match_start = time.perf_counter()
            regions = self._match_entities_to_ocr(ocr_blocks, entities)
            duration_ms["match"] = round((time.perf_counter() - match_start) * 1000)
        else:
            regions = []
            duration_ms["match"] = 0

        # 正则兜底：文本链路最后一步，补齐 HaS Text 漏检的自定义正则类型
        # （未配置任何 regex 类型时严格无操作）
        if ocr_blocks:
            regions.extend(self._apply_regex_fallback(ocr_blocks, 0, 0))

        duration_ms["draw"] = 0
        duration_ms["total"] = round((time.perf_counter() - perf_start) * 1000)
        logger.info(
            "PDF text layer total finished in %.2fs, regions=%d",
            duration_ms["total"] / 1000,
            len(regions),
        )
        return regions

    async def detect_and_draw(
        self,
        image_bytes: bytes,
        vision_types: list | None = None,
        draw_result: bool = True,
    ) -> tuple[list[SensitiveRegion], str | None]:
        """
        检测敏感信息并在图像上绘制

        流程：
        1. PaddleOCR 提取所有文字和精确坐标
        2. HaS 分析文字内容，识别敏感实体（不依赖坐标）
        3. 用文字匹配把敏感实体映射回 OCR 坐标

        Args:
            image_bytes: 图像字节
            vision_types: 用户启用的视觉类型配置列表 (VisionTypeConfig 对象)

        Returns:
            (敏感区域列表, base64编码的带框图像)
        """
        perf_start = time.perf_counter()
        duration_ms: dict[str, Any] = {}
        self.last_duration_ms = duration_ms
        self.last_ocr_blocks = []

        # 准备图像
        prepare_start = time.perf_counter()
        image, width, height = self._prepare_image(image_bytes)
        duration_ms["prepare"] = round((time.perf_counter() - prepare_start) * 1000)
        logger.info("Image size: %dx%d", width, height)

        # 把用户配置转换为类型 ID 列表
        visual_entity_type_ids: list[str] = []
        if vision_types:
            requested_entity_type_ids = _canonicalize_image_text_types([t.id for t in vision_types])
            entity_type_ids = _semantic_entity_type_ids(requested_entity_type_ids)
            visual_entity_type_ids = [
                type_id for type_id in requested_entity_type_ids if type_id in VISUAL_ONLY_ENTITY_TYPES
            ]
            semantic_vision_types = _semantic_vision_types(vision_types)
            logger.info("User enabled types: %s", [t.name for t in vision_types])
            ignored_types = [
                type_id
                for type_id in requested_entity_type_ids
                if type_id not in entity_type_ids and type_id not in visual_entity_type_ids
            ]
            if ignored_types:
                logger.info("OCR+HaS semantic path ignoring visual/non-semantic types: %s", ignored_types)
        else:
            entity_type_ids = _canonicalize_image_text_types([
                "PERSON", "ORG", "COMPANY", "PHONE", "EMAIL",
                "ID_CARD", "BANK_CARD", "ACCOUNT_NAME", "BANK_NAME",
                "ACCOUNT_NUMBER", "ADDRESS", "DATE",
            ])
            semantic_vision_types = vision_types

        # 1. Run PaddleOCR-VL first. PP-StructureV3 is an adaptive supplement
        # inside run_paddle_ocr for sparse, table-like, or short-field pages.
        # Visual regions such as seals are retained only when the caller
        # requested an OCR-supplied visual type.
        ocr_selected_entity_type_ids = list(dict.fromkeys([*entity_type_ids, *visual_entity_type_ids]))
        require_visual_regions = bool(visual_entity_type_ids)
        ocr_start = time.perf_counter()
        ocr_blocks, visual_regions = await asyncio.to_thread(
            self._run_paddle_ocr,
            image,
            require_visual_regions=require_visual_regions,
            selected_entity_types=ocr_selected_entity_type_ids,
            stage_status=duration_ms,
        )
        self.last_ocr_blocks = list(ocr_blocks)
        duration_ms["ocr"] = round((time.perf_counter() - ocr_start) * 1000)
        logger.info("OCR finished in %.2fs, blocks=%d", duration_ms["ocr"] / 1000, len(ocr_blocks))

        all_regions: list[SensitiveRegion] = []

        if visual_regions:
            requested_visual = set(visual_entity_type_ids)
            kept_visual_regions = [
                region
                for region in visual_regions
                if _canonical_image_text_type(region.entity_type) in requested_visual
            ]
            if kept_visual_regions:
                all_regions.extend(kept_visual_regions)
                logger.info(
                    "OCR+HaS retained %d OCR visual regions for requested visual types: %s",
                    len(kept_visual_regions),
                    sorted(requested_visual),
                )
            ignored_visual_count = len(visual_regions) - len(kept_visual_regions)
            if ignored_visual_count > 0:
                logger.info("OCR+HaS ignored %d unrequested OCR visual regions", ignored_visual_count)

        if ocr_blocks:
            logger.debug("OCR all texts: %s", [b.text for b in ocr_blocks])

            # 展开表格
            ocr_blocks_for_ner = self._expand_table_blocks(ocr_blocks)

            # 2. HaS NER
            entities = []
            if _needs_has_text_analysis(entity_type_ids):
                ner_start = time.perf_counter()
                entities = await self._invoke_has_text_analysis(ocr_blocks_for_ner, semantic_vision_types, duration_ms)
                duration_ms["has_ner"] = round((time.perf_counter() - ner_start) * 1000)
                logger.info("HaS NER finished in %.2fs, entities=%d", duration_ms["has_ner"] / 1000, len(entities))
            else:
                duration_ms["has_ner"] = 0
                logger.info("HaS NER skipped; selected vision types are visual-only")

            # 3. 映射实体到 OCR 坐标
            if entities:
                match_start = time.perf_counter()
                matched_regions = self._match_entities_to_ocr(ocr_blocks, entities)
                all_regions.extend(matched_regions)
                duration_ms["match"] = round((time.perf_counter() - match_start) * 1000)
                logger.info("OCR match finished in %.2fs, matches=%d", duration_ms["match"] / 1000, len(matched_regions))
            else:
                duration_ms["match"] = 0

        else:
            duration_ms.setdefault("has_ner", 0)
            duration_ms.setdefault("match", 0)
            logger.warning("PaddleOCR returned no text blocks")

        # 正则兜底：文本链路最后一步，补齐 HaS Text 漏检的自定义正则类型
        # （未配置任何 regex 类型时严格无操作）
        if ocr_blocks:
            all_regions.extend(self._apply_regex_fallback(ocr_blocks, width, height))

        logger.info("Final detected %d sensitive regions", len(all_regions))

        # 5. 绘制结果
        if not draw_result:
            duration_ms["draw"] = 0
            duration_ms["total"] = round((time.perf_counter() - perf_start) * 1000)
            logger.info("OCR/HaS total finished in %.2fs (draw skipped)", duration_ms["total"] / 1000)
            return all_regions, None

        draw_start = time.perf_counter()
        result_image = self._draw_regions_on_image(image, all_regions)
        duration_ms["draw"] = round((time.perf_counter() - draw_start) * 1000)
        logger.info("Draw finished in %.2fs", duration_ms["draw"] / 1000)

        # 6. Base64
        buffer = io.BytesIO()
        result_image.save(buffer, format="PNG")
        result_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        duration_ms["total"] = round((time.perf_counter() - perf_start) * 1000)
        logger.info("OCR/HaS total finished in %.2fs", duration_ms["total"] / 1000)

        return all_regions, result_base64

    async def apply_redaction(
        self,
        image_bytes: bytes,
        regions: list[SensitiveRegion],
        redaction_color: tuple[int, int, int] = (0, 0, 0),
    ) -> bytes:
        """Apply solid-color redaction over sensitive regions."""
        from app.services.vision.image_pipeline import apply_redaction as _apply_redaction

        image, _, _ = self._prepare_image(image_bytes)
        result = _apply_redaction(image, regions, redaction_color)

        buffer = io.BytesIO()
        result.save(buffer, format="PNG")
        return buffer.getvalue()


# Singleton
_ocr_has_service: OcrHasVisionService | None = None

def get_ocr_has_vision_service() -> OcrHasVisionService:
    global _ocr_has_service
    if _ocr_has_service is None:
        _ocr_has_service = OcrHasVisionService()
    return _ocr_has_service
