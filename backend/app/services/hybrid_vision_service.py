"""
Hybrid Vision Service - 图像脱敏核心服务
PaddleOCR-VL（独立微服务@8082）+ HaS 本地模型（敏感信息识别）混合模式
完全离线运行，不依赖云端 API
"""
from __future__ import annotations

import base64
import asyncio
import logging
import time
import io
import os
import re
import inspect
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

from PIL import Image, ImageDraw, ImageFont, ImageOps
from app.core.config import settings

# 敏感信息检测结果
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


class HybridVisionService:
    """
    混合视觉脱敏服务（完全离线）
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
        # OCRService 现在是 HTTP 客户端，直接初始化（不检查可用性，运行时按需检查）
        try:
            from app.services.ocr_service import ocr_service
            self._ocr_service = ocr_service
            logger.info("OCR client initialized (will check availability at runtime)")
        except Exception as e:
            logger.warning("OCR client init failed: %s", e)
            self._ocr_service = None
        
        # 初始化 HaS Client（本地模型）
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
    
    def _prepare_image(self, image_bytes: bytes) -> Tuple[Image.Image, int, int]:
        """准备图像，处理 EXIF 方向"""
        image = Image.open(io.BytesIO(image_bytes))
        # 处理 EXIF 方向
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
        return image, image.width, image.height
    
    def _run_paddle_ocr(self, image: Image.Image) -> Tuple[List[OCRTextBlock], List[SensitiveRegion]]:
        """
        通过 HTTP 调用 PaddleOCR-VL 微服务(8082) 获取文字位置
        返回：(文本块列表, 视觉敏感区域如公章)
        """
        if not self._ocr_service:
            logger.warning("OCR client not initialized")
            return [], []

        if not self._ocr_service.is_available():
            logger.warning("OCR microservice offline (8082)")
            return [], []

        blocks, visual_regions = self._run_ocr_service(image)
        if blocks or visual_regions:
            logger.info("OCR got %d text blocks, %d visual regions", len(blocks), len(visual_regions))
        else:
            logger.info("No results from OCR service")
        return blocks, visual_regions

    def _run_ocr_service(self, image: Image.Image) -> Tuple[List[OCRTextBlock], List[SensitiveRegion]]:
        """
        使用 OCRService (PaddleOCR-VL) 提取文本块和视觉元素
        
        Returns:
            (文本块列表, 视觉敏感区域列表如公章)
        """
        if not self._ocr_service or not self._ocr_service.is_available():
            return [], []

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        from app.services.ocr_service import OCRServiceError
        try:
            items = self._ocr_service.extract_text_boxes(image_bytes)
        except OCRServiceError as e:
            logger.warning("OCR 服务异常 (transient=%s): %s", e.transient, e)
            if not e.transient:
                raise  # 永久错误向上抛出
            items = []  # 瞬态错误降级为空结果
        if not items:
            return [], []

        width, height = image.size
        blocks: List[OCRTextBlock] = []
        visual_regions: List[SensitiveRegion] = []
        
        for item in items:
            left = int(item.x * width)
            top = int(item.y * height)
            w = int(item.width * width)
            h = int(item.height * height)
            right = max(left + max(w, 1), left + 1)
            bottom = max(top + max(h, 1), top + 1)

            # 裁剪到图像范围
            left = max(0, min(left, width - 1))
            top = max(0, min(top, height - 1))
            right = max(left + 1, min(right, width))
            bottom = max(top + 1, min(bottom, height))
            
            # 公章/印章区域直接作为敏感区域
            label = getattr(item, 'label', 'text') or 'text'
            if label == "seal" or item.text.strip() == "[公章]":
                visual_regions.append(SensitiveRegion(
                    text="[公章]",
                    entity_type="SEAL",
                    left=left,
                    top=top,
                    width=right - left,
                    height=bottom - top,
                    confidence=item.confidence,
                    source="paddleocr_vl",
                    color=(255, 0, 0),  # 红色
                ))
                logger.info("Found SEAL @ (%d, %d, %d, %d)", left, top, right-left, bottom-top)
                continue  # 公章不需要走 HaS 文字分析

            polygon = [
                [left, top],
                [right, top],
                [right, bottom],
                [left, bottom],
            ]
            blocks.append(OCRTextBlock(
                text=item.text,
                polygon=polygon,
                confidence=float(item.confidence),
            ))

        return blocks, visual_regions
    
    async def _run_has_text_analysis(
        self,
        ocr_blocks: List[OCRTextBlock],
        vision_types: Optional[list] = None,
    ) -> List[Dict[str, str]]:
        """
        用 HaS 本地模型分析 OCR 提取的文字，识别敏感信息
        完全离线，不依赖云端 API
        
        Args:
            ocr_blocks: OCR 识别的文本块
            vision_types: 用户启用的视觉类型配置列表
        
        Returns:
            [{type: "PERSON", text: "张三"}, ...]
        """
        if not ocr_blocks:
            return []
        
        # 动态检查 HaS 是否可用（服务可能后启动）
        if not self._has_client:
            try:
                from app.services.has_client import HaSClient
                self._has_client = HaSClient()
            except Exception as e:
                logger.error("HaS Client init failed: %s", e)
                return []

        if not self._has_client.is_available():
            logger.warning("HaS service not available, skipping NER")
            return []
        
        try:
            # 把所有 OCR 文字拼接起来
            all_texts = [block.text for block in ocr_blocks if block.text.strip()]
            text_content = "\n".join(all_texts)

            # 文本长度保护：OCR 大图可能产生大量文本，截断防止 HaS 超时/OOM
            MAX_VISION_TEXT_LENGTH = 500_000
            if len(text_content) > MAX_VISION_TEXT_LENGTH:
                logger.warning("OCR 文本过长 (%d chars)，截断至 %d", len(text_content), MAX_VISION_TEXT_LENGTH)
                text_content = text_content[:MAX_VISION_TEXT_LENGTH]

            if not text_content.strip():
                return []
            
            logger.info("HaS analyzing %d text blocks...", len(all_texts))
            
            # =====================================================================
            # 类型 ID -> 中文名 映射
            # 基于 GB/T 37964-2019 标识符分类
            # HaS 擅长语义理解，处理文字类敏感信息
            # 视觉类（签名/印章/指纹等）由 HaS Image / OCR 视觉分支处理，HaS NER 跳过
            # =====================================================================
            # 使用统一类型映射数据源
            from app.models.type_mapping import TYPE_ID_TO_CN as id_to_chinese
            
            # 视觉专属类型（HaS NER 文本侧不处理；由图像分割 / OCR 视觉承担）
            VISUAL_ONLY_TYPES = {
                "SEAL", "SIGNATURE", "FINGERPRINT", "PHOTO",
                "QR_CODE", "HANDWRITING", "WATERMARK",
                "GLM_ID_CARD", "GLM_BANK_CARD",  # 历史 ID，兼容旧配置
            }
            
            # 根据用户配置生成中文类型列表
            if vision_types:
                chinese_types = []
                for vt in vision_types:
                    # 跳过视觉类型
                    if vt.id in VISUAL_ONLY_TYPES:
                        continue
                    # 优先用标准 ID 映射
                    if vt.id in id_to_chinese:
                        chinese_types.append(id_to_chinese[vt.id])
                    else:
                        # 自定义类型用名称
                        chinese_types.append(vt.name)
                # 去重
                chinese_types = list(dict.fromkeys(chinese_types))
                logger.info("HaS using types for NER: %s", chinese_types)
            else:
                # 默认类型 - 基于国标覆盖主要标识符
                chinese_types = [
                    "人名", "身份证号", "电话号码", "电子邮箱",
                    "银行卡号", "银行账号", "机构名称", "详细地址",
                    "日期", "金额", "案件编号", "当事人", "律师",
                ]
                logger.info("HaS using default types: %s", chinese_types)
            
            # HaS 的 httpx 同步调用会阻塞事件循环，放到线程池中
            ner_result = await asyncio.to_thread(
                self._has_client.ner, text_content, chinese_types
            )
            
            # HaS ner() 返回格式：{类型: [实体列表]}，如 {"人名": ["张三"], "组织": ["腾讯"]}
            if not ner_result or not isinstance(ner_result, dict):
                logger.info("HaS: no entities found by NER")
                return []

            logger.info("HaS NER result: %s", ner_result)
            
            # =====================================================================
            # 中文 -> 类型 ID 反向映射（HaS 返回中文，需转回 ID）
            # HaS 可能返回不同的中文表述，需要多种映射
            # =====================================================================
            # 使用统一类型映射数据源
            from app.models.type_mapping import TYPE_CN_TO_ID
            chinese_to_id = dict(TYPE_CN_TO_ID)  # 浅拷贝以允许动态添加自定义类型
            
            # 如果有用户自定义类型，也加入映射
            if vision_types:
                for vt in vision_types:
                    if vt.id not in id_to_chinese:
                        chinese_to_id[vt.name] = vt.id
            
            # 转换为统一格式，过滤太短的实体
            entities = []
            min_len_by_type = {
                "PERSON": 2,   # 人名至少 2 字
                "ORG": 2,      # 组织至少 2 字
                "COMPANY": 2,  # 公司至少 2 字（简称如"腾讯"）
                "ADDRESS": 4,  # 地址至少 4 字
            }
            
            for entity_type, entity_list in ner_result.items():
                if not entity_list:
                    continue
                
                # 中文类型转换为 ID
                normalized_type = chinese_to_id.get(entity_type, entity_type.upper())
                min_len = min_len_by_type.get(normalized_type, 2)
                
                for entity_text in entity_list:
                    text = entity_text.strip() if entity_text else ""
                    # 过滤太短的实体
                    if len(text) < min_len:
                        logger.debug("HaS skipped too short: '%s' (%s)", text, normalized_type)
                        continue
                    
                    entities.append({
                        "type": normalized_type,
                        "text": text,
                    })
                    logger.debug("HaS found entity: %s (%s)", text, normalized_type)

            logger.info("HaS total %d sensitive entities found", len(entities))
            return entities
            
        except Exception as e:
            logger.exception("HaS text analysis failed: %s", e)
            return []
    
    def _extract_table_cells(self, table_html: str, block: OCRTextBlock) -> List[OCRTextBlock]:
        """
        从 HTML 表格中提取各个单元格，创建虚拟 OCRTextBlock。
        基于表格结构估算：
        - 按行分配 Y 轴位置
        - 按列分配 X 轴位置（支持简单 colspan）
        """
        import html
        from html.parser import HTMLParser
        
        rows: List[List[tuple[str, int]]] = []
        
        class TableCellParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_cell = False
                self.current_cell = ""
                self.current_row: List[tuple[str, int]] = []
                self.current_colspan = 1
            
            def handle_starttag(self, tag, attrs):
                if tag == "tr":
                    self.current_row = []
                if tag in ("td", "th"):
                    self.in_cell = True
                    self.current_cell = ""
                    self.current_colspan = 1
                    for k, v in attrs:
                        if k == "colspan":
                            try:
                                self.current_colspan = max(1, int(v))
                            except Exception:
                                self.current_colspan = 1
            
            def handle_endtag(self, tag):
                if tag in ("td", "th") and self.in_cell:
                    self.in_cell = False
                    cell_text = html.unescape(self.current_cell).strip()
                    self.current_row.append((cell_text, self.current_colspan))
                if tag == "tr":
                    if self.current_row:
                        rows.append(self.current_row)
                    self.current_row = []
            
            def handle_data(self, data):
                if self.in_cell:
                    self.current_cell += data
        
        try:
            parser = TableCellParser()
            parser.feed(table_html)
            if getattr(parser, "current_row", None):
                rows.append(parser.current_row)
        except Exception as e:
            logger.warning("Failed to parse table HTML: %s", e)
            return []
        
        if not rows:
            return []
        
        # 计算总行列数（基于 colspan 估算）
        num_rows = len(rows)
        num_cols = max(
            (sum(max(1, span) for _, span in row) for row in rows),
            default=0,
        )
        if num_rows == 0 or num_cols == 0:
            return []
        
        row_height = max(block.height / num_rows, 1.0)
        col_width = max(block.width / num_cols, 1.0)
        
        virtual_blocks: List[OCRTextBlock] = []
        for r_idx, row in enumerate(rows):
            col_idx = 0
            for cell_text, colspan in row:
                span = max(1, colspan)
                if cell_text.strip():
                    cell_left = block.left + col_idx * col_width
                    cell_top = block.top + r_idx * row_height
                    cell_width = col_width * span
                    cell_height = row_height
                    
                    virtual_blocks.append(OCRTextBlock(
                        text=cell_text,
                        polygon=[
                            [cell_left, cell_top],
                            [cell_left + cell_width, cell_top],
                            [cell_left + cell_width, cell_top + cell_height],
                            [cell_left, cell_top + cell_height],
                        ],
                        confidence=block.confidence * 0.9,  # 略微降低置信度
                    ))
                col_idx += span
        
        return virtual_blocks

    def _expand_table_blocks(self, ocr_blocks: List[OCRTextBlock]) -> List[OCRTextBlock]:
        """将 HTML 表格块展开为单元格，降低噪音并提升匹配精度。"""
        expanded: List[OCRTextBlock] = []
        for block in ocr_blocks:
            if block.text.startswith("<table") and "</table>" in block.text:
                cell_blocks = self._extract_table_cells(block.text, block)
                if cell_blocks:
                    expanded.extend(cell_blocks)
                    continue
                # 解析失败时，尽量去掉 HTML 标签，避免超长文本影响 NER
                plain = re.sub(r"<[^>]+>", " ", block.text)
                plain = re.sub(r"\s+", " ", plain).strip()
                if plain:
                    expanded.append(OCRTextBlock(
                        text=plain,
                        polygon=block.polygon,
                        confidence=block.confidence,
                    ))
                else:
                    expanded.append(block)
            else:
                expanded.append(block)
        return expanded
    
    def _match_entities_to_ocr(
        self,
        ocr_blocks: List[OCRTextBlock],
        entities: List[Dict[str, str]],
    ) -> List[SensitiveRegion]:
        """
        将 HaS 识别的敏感实体匹配到 OCR 文本块
        用文字匹配获取精确坐标，支持子词级别定位
        
        特殊处理：
        - HTML 表格：提取单元格后单独匹配
        - 长文本块：跳过子词定位，使用整块
        """
        regions: List[SensitiveRegion] = []
        
        # 预处理：展开 HTML 表格为虚拟单元格块
        expanded_blocks: List[OCRTextBlock] = []
        for block in ocr_blocks:
            if block.text.startswith("<table") and "</table>" in block.text:
                # 提取表格单元格作为虚拟块
                cell_blocks = self._extract_table_cells(block.text, block)
                if cell_blocks:
                    expanded_blocks.extend(cell_blocks)
                    logger.debug("Expanded table into %d cells", len(cell_blocks))
                else:
                    # 解析失败，保留原块
                    expanded_blocks.append(block)
            else:
                expanded_blocks.append(block)
        
        for entity in entities:
            entity_text = entity.get("text", "").strip()
            entity_type = entity.get("type", "UNKNOWN")
            
            if not entity_text:
                continue
            
            # 标准化类型名
            type_mapping = {
                "人名": "PERSON", "姓名": "PERSON", "昵称": "NICKNAME",
                "实验室名称": "LAB_NAME", "实验室": "LAB_NAME", "机构": "ORG",
                "电话": "PHONE", "手机号": "PHONE", "电话号码": "PHONE",
                "身份证": "ID_CARD", "身份证号": "ID_CARD",
                "银行卡": "BANK_CARD", "银行卡号": "BANK_CARD",
                "地址": "ADDRESS", "公司": "ORG", "公司名称": "ORG",
            }
            normalized_type = type_mapping.get(entity_type, entity_type.upper())
            
            matched = False
            
            # 在展开后的 OCR 块中查找匹配
            for block in expanded_blocks:
                block_text = block.text
                
                # 跳过 HTML 表格原始块（已展开为单元格）
                if block_text.startswith("<table"):
                    continue
                
                # 精确包含匹配
                if entity_text in block_text:
                    # 计算子词在行内的精确位置
                    start_pos = block_text.find(entity_text)
                    text_len = len(block_text)
                    entity_len = len(entity_text)
                    
                    # 多字段行（如“姓名：张三  电话：...”）子词定位误差大，直接用整块
                    separator_count = (
                        block_text.count("：")
                        + block_text.count(":")
                        + block_text.count("|")
                    )
                    is_multi_field = separator_count >= 2 or "  " in block_text or "\t" in block_text
                    
                    # 如果文本块太长（可能是表格或段落），或实体占比很小，或多字段行，
                    # 直接使用整个块的坐标
                    if text_len > 100 or entity_len / text_len < 0.1 or is_multi_field:
                        sub_left = block.left
                        sub_width = block.width
                    elif text_len > 0:
                        # 根据字符位置比例计算像素位置
                        start_ratio = start_pos / text_len
                        width_ratio = entity_len / text_len
                        
                        sub_left = int(block.left + start_ratio * block.width)
                        sub_width = max(int(width_ratio * block.width), 20)  # 最小宽度 20px
                        
                        # 如果敏感词占整个块的大部分(>80%)，直接用块坐标
                        if width_ratio > 0.8:
                            sub_left = block.left
                            sub_width = block.width
                    else:
                        sub_left = block.left
                        sub_width = block.width
                    
                    regions.append(SensitiveRegion(
                        text=entity_text,
                        entity_type=normalized_type,
                        left=sub_left,
                        top=block.top,
                        width=sub_width,
                        height=block.height,
                        confidence=1.0,
                        source="text_match",
                    ))
                    logger.debug("MATCH '%s' in '%s...' @ (%d, %d, %d, %d)", entity_text, block_text[:20], sub_left, block.top, sub_width, block.height)
                    matched = True
                    break
                    
                # 模糊匹配（处理 OCR 可能的小错误）
                elif SequenceMatcher(None, entity_text, block_text).ratio() > 0.85:
                    regions.append(SensitiveRegion(
                        text=entity_text,
                        entity_type=normalized_type,
                        left=block.left,
                        top=block.top,
                        width=block.width,
                        height=block.height,
                        confidence=0.9,
                        source="fuzzy_match",
                    ))
                    logger.debug("MATCH '%s' ~ '%s...' (fuzzy)", entity_text, block_text[:20])
                    matched = True
                    break
            
            # 如果在展开块中没找到，尝试在原始块中查找
            if not matched:
                for block in ocr_blocks:
                    # 特别处理表格：直接用整个表格框
                    if block.text.startswith("<table") and entity_text in block.text:
                        regions.append(SensitiveRegion(
                            text=entity_text,
                            entity_type=normalized_type,
                            left=block.left,
                            top=block.top,
                            width=block.width,
                            height=block.height,
                            confidence=0.8,
                            source="table_fallback",
                        ))
                        logger.debug("MATCH '%s' in table @ (%d, %d, %d, %d) [fallback]", entity_text, block.left, block.top, block.width, block.height)
                    break
        
        logger.info("Matched %d entities to OCR blocks", len(regions))
        return regions
    
    def _match_ocr_to_vlm(
        self,
        ocr_blocks: List[OCRTextBlock],
        vlm_regions: List[SensitiveRegion],
        iou_threshold: float = 0.3,
    ) -> List[SensitiveRegion]:
        """
        将 VLM 检测结果与 OCR 文本块匹配
        如果 VLM 区域与 OCR 块重叠，使用 OCR 的精确坐标
        """
        def calc_iou(box1: Tuple[int, int, int, int], box2: Tuple[int, int, int, int]) -> float:
            """计算两个边界框的 IoU"""
            x1 = max(box1[0], box2[0])
            y1 = max(box1[1], box2[1])
            x2 = min(box1[0] + box1[2], box2[0] + box2[2])
            y2 = min(box1[1] + box1[3], box2[1] + box2[3])
            
            if x2 <= x1 or y2 <= y1:
                return 0.0
            
            inter_area = (x2 - x1) * (y2 - y1)
            box1_area = box1[2] * box1[3]
            box2_area = box2[2] * box2[3]
            union_area = box1_area + box2_area - inter_area
            
            return inter_area / union_area if union_area > 0 else 0.0
        
        def normalize_text(text: str) -> str:
            if not text:
                return ""
            text = re.sub(r"\s+", "", text)
            text = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
            return text

        refined_regions: List[SensitiveRegion] = []
        
        for vlm_region in vlm_regions:
            vlm_box = (vlm_region.left, vlm_region.top, vlm_region.width, vlm_region.height)
            
            best_match: Optional[OCRTextBlock] = None
            best_iou = 0.0
            
            for ocr_block in ocr_blocks:
                ocr_box = (ocr_block.left, ocr_block.top, ocr_block.width, ocr_block.height)
                iou = calc_iou(vlm_box, ocr_box)
                
                if iou > best_iou and iou >= iou_threshold:
                    best_iou = iou
                    best_match = ocr_block
            
            if not best_match:
                # IoU 失败时，使用文本匹配兜底
                norm_vlm = normalize_text(vlm_region.text)
                if norm_vlm:
                    for ocr_block in ocr_blocks:
                        norm_ocr = normalize_text(ocr_block.text)
                        if norm_ocr and (norm_vlm in norm_ocr or norm_ocr in norm_vlm):
                            best_match = ocr_block
                            break
                        # 模糊匹配兜底
                        if norm_ocr:
                            ratio = SequenceMatcher(None, norm_vlm, norm_ocr).ratio()
                            if ratio >= 0.6:
                                best_match = ocr_block
                                break

            if best_match:
                # 使用 OCR 的精确坐标
                refined_regions.append(SensitiveRegion(
                    text=best_match.text,
                    entity_type=vlm_region.entity_type,
                    left=best_match.left,
                    top=best_match.top,
                    width=best_match.width,
                    height=best_match.height,
                    confidence=max(vlm_region.confidence, best_match.confidence),
                    source="merged",
                    color=vlm_region.color,
                ))
            else:
                # 没有匹配的 OCR 块，保留 VLM 结果
                refined_regions.append(vlm_region)
        
        return refined_regions
    
    def _apply_regex_rules(
        self,
        ocr_blocks: List[OCRTextBlock],
        entity_types: List[str],
    ) -> List[SensitiveRegion]:
        """
        对 OCR 结果应用正则规则检测
        覆盖各类敏感信息：证件号、联系方式、账号、网络标识等
        """
        # 敏感信息正则模式（正则为主力的类型）
        patterns = {
            # ===== 联系方式 =====
            "PHONE": r"1[3-9]\d{9}",  # 手机号
            "EMAIL": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            
            # ===== 证件号码 =====
            "ID_CARD": r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]",  # 18位身份证
            "BANK_CARD": r"[3-6]\d{15,18}",  # 银行卡号（3/4/5/6开头）
            
            # ===== 组织机构 =====
            "COMPANY": r"[\u4e00-\u9fa5]{2,20}(?:有限公司|股份有限公司|集团|公司)",  # 公司名（全称或简称）
            
            # ===== 开户行 =====
            "BANK_NAME": r"[\u4e00-\u9fa5]{2,10}(?:银行)[\u4e00-\u9fa5]{0,10}(?:分行|支行|营业部)?",  # 如：中国工商银行北京分行
            
            # ===== 账号 =====
            # 正则只作为辅助，主要依赖 HaS 模型语义识别
            "ACCOUNT_NUMBER": r"(?:账号|帐号|账户号)[：:\s]*(\d{10,25})",  # 账号：6222020200012345678
            
            # ===== 日期 =====
            "DATE": r"(?:\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)|(?:\d{4}年\d{1,2}月\d{1,2}日)",  # 2024-01-01 或 2024年1月1日
        }
        
        regions: List[SensitiveRegion] = []
        
        for block in ocr_blocks:
            block_text = block.text
            text_len = len(block_text)
            
            for entity_type, pattern in patterns.items():
                if entity_type not in entity_types:
                    continue
                
                matches = re.finditer(pattern, block_text)
                for match in matches:
                    matched_text = match.group()
                    
                    # 计算子词在行内的精确位置
                    start_pos = match.start()
                    matched_len = len(matched_text)
                    
                    if text_len > 0:
                        start_ratio = start_pos / text_len
                        width_ratio = matched_len / text_len
                        
                        sub_left = int(block.left + start_ratio * block.width)
                        sub_width = max(int(width_ratio * block.width), 20)
                        
                        # 如果匹配内容占整个块的大部分(>80%)，用块坐标
                        if width_ratio > 0.8:
                            sub_left = block.left
                            sub_width = block.width
                    else:
                        sub_left = block.left
                        sub_width = block.width
                    
                    regions.append(SensitiveRegion(
                        text=matched_text,
                        entity_type=entity_type,
                        left=sub_left,
                        top=block.top,
                        width=sub_width,
                        height=block.height,
                        confidence=1.0,
                        source="regex",
                    ))
        
        return regions
    
    def _draw_regions_on_image(
        self,
        image: Image.Image,
        regions: List[SensitiveRegion],
    ) -> Image.Image:
        """在图像上绘制敏感区域框"""
        draw_image = image.copy()
        draw = ImageDraw.Draw(draw_image)
        
        # 尝试加载中文字体
        font = None
        font_paths = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simsun.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        ]
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    font = ImageFont.truetype(fp, 14)
                    break
                except (OSError, IOError):
                    pass
        if not font:
            font = ImageFont.load_default()
        
        # 类型颜色映射（hex 转 RGB）
        type_colors = {
            # 人员相关
            "PERSON": (59, 130, 246),      # 蓝色
            
            # 组织机构
            "ORG": (16, 185, 129),         # 绿色
            "COMPANY": (20, 184, 166),     # 青绿色
            
            # 联系方式
            "PHONE": (249, 115, 22),       # 橙色
            "EMAIL": (234, 179, 8),        # 黄色
            
            # 证件号码
            "ID_CARD": (239, 68, 68),      # 红色
            "BANK_CARD": (236, 72, 153),   # 粉红色
            
            # 银行账户相关
            "ACCOUNT_NAME": (168, 85, 247),# 紫色
            "BANK_NAME": (124, 58, 237),   # 深紫色
            "ACCOUNT_NUMBER": (139, 92, 246), # 紫罗兰色
            
            # 地址
            "ADDRESS": (99, 102, 241),     # 靛蓝色
            
            # 日期
            "DATE": (161, 98, 7),          # 深金色
            
            # 视觉类
            "SEAL": (220, 20, 60),         # 深红色（公章）
        }
        
        for region in regions:
            color = type_colors.get(region.entity_type, (255, 0, 0))
            
            # 绘制边框
            x1, y1 = region.left, region.top
            x2, y2 = region.left + region.width, region.top + region.height
            draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
            
            # 绘制标签
            label = f"{region.entity_type}"
            if region.text:
                label += f": {region.text[:15]}"
            
            # 标签背景
            bbox = draw.textbbox((x1, y1 - 18), label, font=font)
            draw.rectangle([bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2], fill=color)
            draw.text((x1, y1 - 18), label, fill=(255, 255, 255), font=font)
        
        return draw_image
    
    async def detect_and_draw(
        self,
        image_bytes: bytes,
        vision_types: Optional[list] = None,
    ) -> Tuple[List[SensitiveRegion], str]:
        """
        检测敏感信息并在图像上绘制
        
        新流程（参考 document_redaction_vlm）：
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
        
        # 把用户配置转换为类型 ID 列表（用于正则规则和过滤）
        if vision_types:
            entity_type_ids = [t.id for t in vision_types]
            logger.info("User enabled types: %s", [t.name for t in vision_types])
        else:
            # 默认检测所有类型
            entity_type_ids = ["PERSON", "ORG", "COMPANY", "PHONE", "EMAIL",
                              "ID_CARD", "BANK_CARD", "ACCOUNT_NAME", "BANK_NAME",
                              "ACCOUNT_NUMBER", "ADDRESS", "DATE", "SEAL"]
        
        # 1. 运行 PaddleOCR-VL 提取文字和视觉元素（如公章）
        # OCR 推理较慢，放到线程池，避免阻塞后续流水线
        ocr_start = time.perf_counter()
        ocr_blocks, visual_regions = await asyncio.to_thread(self._run_paddle_ocr, image)
        logger.info("OCR finished in %.2fs, blocks=%d", time.perf_counter() - ocr_start, len(ocr_blocks))
        
        all_regions: List[SensitiveRegion] = []
        
        # 1.5 添加视觉敏感区域（公章等），根据用户配置过滤
        for vr in visual_regions:
            if vr.entity_type in entity_type_ids:
                all_regions.append(vr)
                logger.debug("VL added %s: %s", vr.entity_type, vr.text)
            else:
                logger.debug("VL skipped %s (not in enabled types)", vr.entity_type)
        
        if ocr_blocks:
            # 打印 OCR 识别到的所有文字（调试用）
            logger.debug("OCR all texts: %s", [b.text for b in ocr_blocks])
            
            # 表格类 HTML 文本会严重拖慢 NER，先展开/清洗
            ocr_blocks_for_ner = self._expand_table_blocks(ocr_blocks)
            
            # 2. 用 HaS 本地模型分析 OCR 文字，识别敏感实体（完全离线！）
            ner_start = time.perf_counter()
            entities = await self._run_has_text_analysis(ocr_blocks_for_ner, vision_types)
            logger.info("HaS NER finished in %.2fs, entities=%d", time.perf_counter() - ner_start, len(entities))
            
            # 3. 用文字匹配把敏感实体映射回 OCR 的精确坐标
            if entities:
                match_start = time.perf_counter()
                matched_regions = self._match_entities_to_ocr(ocr_blocks, entities)
                all_regions.extend(matched_regions)
                logger.info("OCR match finished in %.2fs, matches=%d", time.perf_counter() - match_start, len(matched_regions))
            
            # 4. 对 OCR 结果应用正则规则（补充检测）
            regex_start = time.perf_counter()
            regex_regions = self._apply_regex_rules(ocr_blocks_for_ner, entity_type_ids)
            all_regions = self._merge_regions(all_regions, regex_regions)
            logger.info("Regex finished in %.2fs, matches=%d", time.perf_counter() - regex_start, len(regex_regions))
        else:
            logger.warning("PaddleOCR returned no text blocks")

        logger.info("Final detected %d sensitive regions", len(all_regions))
        
        # 5. 在图像上绘制
        draw_start = time.perf_counter()
        result_image = self._draw_regions_on_image(image, all_regions)
        logger.info("Draw finished in %.2fs", time.perf_counter() - draw_start)
        
        # 6. 转换为 base64
        buffer = io.BytesIO()
        result_image.save(buffer, format="PNG")
        result_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        
        logger.info("Hybrid total finished in %.2fs", time.perf_counter() - perf_start)
        
        return all_regions, result_base64
    
    def _merge_regions(
        self,
        regions1: List[SensitiveRegion],
        regions2: List[SensitiveRegion],
        iou_threshold: float = 0.5,
    ) -> List[SensitiveRegion]:
        """合并两个区域列表，去除重复"""
        def calc_iou(r1: SensitiveRegion, r2: SensitiveRegion) -> float:
            x1 = max(r1.left, r2.left)
            y1 = max(r1.top, r2.top)
            x2 = min(r1.left + r1.width, r2.left + r2.width)
            y2 = min(r1.top + r1.height, r2.top + r2.height)
            
            if x2 <= x1 or y2 <= y1:
                return 0.0
            
            inter = (x2 - x1) * (y2 - y1)
            area1 = r1.width * r1.height
            area2 = r2.width * r2.height
            union = area1 + area2 - inter
            
            return inter / union if union > 0 else 0.0
        
        merged = list(regions1)
        
        for r2 in regions2:
            is_duplicate = False
            for r1 in merged:
                if calc_iou(r1, r2) >= iou_threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                merged.append(r2)
        
        return merged
    
    async def apply_redaction(
        self,
        image_bytes: bytes,
        regions: List[SensitiveRegion],
        redaction_color: Tuple[int, int, int] = (0, 0, 0),
    ) -> bytes:
        """
        应用脱敏（用纯色块覆盖敏感区域）
        """
        image, _, _ = self._prepare_image(image_bytes)
        draw = ImageDraw.Draw(image)
        
        for region in regions:
            x1, y1 = region.left, region.top
            x2, y2 = region.left + region.width, region.top + region.height
            draw.rectangle([x1, y1, x2, y2], fill=redaction_color)
        
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()


# 单例
_hybrid_service: Optional[HybridVisionService] = None

def get_hybrid_vision_service() -> HybridVisionService:
    global _hybrid_service
    if _hybrid_service is None:
        _hybrid_service = HybridVisionService()
    return _hybrid_service
