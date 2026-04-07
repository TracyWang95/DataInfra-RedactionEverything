# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
OCR Pipeline - PaddleOCR text extraction + HaS NER sensitive entity detection.

Responsibilities:
- Running PaddleOCR-VL microservice to extract text blocks and visual regions
- HTML table cell extraction and expansion
- Running HaS local NER model on OCR text to identify sensitive entities
- Matching NER entities back to OCR bounding boxes (exact + fuzzy)
- Regex-based supplementary detection on OCR text
"""
from __future__ import annotations

import asyncio
import html
import io
import logging
import re
from difflib import SequenceMatcher
from html.parser import HTMLParser
from typing import List, Optional, Tuple, Dict, Any

from PIL import Image, ImageOps

from app.services.hybrid_vision_service import SensitiveRegion, OCRTextBlock

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Image preparation
# ---------------------------------------------------------------------------

def prepare_image(image_bytes: bytes) -> Tuple[Image.Image, int, int]:
    """Decode image bytes, apply EXIF orientation, convert to RGB."""
    image = Image.open(io.BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image, image.width, image.height


# ---------------------------------------------------------------------------
# PaddleOCR extraction
# ---------------------------------------------------------------------------

def run_paddle_ocr(
    image: Image.Image,
    ocr_service: Any,
) -> Tuple[List[OCRTextBlock], List[SensitiveRegion]]:
    """
    Call PaddleOCR-VL microservice (port 8082) to extract text blocks and visual
    regions (e.g. seals).

    Returns:
        (text_blocks, visual_sensitive_regions)
    """
    if not ocr_service:
        logger.warning("OCR client not initialized")
        return [], []

    if not ocr_service.is_available():
        logger.warning("OCR microservice offline (8082)")
        return [], []

    blocks, visual_regions = _run_ocr_service(image, ocr_service)
    if blocks or visual_regions:
        logger.info("OCR got %d text blocks, %d visual regions", len(blocks), len(visual_regions))
    else:
        logger.info("No results from OCR service")
    return blocks, visual_regions


def _run_ocr_service(
    image: Image.Image,
    ocr_service: Any,
) -> Tuple[List[OCRTextBlock], List[SensitiveRegion]]:
    """Low-level call to OCRService (PaddleOCR-VL) and result conversion."""
    if not ocr_service or not ocr_service.is_available():
        return [], []

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    image_bytes = buffer.getvalue()

    from app.services.ocr_service import OCRServiceError
    try:
        items = ocr_service.extract_text_boxes(image_bytes)
    except OCRServiceError as e:
        logger.warning("OCR 服务异常 (transient=%s): %s", e.transient, e)
        if not e.transient:
            raise  # permanent error propagated
        items = []  # transient error degrades gracefully
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

        # clamp to image bounds
        left = max(0, min(left, width - 1))
        top = max(0, min(top, height - 1))
        right = max(left + 1, min(right, width))
        bottom = max(top + 1, min(bottom, height))

        # seals -> direct sensitive region
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
                color=(255, 0, 0),
            ))
            logger.info("Found SEAL @ (%d, %d, %d, %d)", left, top, right - left, bottom - top)
            continue

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


# ---------------------------------------------------------------------------
# HTML table expansion
# ---------------------------------------------------------------------------

def extract_table_cells(table_html: str, block: OCRTextBlock) -> List[OCRTextBlock]:
    """
    Parse an HTML table and create virtual OCRTextBlock per cell.

    Cell positions are estimated from row/column indices and the parent block's
    bounding box.
    """
    rows: List[List[tuple]] = []

    class TableCellParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_cell = False
            self.current_cell = ""
            self.current_row: List[tuple] = []
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
                    confidence=block.confidence * 0.9,
                ))
            col_idx += span

    return virtual_blocks


def expand_table_blocks(ocr_blocks: List[OCRTextBlock]) -> List[OCRTextBlock]:
    """Expand HTML table blocks into per-cell blocks for cleaner NER input."""
    expanded: List[OCRTextBlock] = []
    for block in ocr_blocks:
        if block.text.startswith("<table") and "</table>" in block.text:
            cell_blocks = extract_table_cells(block.text, block)
            if cell_blocks:
                expanded.extend(cell_blocks)
                continue
            # parse failed - strip HTML tags as fallback
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


# ---------------------------------------------------------------------------
# HaS NER text analysis
# ---------------------------------------------------------------------------

async def run_has_text_analysis(
    ocr_blocks: List[OCRTextBlock],
    has_client: Any,
    vision_types: Optional[list] = None,
) -> List[Dict[str, str]]:
    """
    Analyse OCR text with HaS local NER model to identify sensitive entities.
    Fully offline - no cloud API dependency.

    Args:
        ocr_blocks: OCR text blocks.
        has_client: HaSClient instance (may be None).
        vision_types: User-enabled vision type configs.

    Returns:
        [{type: "PERSON", text: "张三"}, ...]
    """
    if not ocr_blocks:
        return []

    # Lazy re-init if client was not available at startup
    if not has_client:
        try:
            from app.services.has_client import HaSClient
            has_client = HaSClient()
        except Exception as e:
            logger.error("HaS Client init failed: %s", e)
            return []

    if not has_client.is_available():
        logger.warning("HaS service not available, skipping NER")
        return []

    try:
        all_texts = [block.text for block in ocr_blocks if block.text.strip()]
        text_content = "\n".join(all_texts)

        MAX_VISION_TEXT_LENGTH = 500_000
        if len(text_content) > MAX_VISION_TEXT_LENGTH:
            logger.warning("OCR 文本过长 (%d chars)，截断至 %d", len(text_content), MAX_VISION_TEXT_LENGTH)
            text_content = text_content[:MAX_VISION_TEXT_LENGTH]

        if not text_content.strip():
            return []

        logger.info("HaS analyzing %d text blocks...", len(all_texts))

        # ----- type ID <-> Chinese name mappings -----
        from app.models.type_mapping import TYPE_ID_TO_CN as id_to_chinese

        VISUAL_ONLY_TYPES = {
            "SEAL", "SIGNATURE", "FINGERPRINT", "PHOTO",
            "QR_CODE", "HANDWRITING", "WATERMARK",
            "GLM_ID_CARD", "GLM_BANK_CARD",
        }

        if vision_types:
            chinese_types = []
            for vt in vision_types:
                if vt.id in VISUAL_ONLY_TYPES:
                    continue
                if vt.id in id_to_chinese:
                    chinese_types.append(id_to_chinese[vt.id])
                else:
                    chinese_types.append(vt.name)
            chinese_types = list(dict.fromkeys(chinese_types))
            logger.info("HaS using types for NER: %s", chinese_types)
        else:
            chinese_types = [
                "人名", "身份证号", "电话号码", "电子邮箱",
                "银行卡号", "银行账号", "机构名称", "详细地址",
                "日期", "金额", "案件编号", "当事人", "律师",
            ]
            logger.info("HaS using default types: %s", chinese_types)

        # HaS httpx is synchronous - offload to threadpool
        ner_result = await asyncio.to_thread(
            has_client.ner, text_content, chinese_types
        )

        if not ner_result or not isinstance(ner_result, dict):
            logger.info("HaS: no entities found by NER")
            return []

        logger.info("HaS NER result: %s", ner_result)

        # ----- reverse mapping: Chinese -> type ID -----
        from app.models.type_mapping import TYPE_CN_TO_ID
        chinese_to_id = dict(TYPE_CN_TO_ID)

        if vision_types:
            for vt in vision_types:
                if vt.id not in id_to_chinese:
                    chinese_to_id[vt.name] = vt.id

        entities = []
        min_len_by_type = {
            "PERSON": 2,
            "ORG": 2,
            "COMPANY": 2,
            "ADDRESS": 4,
        }

        for entity_type, entity_list in ner_result.items():
            if not entity_list:
                continue

            normalized_type = chinese_to_id.get(entity_type, entity_type.upper())
            min_len = min_len_by_type.get(normalized_type, 2)

            for entity_text in entity_list:
                text = entity_text.strip() if entity_text else ""
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


# ---------------------------------------------------------------------------
# Entity-to-OCR matching
# ---------------------------------------------------------------------------

def match_entities_to_ocr(
    ocr_blocks: List[OCRTextBlock],
    entities: List[Dict[str, str]],
) -> List[SensitiveRegion]:
    """
    Match HaS-detected entities to OCR text blocks using text matching to get
    precise bounding boxes.  Supports sub-word positioning, HTML table expansion,
    and fuzzy matching.
    """
    regions: List[SensitiveRegion] = []

    # Expand HTML tables into virtual cell blocks
    expanded_blocks: List[OCRTextBlock] = []
    for block in ocr_blocks:
        if block.text.startswith("<table") and "</table>" in block.text:
            cell_blocks = extract_table_cells(block.text, block)
            if cell_blocks:
                expanded_blocks.extend(cell_blocks)
                logger.debug("Expanded table into %d cells", len(cell_blocks))
            else:
                expanded_blocks.append(block)
        else:
            expanded_blocks.append(block)

    for entity in entities:
        entity_text = entity.get("text", "").strip()
        entity_type = entity.get("type", "UNKNOWN")

        if not entity_text:
            continue

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

        for block in expanded_blocks:
            block_text = block.text

            if block_text.startswith("<table"):
                continue

            # Exact containment match
            if entity_text in block_text:
                start_pos = block_text.find(entity_text)
                text_len = len(block_text)
                entity_len = len(entity_text)

                separator_count = (
                    block_text.count("：")
                    + block_text.count(":")
                    + block_text.count("|")
                )
                is_multi_field = separator_count >= 2 or "  " in block_text or "\t" in block_text

                if text_len > 100 or entity_len / text_len < 0.1 or is_multi_field:
                    sub_left = block.left
                    sub_width = block.width
                elif text_len > 0:
                    start_ratio = start_pos / text_len
                    width_ratio = entity_len / text_len

                    sub_left = int(block.left + start_ratio * block.width)
                    sub_width = max(int(width_ratio * block.width), 20)

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
                logger.debug(
                    "MATCH '%s' in '%s...' @ (%d, %d, %d, %d)",
                    entity_text, block_text[:20], sub_left, block.top, sub_width, block.height,
                )
                matched = True
                break

            # Fuzzy match (handles minor OCR errors)
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

        # Fallback: search in original (unexpanded) blocks
        if not matched:
            for block in ocr_blocks:
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
                    logger.debug(
                        "MATCH '%s' in table @ (%d, %d, %d, %d) [fallback]",
                        entity_text, block.left, block.top, block.width, block.height,
                    )
                break

    logger.info("Matched %d entities to OCR blocks", len(regions))
    return regions


# ---------------------------------------------------------------------------
# Regex supplementary detection
# ---------------------------------------------------------------------------

def apply_regex_rules(
    ocr_blocks: List[OCRTextBlock],
    entity_types: List[str],
) -> List[SensitiveRegion]:
    """
    Apply regex patterns to OCR text blocks for supplementary sensitive-info
    detection (IDs, phone numbers, emails, bank cards, etc.).
    """
    patterns = {
        # Contact info
        "PHONE": r"1[3-9]\d{9}",
        "EMAIL": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        # ID documents
        "ID_CARD": r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]",
        "BANK_CARD": r"[3-6]\d{15,18}",
        # Organizations
        "COMPANY": r"[\u4e00-\u9fa5]{2,20}(?:有限公司|股份有限公司|集团|公司)",
        # Bank names
        "BANK_NAME": r"[\u4e00-\u9fa5]{2,10}(?:银行)[\u4e00-\u9fa5]{0,10}(?:分行|支行|营业部)?",
        # Account numbers
        "ACCOUNT_NUMBER": r"(?:账号|帐号|账户号)[：:\s]*(\d{10,25})",
        # Dates
        "DATE": r"(?:\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)|(?:\d{4}年\d{1,2}月\d{1,2}日)",
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

                start_pos = match.start()
                matched_len = len(matched_text)

                if text_len > 0:
                    start_ratio = start_pos / text_len
                    width_ratio = matched_len / text_len

                    sub_left = int(block.left + start_ratio * block.width)
                    sub_width = max(int(width_ratio * block.width), 20)

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
