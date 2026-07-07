# Copyright 2026 DataInfra-RedactionEverything Contributors
"""成品水印（W2-1）：给匿名化输出叠加半透明平铺文案。

中文渲染不依赖系统字体：用 PyMuPDF 内置 CJK 字体（china-s）把文案渲染成
带 alpha 的小图块，图像输出走 PIL 平铺合成，PDF 输出逐页插字。
默认关闭（RedactionConfig.watermark_text 为空即 no-op）。
"""
from __future__ import annotations

import logging
import math
import os

import fitz
from PIL import Image

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
_FONTNAME = "china-s"
_GRAY = (0.45, 0.45, 0.45)
_PDF_OPACITY = 0.14
_IMAGE_ALPHA = 0.16
_ANGLE_DEG = 30.0


def apply_watermark(output_path: str, text: str | None) -> bool:
    """按扩展名分发；成功叠加返回 True，空文案/不支持类型返回 False。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".pdf":
        _watermark_pdf(output_path, cleaned)
        return True
    if ext in _IMAGE_EXTS:
        _watermark_image(output_path, cleaned)
        return True
    return False


def _render_text_tile(text: str, fontsize: int = 30) -> Image.Image:
    """用 fitz 内置 CJK 字体渲染透明底文字块（服务器无中文系统字体也可用）。"""
    width = max(80.0, fitz.get_text_length(text, fontname=_FONTNAME, fontsize=fontsize))
    doc = fitz.open()
    page = doc.new_page(width=width + 16, height=fontsize + 14)
    page.insert_text(
        (8, fontsize + 4), text, fontsize=fontsize, fontname=_FONTNAME, fill=_GRAY
    )
    pix = page.get_pixmap(alpha=True)
    png_bytes = pix.tobytes("png")
    doc.close()
    import io

    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def _tile_overlay(size: tuple[int, int], tile: Image.Image) -> Image.Image:
    """斜排平铺：旋转文字块后按对角网格铺满画布。"""
    rotated = tile.rotate(_ANGLE_DEG, expand=True, resample=Image.BICUBIC)
    # 压 alpha 到目标透明度
    alpha = rotated.getchannel("A").point(lambda a: int(a * _IMAGE_ALPHA))
    rotated.putalpha(alpha)
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    step_x = rotated.width + max(60, rotated.width // 2)
    step_y = rotated.height + max(50, rotated.height // 2)
    for row, y in enumerate(range(-rotated.height, size[1] + rotated.height, step_y)):
        offset = (row % 2) * (step_x // 2)
        for x in range(-rotated.width, size[0] + rotated.width, step_x):
            overlay.paste(rotated, (x + offset, y), rotated)
    return overlay


def _composite_frame(frame: Image.Image, tile: Image.Image) -> Image.Image:
    base = frame.convert("RGBA")
    overlay = _tile_overlay(base.size, tile)
    return Image.alpha_composite(base, overlay)


def _watermark_image(path: str, text: str) -> None:
    tile = _render_text_tile(text)
    img = Image.open(path)
    fmt = img.format
    n_frames = getattr(img, "n_frames", 1)
    if n_frames > 1:
        # 多页 TIFF（医疗常见）：逐帧加水印并完整保留页数
        frames = []
        for i in range(n_frames):
            img.seek(i)
            frames.append(_composite_frame(img, tile).convert("RGB"))
        frames[0].save(path, format=fmt, save_all=True, append_images=frames[1:])
        return
    out = _composite_frame(img, tile)
    if fmt in ("JPEG", "BMP") or (fmt == "TIFF" and out.mode == "RGBA"):
        out = out.convert("RGB")
    save_kwargs = {"quality": 92} if fmt == "JPEG" else {}
    out.save(path, format=fmt, **save_kwargs)


def _watermark_pdf(path: str, text: str) -> None:
    doc = fitz.open(path)
    try:
        for page in doc:
            rect = page.rect
            fontsize = max(18.0, min(rect.width, rect.height) / 16)
            text_len = fitz.get_text_length(text, fontname=_FONTNAME, fontsize=fontsize)
            step_x = text_len + 90
            step_y = fontsize * 7
            angle = math.radians(_ANGLE_DEG)
            row = 0
            y = step_y / 2
            while y < rect.height + step_y:
                x = -step_x / 2 + (row % 2) * (step_x / 2)
                while x < rect.width + step_x:
                    pivot = fitz.Point(x, y)
                    matrix = fitz.Matrix(math.cos(angle), -math.sin(angle), math.sin(angle), math.cos(angle), 0, 0)
                    try:
                        page.insert_text(
                            pivot,
                            text,
                            fontsize=fontsize,
                            fontname=_FONTNAME,
                            fill=_GRAY,
                            fill_opacity=_PDF_OPACITY,
                            morph=(pivot, matrix),
                            overlay=True,
                        )
                    except TypeError:
                        # 旧版 PyMuPDF 无 morph/fill_opacity：退化为水平浅色水印
                        page.insert_text(
                            pivot, text, fontsize=fontsize, fontname=_FONTNAME, fill=_GRAY
                        )
                    x += step_x
                y += step_y
                row += 1
        doc.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    finally:
        doc.close()
