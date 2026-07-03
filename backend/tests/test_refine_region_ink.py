"""缩墨（_refine_ocr_region_to_ink）在低清照片值级小框上的覆盖回归。

回归背景（2026-07-02 测试反馈"识别出来了但遮盖面积小"）：协和报告照片
（660×1174 低清）上 `_remove_ocr_rule_lines` 的行程阈值是相对裁剪框宽度的，
值级小框里糊连的笔画整行被误判为表格线删除（K124016 墨水 825→28 像素、
心血管内科 1431→13），缩墨随之把 19-20px 高的值框收成 3-4px 细条 → 打码
只剩一条缝。修复：剔线若删掉过半墨水即视为误杀、回退原始墨水掩码
（多遮一条表格线无害，少遮值是泄漏）。

夹具 assets/lowres_photo_value_crop.png = 原图 (90,215)-(190,280) 实裁；
框坐标为裁剪系：科室值"心血管内科"=(15,10,72,20)、检查号值"K124016"=(19,34,44,19)。
"""

from pathlib import Path

import numpy as np
from PIL import Image

from app.services.vision_service import VisionService

FIXTURE = Path(__file__).parent / "assets" / "lowres_photo_value_crop.png"


def _fixture_image() -> Image.Image:
    return Image.open(FIXTURE).convert("RGB")


def test_lowres_value_crop_keeps_exam_no_coverage():
    img = _fixture_image()
    left, top, width, height = VisionService._refine_ocr_region_to_ink(img, 19, 34, 44, 19)
    # 修复前收成 44x4 细条；值框必须基本保住
    assert width >= 44 * 0.9, f"width shrunk to {width}"
    assert height >= 19 * 0.7, f"height shrunk to {height}"


def test_lowres_value_crop_keeps_department_coverage():
    img = _fixture_image()
    left, top, width, height = VisionService._refine_ocr_region_to_ink(img, 15, 10, 72, 20)
    # 修复前收成 14x3 细条
    assert width >= 72 * 0.85, f"width shrunk to {width}"
    assert height >= 20 * 0.7, f"height shrunk to {height}"


def test_genuine_rule_line_is_still_pruned():
    """真正的表格线（占墨水少数）仍然被剔除：缩墨框贴住字形、不含底部长线。"""
    img_arr = np.full((40, 400, 3), 235, dtype=np.uint8)  # 浅色纸面
    img_arr[5:21, 10:110] = 40   # 密集字形块 100x16=1600 墨水像素
    img_arr[35:37, 0:400] = 40   # 全宽表格线 400x2=800 像素（少数）
    img = Image.fromarray(img_arr, "RGB")

    left, top, width, height = VisionService._refine_ocr_region_to_ink(img, 0, 0, 400, 40)
    bottom = top + height
    assert bottom <= 30, f"rule line at rows 35-36 not pruned (bottom={bottom})"
    assert width <= 130, f"box should hug the glyph block, got width={width}"
