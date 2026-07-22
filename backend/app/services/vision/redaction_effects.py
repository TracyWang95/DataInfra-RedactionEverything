# Copyright 2026 DataInfra-RedactionEverything Contributors

"""遮盖效果的像素级原语：把一块矩形涂成实心/马赛克/模糊，以及画框预览。

从 vision_service 搬出来的纯函数：只吃图和坐标，不碰任何服务状态。和
``redaction/image_redactor.py`` 的区别是这里做的是"怎么涂"，那边做的是
"涂哪些框、涂完怎么落盘"。
"""

from PIL import Image, ImageDraw, ImageFilter

from app.models.schemas import BoundingBox

# 强度 1-100 的上限；马赛克块大小和模糊半径都从它线性推出来。
_REDACTION_STRENGTH_MAX = 100

_MOSAIC_BLOCK_MIN = 8
_MOSAIC_BLOCK_BASE = 4
_MOSAIC_BLOCK_EDGE_RATIO = 0.6

_BLUR_RADIUS_BASE = 1
_BLUR_RADIUS_MAX_SPAN = 24


def _hex_to_rgb(fill_color: str) -> tuple[int, int, int]:
    h = (fill_color or "#000000").strip().lstrip("#")
    if len(h) == 6:
        try:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except ValueError:
            pass
    return (0, 0, 0)

def _apply_region_effect(
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
        rgb = _hex_to_rgb(fill_color)
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

    rgb = _hex_to_rgb(fill_color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([x1, y1, x2, y2], fill=rgb)

def _apply_box_effect(
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
    _apply_region_effect(img, x1, y1, x2, y2, image_method, strength, fill_color)

