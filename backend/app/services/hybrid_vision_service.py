"""
Hybrid Vision Service - 图像匿名化核心服务
PaddleOCR-VL（独立微服务@8082）+ HaS 本地模型（敏感信息识别）混合模式
完全离线运行，不依赖云端 API

This module defines the shared data classes (SensitiveRegion, OCRTextBlock) and
the HybridVisionService orchestrator.  The heavy logic lives in three focused
sub-modules under ``app.services.vision``:

- ``ocr_pipeline``   – OCR extraction, HaS NER, entity matching, regex rules
- ``image_pipeline`` – VLM/OCR coordinate refinement, drawing, redaction
- ``region_merger``  – IoU calculation and region deduplication
"""
from __future__ import annotations

import base64
import asyncio
import logging
import time
import io
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

from PIL import Image

# ---------------------------------------------------------------------------
# Shared data classes (imported by sub-modules and external consumers)
# ---------------------------------------------------------------------------

@dataclass
class SensitiveRegion:
    """敏感区域"""
    text: str
    entity_type: str
    left: int      # 像素坐标
    top: int
    width: int
    height: int
    confidence: float = 1.0
    source: str = "unknown"  # "ocr", "vlm", "merged"
    color: Tuple[int, int, int] = (255, 0, 0)


@dataclass
class OCRTextBlock:
    """OCR 识别的文本块（bbox 在构造时缓存，避免每次 property 访问重算）"""
    text: str
    polygon: List[List[float]]  # 四边形顶点 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    confidence: float = 1.0

    # 构造后缓存的 bbox 值
    _bbox_cache: Tuple[int, int, int, int] = field(default=(0, 0, 0, 0), init=False, repr=False)

    def __post_init__(self):
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        self._bbox_cache = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))

    @property
    def bbox(self) -> Tuple[int, int, int, int]:
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
# Orchestrator
# ---------------------------------------------------------------------------

class HybridVisionService:
    """
    混合视觉匿名化服务（完全离线）
    1. PaddleOCR-VL：文字检测+识别（获取精确位置）
    2. HaS 本地模型：敏感信息类型识别（理解语义）
    3. 融合两者结果
    """

    def __init__(self):
        self._ocr_service = None   # OCR HTTP 客户端
        self._has_client = None    # HaS NER 客户端
        self._has_ready = False
        self._init_services()

    def _init_services(self):
        """初始化 OCR 和 HaS 服务"""
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
            if self._has_client.is_available():
                self._has_ready = True
                self._has_service = True
                logger.info("HaS Client init success (local model)")
            else:
                logger.warning("HaS service not available (is llama.cpp server running?)")
                self._has_ready = False
        except Exception as e:
            logger.warning("HaS Client init failed: %s", e)
            self._has_client = None
            self._has_ready = False

    # ------------------------------------------------------------------
    # Delegated helpers (keep old private names for any internal callers)
    # ------------------------------------------------------------------

    def _prepare_image(self, image_bytes: bytes) -> Tuple[Image.Image, int, int]:
        from app.services.vision.ocr_pipeline import prepare_image
        return prepare_image(image_bytes)

    def _run_paddle_ocr(self, image: Image.Image) -> Tuple[List[OCRTextBlock], List[SensitiveRegion]]:
        from app.services.vision.ocr_pipeline import run_paddle_ocr
        return run_paddle_ocr(image, self._ocr_service)

    async def _run_has_text_analysis(
        self,
        ocr_blocks: List[OCRTextBlock],
        vision_types: Optional[list] = None,
    ) -> List[dict]:
        # Lazy re-init (service may have started after us)
        if not self._has_client:
            try:
                from app.services.has_client import HaSClient
                self._has_client = HaSClient()
            except Exception:
                pass
        from app.services.vision.ocr_pipeline import run_has_text_analysis
        return await run_has_text_analysis(ocr_blocks, self._has_client, vision_types)

    def _extract_table_cells(self, table_html: str, block: OCRTextBlock) -> List[OCRTextBlock]:
        from app.services.vision.ocr_pipeline import extract_table_cells
        return extract_table_cells(table_html, block)

    def _expand_table_blocks(self, ocr_blocks: List[OCRTextBlock]) -> List[OCRTextBlock]:
        from app.services.vision.ocr_pipeline import expand_table_blocks
        return expand_table_blocks(ocr_blocks)

    def _match_entities_to_ocr(
        self,
        ocr_blocks: List[OCRTextBlock],
        entities: List[dict],
    ) -> List[SensitiveRegion]:
        from app.services.vision.ocr_pipeline import match_entities_to_ocr
        return match_entities_to_ocr(ocr_blocks, entities)

    def _apply_regex_rules(
        self,
        ocr_blocks: List[OCRTextBlock],
        entity_types: List[str],
    ) -> List[SensitiveRegion]:
        from app.services.vision.ocr_pipeline import apply_regex_rules
        return apply_regex_rules(ocr_blocks, entity_types)

    def _match_ocr_to_vlm(
        self,
        ocr_blocks: List[OCRTextBlock],
        vlm_regions: List[SensitiveRegion],
        iou_threshold: float = 0.3,
    ) -> List[SensitiveRegion]:
        from app.services.vision.image_pipeline import match_ocr_to_vlm
        return match_ocr_to_vlm(ocr_blocks, vlm_regions, iou_threshold)

    def _draw_regions_on_image(
        self,
        image: Image.Image,
        regions: List[SensitiveRegion],
    ) -> Image.Image:
        from app.services.vision.image_pipeline import draw_regions_on_image
        return draw_regions_on_image(image, regions)

    def _merge_regions(
        self,
        regions1: List[SensitiveRegion],
        regions2: List[SensitiveRegion],
        iou_threshold: float = 0.5,
    ) -> List[SensitiveRegion]:
        from app.services.vision.region_merger import merge_regions
        return merge_regions(regions1, regions2, iou_threshold)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def detect_and_draw(
        self,
        image_bytes: bytes,
        vision_types: Optional[list] = None,
    ) -> Tuple[List[SensitiveRegion], str]:
        """
        检测敏感信息并在图像上绘制

        流程：
        1. PaddleOCR 提取所有文字和精确坐标
        2. HaS 分析文字内容，识别敏感实体（不依赖坐标）
        3. 用文字匹配把敏感实体映射回 OCR 坐标
        4. 正则规则补充检测

        Args:
            image_bytes: 图像字节
            vision_types: 用户启用的视觉类型配置列表 (VisionTypeConfig 对象)

        Returns:
            (敏感区域列表, base64编码的带框图像)
        """
        perf_start = time.perf_counter()

        # 准备图像
        image, width, height = self._prepare_image(image_bytes)
        logger.info("Image size: %dx%d", width, height)

        # 把用户配置转换为类型 ID 列表
        if vision_types:
            entity_type_ids = [t.id for t in vision_types]
            logger.info("User enabled types: %s", [t.name for t in vision_types])
        else:
            entity_type_ids = [
                "PERSON", "ORG", "COMPANY", "PHONE", "EMAIL",
                "ID_CARD", "BANK_CARD", "ACCOUNT_NAME", "BANK_NAME",
                "ACCOUNT_NUMBER", "ADDRESS", "DATE", "SEAL",
            ]

        # 1. 运行 PaddleOCR-VL
        ocr_start = time.perf_counter()
        ocr_blocks, visual_regions = await asyncio.to_thread(self._run_paddle_ocr, image)
        logger.info("OCR finished in %.2fs, blocks=%d", time.perf_counter() - ocr_start, len(ocr_blocks))

        all_regions: List[SensitiveRegion] = []

        # 1.5 添加视觉敏感区域（公章等）
        for vr in visual_regions:
            if vr.entity_type in entity_type_ids:
                all_regions.append(vr)
                logger.debug("VL added %s: %s", vr.entity_type, vr.text)
            else:
                logger.debug("VL skipped %s (not in enabled types)", vr.entity_type)

        if ocr_blocks:
            logger.debug("OCR all texts: %s", [b.text for b in ocr_blocks])

            # 展开表格
            ocr_blocks_for_ner = self._expand_table_blocks(ocr_blocks)

            # 2. HaS NER
            ner_start = time.perf_counter()
            entities = await self._run_has_text_analysis(ocr_blocks_for_ner, vision_types)
            logger.info("HaS NER finished in %.2fs, entities=%d", time.perf_counter() - ner_start, len(entities))

            # 3. 映射实体到 OCR 坐标
            if entities:
                match_start = time.perf_counter()
                matched_regions = self._match_entities_to_ocr(ocr_blocks, entities)
                all_regions.extend(matched_regions)
                logger.info("OCR match finished in %.2fs, matches=%d", time.perf_counter() - match_start, len(matched_regions))

            # 4. 正则规则补充检测
            regex_start = time.perf_counter()
            regex_regions = self._apply_regex_rules(ocr_blocks_for_ner, entity_type_ids)
            all_regions = self._merge_regions(all_regions, regex_regions)
            logger.info("Regex finished in %.2fs, matches=%d", time.perf_counter() - regex_start, len(regex_regions))
        else:
            logger.warning("PaddleOCR returned no text blocks")

        logger.info("Final detected %d sensitive regions", len(all_regions))

        # 5. 绘制结果
        draw_start = time.perf_counter()
        result_image = self._draw_regions_on_image(image, all_regions)
        logger.info("Draw finished in %.2fs", time.perf_counter() - draw_start)

        # 6. Base64
        buffer = io.BytesIO()
        result_image.save(buffer, format="PNG")
        result_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        logger.info("Hybrid total finished in %.2fs", time.perf_counter() - perf_start)

        return all_regions, result_base64

    async def apply_redaction(
        self,
        image_bytes: bytes,
        regions: List[SensitiveRegion],
        redaction_color: Tuple[int, int, int] = (0, 0, 0),
    ) -> bytes:
        """应用匿名化（用纯色块覆盖敏感区域）"""
        from app.services.vision.image_pipeline import apply_redaction as _apply_redaction

        image, _, _ = self._prepare_image(image_bytes)
        result = _apply_redaction(image, regions, redaction_color)

        buffer = io.BytesIO()
        result.save(buffer, format="PNG")
        return buffer.getvalue()


# 单例
_hybrid_service: Optional[HybridVisionService] = None

def get_hybrid_vision_service() -> HybridVisionService:
    global _hybrid_service
    if _hybrid_service is None:
        _hybrid_service = HybridVisionService()
    return _hybrid_service
