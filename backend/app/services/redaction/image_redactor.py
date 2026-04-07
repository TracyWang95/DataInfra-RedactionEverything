# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
图片匿名化模块
处理图片/扫描件的区域匿名化（马赛克 / 高斯模糊 / 纯色填充）
委托给 VisionService.apply_redaction 执行实际图像处理
"""
import logging

from app.models.schemas import BoundingBox, RedactionConfig, FileType

logger = logging.getLogger(__name__)


class ImageRedactorMixin:
    """
    图片匿名化方法集合
    设计为 mixin，由 Redactor 类继承使用
    要求宿主类具有 self.vision_service 属性（VisionService 实例）
    """

    async def _redact_image(
        self,
        file_path: str,
        file_type: FileType,
        selected_boxes: list[BoundingBox],
        output_path: str,
        config: RedactionConfig,
    ) -> int:
        """
        图片/扫描件匿名化：HaS Image 风格块级匿名化
        马赛克 / 高斯模糊 / 纯色填充，与文本 replacement_mode 无关

        Args:
            file_path: 输入文件路径
            file_type: 文件类型（PDF_SCANNED 或 IMAGE）
            selected_boxes: 选中的边界框列表
            output_path: 输出文件路径
            config: 匿名化配置

        Returns:
            匿名化区域数量
        """
        method = getattr(config, "image_redaction_method", None) or "fill"
        strength = int(getattr(config, "image_redaction_strength", None) or 25)
        fill_color = getattr(config, "image_fill_color", None) or "#000000"

        await self.vision_service.apply_redaction(
            file_path,
            file_type,
            selected_boxes,
            output_path,
            image_method=method,
            strength=max(1, min(100, strength)),
            fill_color=fill_color,
        )

        return len(selected_boxes)
