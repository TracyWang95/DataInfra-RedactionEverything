# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
匿名化执行服务（薄编排层）
实际逻辑委托给 redaction 子包的三个专注模块：
  - replacement_strategy: 替换策略与实体映射
  - text_redactor: DOCX / PDF / TXT 文本替换
  - image_redactor: 图片区域匿名化
"""
import logging
import os
import uuid
from typing import Optional, Any

from app.core.config import settings
from app.models.schemas import (
    Entity,
    BoundingBox,
    RedactionConfig,
    FileType,
)
from app.services.vision_service import VisionService

# ---- Re-export 公共符号，保持向后兼容 ----
from app.services.redaction.replacement_strategy import (   # noqa: F401
    RedactionContext,
    build_preview_entity_map,
)
from app.services.redaction.text_redactor import TextRedactorMixin
from app.services.redaction.image_redactor import ImageRedactorMixin

logger = logging.getLogger(__name__)


class Redactor(TextRedactorMixin, ImageRedactorMixin):
    """匿名化执行器（编排入口）"""

    def __init__(self):
        self.vision_service = VisionService()

    def _resolve_existing_path(self, raw_path: Any, preferred_dir: str) -> Optional[str]:
        """Resolve legacy relative storage paths against the configured storage directory."""
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None

        path = raw_path.strip()
        if os.path.isabs(path) and os.path.exists(path):
            return os.path.realpath(path)

        basename = os.path.basename(path)
        backend_root = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
        project_root = os.path.realpath(os.path.join(backend_root, ".."))
        candidates: list[str] = []
        if basename:
            candidates.append(os.path.join(preferred_dir, basename))
            candidates.append(os.path.join(backend_root, os.path.basename(preferred_dir), basename))
            candidates.append(os.path.join(project_root, os.path.basename(preferred_dir), basename))
        if not os.path.isabs(path):
            candidates.append(os.path.join(preferred_dir, path))
            candidates.append(os.path.join(os.getcwd(), path))

        seen: set[str] = set()
        for candidate in candidates:
            real = os.path.realpath(candidate)
            if real in seen:
                continue
            seen.add(real)
            if os.path.exists(real):
                return real

        return os.path.realpath(path if os.path.isabs(path) else os.path.join(preferred_dir, basename or path))

    async def redact(
        self,
        file_info: dict,
        entities: list[Entity],
        bounding_boxes: list[BoundingBox],
        config: RedactionConfig,
    ) -> dict:
        """
        执行匿名化操作

        Args:
            file_info: 文件信息
            entities: 要匿名化的实体列表
            bounding_boxes: 要匿名化的图片区域列表
            config: 匿名化配置

        Returns:
            匿名化结果
        """
        file_type = file_info["file_type"]
        file_path = file_info["file_path"]

        # 创建匿名化上下文
        context = RedactionContext(config.replacement_mode)
        context.set_custom_replacements(config.custom_replacements)

        # 生成输出文件路径
        output_file_id = str(uuid.uuid4())
        logger.info("[redact] file_path=%s file_type=%s output_file_id=%s", file_path, file_type, output_file_id)
        original_ext = os.path.splitext(file_path)[1]
        output_ext = original_ext
        if file_type == FileType.DOC:
            output_ext = ".docx"
        output_path = os.path.realpath(os.path.join(settings.OUTPUT_DIR, f"{output_file_id}{output_ext}"))

        # 只处理选中的实体
        selected_entities = [e for e in entities if e.selected]
        selected_boxes = [b for b in bounding_boxes if b.selected]

        redacted_count = 0

        if file_type == FileType.DOC:
            # 先将 .doc 转换为 .docx 再处理
            converted_path = await self._convert_doc_to_docx(file_path)
            if not converted_path or not os.path.exists(converted_path):
                raise ValueError("DOC 转换失败，无法匿名化")
            redacted_count = await self._redact_docx(
                converted_path, output_path, selected_entities, context
            )
            # 清理转换后的临时文件
            if converted_path != file_path:
                try:
                    os.remove(converted_path)
                except OSError:
                    pass
        elif file_type == FileType.DOCX:
            # Word 文档匿名化
            redacted_count = await self._redact_docx(
                file_path, output_path, selected_entities, context
            )
        elif file_type == FileType.TXT:
            # 纯文本匿名化（.txt, .md, .html, .rtf）
            redacted_count = await self._redact_txt(
                file_path, output_path, selected_entities, context
            )
        elif file_type == FileType.PDF:
            # PDF 文档匿名化（文本型）
            redacted_count = await self._redact_pdf_text(
                file_path, output_path, selected_entities, context
            )
        elif file_type in [FileType.PDF_SCANNED, FileType.IMAGE]:
            # 图片/扫描件匿名化
            redacted_count = await self._redact_image(
                file_path, file_type, selected_boxes, output_path, config
            )

        return {
            "output_file_id": output_file_id,
            "output_path": output_path,
            "redacted_count": redacted_count,
            "entity_map": context.entity_map,
        }

    async def _convert_doc_to_docx(self, file_path: str) -> Optional[str]:
        """将 .doc 转换为 .docx（复用 FileParser 逻辑）"""
        try:
            from app.services.file_parser import FileParser
            parser = FileParser()
            return await parser._convert_doc_to_docx(file_path)
        except (OSError, ValueError, KeyError) as e:
            logger.error("DOC 转换失败: %s", e)
            return None

    async def get_comparison(self, file_info: dict) -> dict:
        """
        获取匿名化前后对比数据
        """
        file_type = file_info["file_type"]
        original_path = self._resolve_existing_path(file_info.get("file_path"), settings.UPLOAD_DIR) or file_info["file_path"]
        redacted_path = self._resolve_existing_path(file_info.get("output_path"), settings.OUTPUT_DIR)
        redacted_text = file_info.get("redacted_text")

        if not redacted_path or not os.path.exists(redacted_path):
            raise ValueError("匿名化文件不存在")

        # 统一转为字符串比较（兼容枚举和字符串）
        ft = str(file_type.value) if hasattr(file_type, 'value') else str(file_type)
        # 防御：output 扩展名与 file_type 不匹配时（旧脏数据），返回提示对比
        out_ext = os.path.splitext(redacted_path)[1].lower() if redacted_path else ""
        text_exts = {".docx", ".doc", ".txt", ".pdf"}
        if out_ext and out_ext not in text_exts and ft in ("docx", "doc", "txt", "pdf", "pdf_scanned"):
            logger.warning("output ext %s mismatches file_type %s, returning placeholder compare", out_ext, ft)
            return {
                "original": file_info.get("content", "[原始文本不可用]"),
                "redacted": f"[匿名化输出类型不匹配 ({out_ext})，请重新执行匿名化]",
                "changes": [],
            }
        is_docx = ft in ("docx", "doc")
        is_txt = ft == "txt"
        is_pdf = ft in ("pdf", "pdf_scanned")

        logger.debug("Compare file_type=%s, ft=%s, is_docx=%s, is_pdf=%s, redacted_path=%s", file_type, ft, is_docx, is_pdf, redacted_path)

        original_content = ""
        redacted_content = ""

        # .doc 文件匿名化后输出为 .docx，原始内容从解析缓存读取
        original_content_cached = file_info.get("content", "")

        if redacted_text:
            redacted_content = redacted_text
            if is_docx:
                original_content = original_content_cached or self._safe_extract_text(original_path, ft)
            elif is_txt:
                original_content = original_content_cached or self._read_txt(original_path)
            elif is_pdf:
                original_content = original_content_cached or self._extract_pdf_text(original_path)
            else:
                original_content = "[图片文件，请查看预览]"
        elif is_docx:
            original_content = original_content_cached or self._safe_extract_text(original_path, ft)
            redacted_content = self._extract_docx_text(redacted_path)
        elif is_txt:
            original_content = original_content_cached or self._read_txt(original_path)
            redacted_content = self._read_txt(redacted_path)
        elif is_pdf:
            original_content = original_content_cached or self._extract_pdf_text(original_path)
            redacted_content = self._extract_pdf_text(redacted_path)
        else:
            original_content = "[图片文件，请查看预览]"
            redacted_content = "[已匿名化图片，请查看预览]"

        # 计算变更
        changes = self._compute_changes(
            original_content,
            redacted_content,
            file_info.get("entity_map", {}),
        )

        return {
            "original": original_content,
            "redacted": redacted_content,
            "changes": changes,
        }

    def _compute_changes(
        self,
        original: str,
        redacted: str,
        entity_map: dict[str, str],
    ) -> list[dict]:
        """计算变更列表"""
        changes = []

        for original_text, replacement in entity_map.items():
            # 计算出现次数
            count = original.count(original_text)
            if count > 0:
                changes.append({
                    "original": original_text,
                    "replacement": replacement,
                    "count": count,
                })

        return changes
