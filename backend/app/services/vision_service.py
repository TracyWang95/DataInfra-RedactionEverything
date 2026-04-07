# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
视觉识别服务
- OCR + HaS：文字类
- HaS Image：8081 YOLO 微服务，隐私区域分割
"""
import asyncio
import base64
import io
import logging
import os
import time
import uuid

logger = logging.getLogger(__name__)
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from app.models.schemas import BoundingBox, FileType
from app.core.config import settings
from app.core.has_image_categories import SLUG_TO_NAME_ZH
from app.core.has_image_client import detect_privacy_regions
from app.services.file_parser import FileParser
from app.services.hybrid_vision_service import get_hybrid_vision_service


class VisionService:
    """视觉识别服务"""

    def __init__(self):
        self.file_parser = FileParser()
        self.hybrid_service = get_hybrid_vision_service()

    async def detect_sensitive_regions(
        self,
        file_path: str,
        file_type: FileType,
        page: int = 1,
        draw_result: bool = True,
        pipeline_mode: str = "ocr_has",
        pipeline_types: list = None,
    ) -> tuple[list[BoundingBox], Optional[str]]:
        if file_type == FileType.IMAGE:
            image_data = await self.file_parser.read_image(file_path)
        elif file_type in [FileType.PDF, FileType.PDF_SCANNED]:
            image_data = await self.file_parser.get_pdf_page_image(file_path, page)
        else:
            raise ValueError(f"Unsupported file type for vision: {file_type}")

        logger.info("Using pipeline: %s", pipeline_mode)

        if pipeline_mode == "has_image":
            bounding_boxes, result_image_base64 = await self._detect_with_has_image(
                image_data, page, pipeline_types
            )
        else:
            bounding_boxes, result_image_base64 = await self._detect_with_ocr_has(
                image_data, page, pipeline_types
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
    ) -> tuple[list[BoundingBox], Optional[str]]:
        if file_type == FileType.IMAGE:
            image_data = await self.file_parser.read_image(file_path)
        elif file_type in [FileType.PDF, FileType.PDF_SCANNED]:
            image_data = await self.file_parser.get_pdf_page_image(file_path, page)
        else:
            raise ValueError(f"Unsupported file type for vision: {file_type}")

        all_boxes: list[BoundingBox] = []
        total_start = time.perf_counter()

        async def timed(label: str, coro):
            start = time.perf_counter()
            try:
                return await coro
            finally:
                elapsed = time.perf_counter() - start
                logger.info("%s finished in %.2fs", label, elapsed)

        ocr_task = None
        hi_task = None

        if ocr_has_types:
            logger.info("Running OCR+HaS with %d types...", len(ocr_has_types))
            ocr_task = asyncio.create_task(
                timed("ocr_has", self._detect_with_ocr_has(image_data, page, ocr_has_types))
            )
        else:
            logger.info("OCR+HaS skipped (no types enabled)")

        if has_image_types:
            logger.info("Running HaS Image with %d types...", len(has_image_types))
            hi_task = asyncio.create_task(
                timed("has_image", self._detect_with_has_image(image_data, page, has_image_types))
            )
        else:
            logger.info("HaS Image skipped (no types enabled)")

        tasks = []
        labels = []
        if ocr_task:
            tasks.append(ocr_task)
            labels.append("ocr_has")
        if hi_task:
            tasks.append(hi_task)
            labels.append("has_image")

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            logger.info("两路均未运行，将返回空结果")
            results = []

        for label, result in zip(labels, results):
            if isinstance(result, Exception):
                logger.error("%s failed: %s", label, result)
                continue
            boxes, _ = result
            all_boxes.extend(boxes)
            logger.info("%s found %d regions", label, len(boxes))

        all_boxes = self._deduplicate_boxes(all_boxes)

        img = Image.open(io.BytesIO(image_data))
        img = ImageOps.exif_transpose(img)
        result_image_base64 = self._draw_boxes_on_image(img, all_boxes)

        total_elapsed = time.perf_counter() - total_start
        logger.info("Dual pipeline total: %d regions, %.2fs", len(all_boxes), total_elapsed)
        return all_boxes, result_image_base64

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

    def _deduplicate_boxes(
        self,
        boxes: list[BoundingBox],
        iou_threshold: float = 0.3,
    ) -> list[BoundingBox]:
        """去重：OCR 优先；对新增 box 按 x 排序后仅与邻近 box 比较 IoU，
        将最坏 O(n*m) 降低为 O(n*k)，k 为 x 方向邻近数量（远小于 n）。"""
        if len(boxes) <= 1:
            return boxes

        ocr_boxes = [b for b in boxes if b.source == "ocr_has"]
        hi_boxes = [b for b in boxes if b.source == "has_image"]
        other_boxes = [b for b in boxes if b.source not in ("ocr_has", "has_image")]

        result = list(ocr_boxes)

        def _overlaps_any(candidate: BoundingBox, existing: list[BoundingBox]) -> bool:
            """检查 candidate 是否与 existing 中任何 box 的 IoU 超过阈值。
            按 x 排序后利用 x 范围快速跳过不可能重叠的 box。"""
            cx_end = candidate.x + candidate.width
            for eb in existing:
                # x 方向无交集则跳过
                if eb.x > cx_end or eb.x + eb.width < candidate.x:
                    continue
                if self._calculate_iou(candidate, eb) > iou_threshold:
                    return True
            return False

        # 按 x 排序加速剪枝
        hi_boxes.sort(key=lambda b: b.x)
        for hi_box in hi_boxes:
            if _overlaps_any(hi_box, ocr_boxes):
                logger.debug("DEDUP HaS-Image '%s' overlaps OCR box, skipping", hi_box.type)
            else:
                result.append(hi_box)

        other_boxes.sort(key=lambda b: b.x)
        for other_box in other_boxes:
            if not _overlaps_any(other_box, result):
                result.append(other_box)

        removed_count = len(boxes) - len(result)
        if removed_count > 0:
            logger.info("DEDUP removed %d duplicate boxes", removed_count)

        return result

    async def _detect_with_ocr_has(
        self,
        image_data: bytes,
        page: int,
        pipeline_types: list = None,
    ) -> tuple[list[BoundingBox], Optional[str]]:
        regions, result_image_base64 = await self.hybrid_service.detect_and_draw(
            image_data,
            vision_types=pipeline_types,
        )

        img = Image.open(io.BytesIO(image_data))
        img = ImageOps.exif_transpose(img)
        width, height = img.size

        bounding_boxes = []
        for i, region in enumerate(regions):
            bbox = BoundingBox(
                id=f"ocr_{i}_{uuid.uuid4().hex[:8]}",
                x=region.left / width,
                y=region.top / height,
                width=region.width / width,
                height=region.height / height,
                type=region.entity_type,
                text=region.text,
                page=page,
                source="ocr_has",
            )
            bounding_boxes.append(bbox)

        return bounding_boxes, result_image_base64

    async def _detect_with_has_image(
        self,
        image_data: bytes,
        page: int,
        pipeline_types: list = None,
    ) -> tuple[list[BoundingBox], Optional[str]]:
        slugs = [t.id for t in pipeline_types] if pipeline_types else None
        raw_boxes = await detect_privacy_regions(
            image_data,
            conf=settings.HAS_IMAGE_CONF,
            category_slugs=slugs,
        )

        img = Image.open(io.BytesIO(image_data))
        img = ImageOps.exif_transpose(img)

        bounding_boxes: list[BoundingBox] = []
        for i, b in enumerate(raw_boxes):
            slug = str(b.get("category", ""))
            name_zh = SLUG_TO_NAME_ZH.get(slug, slug)
            bbox = BoundingBox(
                id=f"hi_{i}_{uuid.uuid4().hex[:8]}",
                x=float(b["x"]),
                y=float(b["y"]),
                width=float(b["width"]),
                height=float(b["height"]),
                type=slug,
                text=name_zh,
                page=page,
                source="has_image",
            )
            bounding_boxes.append(bbox)

        result_image_base64 = self._draw_boxes_on_image(img, bounding_boxes)
        return bounding_boxes, result_image_base64

    def _draw_boxes_on_image(
        self,
        image: Image.Image,
        bounding_boxes: list[BoundingBox],
    ) -> str:
        import os

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
        except (OSError, IOError):
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

            label_zh = bbox.text or SLUG_TO_NAME_ZH.get(bbox.type, bbox.type)
            if len(label_zh) > 12:
                label_zh = label_zh[:12] + "…"
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
        """在 RGB 图像上对矩形区域做马赛克 / 高斯模糊 / 纯色填充（与 HaS Image 文档一致）。"""
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
            block = max(2, int(2 + (s / 100.0) * (min(w, h) // 8)))
            small_w = max(1, w // block)
            small_h = max(1, h // block)
            small = roi.resize((small_w, small_h), Image.Resampling.NEAREST)
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

    async def apply_redaction(
        self,
        file_path: str,
        file_type: FileType,
        bounding_boxes: list[BoundingBox],
        output_path: str,
        image_method: str = "fill",
        strength: int = 25,
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
            x1 = int(bbox.x * width)
            y1 = int(bbox.y * height)
            x2 = int((bbox.x + bbox.width) * width)
            y2 = int((bbox.y + bbox.height) * height)
            self._apply_region_effect(image, x1, y1, x2, y2, image_method, strength, fill_color)

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
                x1 = int(bbox.x * pix.width)
                y1 = int(bbox.y * pix.height)
                x2 = int((bbox.x + bbox.width) * pix.width)
                y2 = int((bbox.y + bbox.height) * pix.height)
                self._apply_region_effect(img, x1, y1, x2, y2, image_method, strength, fill_color)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, stream=buf.read())

        doc.close()
        new_doc.save(output_path)
        new_doc.close()

        return output_path

    async def preview_redaction(
        self,
        file_path: str,
        file_type: FileType,
        bounding_boxes: list[BoundingBox],
        page: int = 1,
        image_method: str = "fill",
        strength: int = 25,
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
            x1 = int(bbox.x * width)
            y1 = int(bbox.y * height)
            x2 = int((bbox.x + bbox.width) * width)
            y2 = int((bbox.y + bbox.height) * height)
            self._apply_region_effect(
                image,
                x1,
                y1,
                x2,
                y2,
                image_method,
                max(1, min(100, strength)),
                fill_color,
            )

        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)

        return output.getvalue()
