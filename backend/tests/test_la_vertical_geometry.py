"""用 LocateAnything 的手写 2D 定位校正 OCR 文本框的纵向几何.

拍照表单上 PaddleOCR-VL 的字符框逐字都只带"整块 y 范围"(无逐字纵向), 所以手写值框
纵向虚高、且倾斜多列时错行。LA(LocateAnything)把手写 ground 成真 2D 框(纵向紧、
倾斜自动对齐)。同列同值的手写框与 OCR 值框横向重叠——以此为身份(无阈值), 采纳 LA
的 y/高度、保留 OCR 的 x(字符裁剪已准)。无匹配 LA 框则保留 OCR 框(绝不丢覆盖)。
"""
from app.models.schemas import BoundingBox
from app.services.vision_service import VisionService


def _b(x, y, w, h, source="ocr_has", text="v", type_="ID_CARD"):
    return BoundingBox(id=f"b{x}{y}", x=x, y=y, width=w, height=h, type=type_, text=text,
                       page=1, confidence=0.9, source=source)


def _la(x, y, w, h):
    return BoundingBox(id=f"la{x}{y}", x=x, y=y, width=w, height=h, type="handwriting",
                       text="", page=1, confidence=0.82, source="visual_features")


def test_adopts_la_tight_y_keeps_ocr_x():
    ocr = _b(0.35, 0.17, 0.19, 0.06)            # tall OCR value box
    la = _la(0.34, 0.18, 0.20, 0.029)            # tight LA box, x-overlaps, y-center inside
    out = VisionService()._adopt_la_vertical_geometry([ocr], [la])
    assert len(out) == 1
    r = out[0]
    assert abs(r.x - 0.35) < 1e-9 and abs(r.width - 0.19) < 1e-9   # OCR x kept
    assert abs(r.y - 0.18) < 1e-9 and abs(r.height - 0.029) < 1e-9  # LA y/height adopted


def test_tilt_picks_row_by_la_y():
    # OCR box tall, spanning into the next row; LA grounds the value's real row lower
    ocr = _b(0.70, 0.206, 0.23, 0.06)
    la = _la(0.703, 0.228, 0.255, 0.03)
    r = VisionService()._adopt_la_vertical_geometry([ocr], [la])[0]
    assert abs(r.y - 0.228) < 1e-9 and abs(r.height - 0.03) < 1e-9


def test_no_matching_la_keeps_ocr_box():
    ocr = _b(0.35, 0.17, 0.19, 0.06)
    la_other_column = _la(0.70, 0.18, 0.20, 0.03)   # different column, no x-overlap
    r = VisionService()._adopt_la_vertical_geometry([ocr], [la_other_column])[0]
    assert abs(r.y - 0.17) < 1e-9 and abs(r.height - 0.06) < 1e-9   # unchanged


def test_visual_and_textless_boxes_untouched():
    seal = _b(0.3, 0.1, 0.1, 0.1, source="visual_features", type_="official_seal", text="公章")
    la = _la(0.3, 0.12, 0.1, 0.03)
    r = VisionService()._adopt_la_vertical_geometry([seal], [la])[0]
    assert abs(r.y - 0.1) < 1e-9 and abs(r.height - 0.1) < 1e-9   # visual box not corrected


def test_picks_correct_column_among_multiple_la():
    ocr_left = _b(0.35, 0.17, 0.19, 0.06)
    la_left = _la(0.34, 0.18, 0.20, 0.029)
    la_right = _la(0.70, 0.18, 0.20, 0.029)
    r = VisionService()._adopt_la_vertical_geometry([ocr_left], [la_left, la_right])[0]
    assert abs(r.y - 0.18) < 1e-9   # took the x-overlapping left LA box


def test_la_box_outside_ocr_yspan_ignored():
    ocr = _b(0.35, 0.17, 0.19, 0.04)             # 0.17-0.21
    la_far = _la(0.34, 0.30, 0.20, 0.03)          # y-center 0.315, outside ocr y-span
    r = VisionService()._adopt_la_vertical_geometry([ocr], [la_far])[0]
    assert abs(r.y - 0.17) < 1e-9 and abs(r.height - 0.04) < 1e-9   # unchanged
