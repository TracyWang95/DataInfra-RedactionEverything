"""用 LocateAnything 的手写 2D 定位收紧 OCR 文本框的纵向虚高——保覆盖版 (R7c).

拍照表单上 PaddleOCR-VL 的字符框逐字都只带"整块 y 范围"(无逐字纵向), 所以手写值框
纵向虚高、且倾斜多列时可能错行。旧实现"裸替换 y/height 为 LA 的"有两个风险:
(1) LA 只框最密笔画, 会欠盖 descender/花体尾巴; (2) 错行/歧义时可能纠到错误行。

R7c 把它改成"保覆盖消费者", 只做纯几何合并 (GPU 取 LA/实测墨迹由调用方做):
  (a) 错行守卫: 候选 LA 必须包含 OCR 框的 y-center; 多候选取中心距最近; cy 落 gutter -> 保留原框。
  (b) 歧义弃用: >=2 个纵向互不重叠的同列 LA 候选 -> 无法确定行 -> 保留原框。
  (c) 保覆盖高度: 新框纵向 = hull(LA 框 ∪ 已证墨迹 hull), 永不缩到墨迹以下。
  (d) 仅对确证虚高 (height >= 2*doc_line_h) 的框触发, 其余框原样返回。
所有失败路径 -> 保留原过覆盖框 (0 泄露: 相对裸替换是严格加固)。
"""
from app.models.schemas import BoundingBox
from app.services.vision_service import VisionService


def _b(x, y, w, h, id_=None, source="ocr_has", text="v", type_="ID_CARD"):
    return BoundingBox(id=id_ or f"b{x}{y}", x=x, y=y, width=w, height=h, type=type_,
                       text=text, page=1, confidence=0.9, source=source)


def _la(x, y, w, h):
    return BoundingBox(id=f"la{x}{y}", x=x, y=y, width=w, height=h, type="handwriting",
                       text="", page=1, confidence=0.82, source="visual_features")


DOC_LH = 0.02  # self-calibrated document line height; 2x = 0.04 is the oversize floor


# ---- (d) only confirmed-oversize boxes are touched ---------------------------

def test_non_oversize_box_returned_unchanged():
    # height 0.03 < 2*doc_line_h (0.04): a normal box, never touched even with a
    # matching LA and a measured ink hull.
    ocr = _b(0.35, 0.17, 0.19, 0.03, id_="e1")
    la = _la(0.34, 0.175, 0.20, 0.012)
    out = VisionService()._adopt_la_vertical_geometry(
        [ocr], [la], DOC_LH, {"e1": (0.176, 0.188)})
    r = out[0]
    assert (r.y, r.height) == (0.17, 0.03)  # untouched


# ---- (a) error-row guard -----------------------------------------------------

def test_adopts_row_whose_la_contains_cy():
    # Tall OCR box spans two LA rows in its column. la_true contains the OCR
    # y-center; la_above sits in the span but ends before cy (does NOT contain
    # it) yet overlaps la_true (single row-cluster -> not ambiguous). We must
    # adopt la_true's row, floored by the measured ink hull.
    ocr = _b(0.35, 0.17, 0.19, 0.06, id_="e1")           # [0.17,0.23], cy=0.20
    la_true = _la(0.34, 0.19, 0.20, 0.03)                # [0.19,0.22], contains 0.20
    la_above = _la(0.34, 0.17, 0.20, 0.025)              # [0.17,0.195], overlaps la_true, no cy
    ink = {"e1": (0.185, 0.225)}                          # descender to 0.225
    r = VisionService()._adopt_la_vertical_geometry([ocr], [la_true, la_above], DOC_LH, ink)[0]
    assert abs(r.x - 0.35) < 1e-9 and abs(r.width - 0.19) < 1e-9   # OCR x kept
    # hull(la_true [0.19,0.22] ∪ ink [0.185,0.225]) = [0.185,0.225]
    assert abs(r.y - 0.185) < 1e-9
    assert abs((r.y + r.height) - 0.225) < 1e-9


def test_center_nearest_among_cy_containing_candidates():
    # Two overlapping LA both contain cy; pick the one whose center is nearest.
    ocr = _b(0.35, 0.17, 0.19, 0.06, id_="e1")           # cy=0.20
    la_near = _la(0.34, 0.185, 0.20, 0.03)               # [0.185,0.215], center 0.200
    la_far = _la(0.34, 0.19, 0.20, 0.045)                # [0.19,0.235], center 0.2125, overlaps la_near
    ink = {"e1": (0.188, 0.212)}
    r = VisionService()._adopt_la_vertical_geometry([ocr], [la_near, la_far], DOC_LH, ink)[0]
    # la_near chosen: hull([0.185,0.215] ∪ [0.188,0.212]) = [0.185,0.215]
    assert abs(r.y - 0.185) < 1e-9 and abs((r.y + r.height) - 0.215) < 1e-9


def test_cy_in_gutter_between_rows_keeps_original():
    # OCR y-center falls in the gutter between two non-overlapping LA rows: no
    # row contains it -> refuse to correct -> keep the over-covering OCR box.
    ocr = _b(0.35, 0.15, 0.19, 0.12, id_="e1")           # [0.15,0.27], cy=0.21
    la_hi = _la(0.34, 0.16, 0.20, 0.025)                 # [0.16,0.185]
    la_lo = _la(0.34, 0.235, 0.20, 0.025)                # [0.235,0.26]  (0.21 in the gutter)
    r = VisionService()._adopt_la_vertical_geometry(
        [ocr], [la_hi, la_lo], DOC_LH, {"e1": (0.20, 0.22)})[0]
    assert (r.y, r.height) == (0.15, 0.12)               # unchanged


# ---- (b) ambiguity -----------------------------------------------------------

def test_two_disjoint_la_rows_keep_original_even_if_one_contains_cy():
    # A second distinct (vertically disjoint) LA row exists in the column, so
    # the row is ambiguous -> keep original, EVEN THOUGH la_one contains cy.
    ocr = _b(0.35, 0.15, 0.19, 0.12, id_="e1")           # [0.15,0.27], cy=0.21
    la_one = _la(0.34, 0.18, 0.20, 0.035)                # [0.18,0.215], contains cy
    la_two = _la(0.34, 0.24, 0.20, 0.025)                # [0.24,0.265], disjoint from la_one
    r = VisionService()._adopt_la_vertical_geometry(
        [ocr], [la_one, la_two], DOC_LH, {"e1": (0.19, 0.21)})[0]
    assert (r.y, r.height) == (0.15, 0.12)               # ambiguous -> unchanged


# ---- (c) coverage-preserving height: NEVER collapse below the ink ------------

def test_coverage_preserving_never_collapses_below_ink_hull():
    # LA is very tight (h=0.012) but the entity's measured ink (incl. descender)
    # runs [0.18,0.21]. The new box must cover the whole ink hull and never
    # collapse to LA's 0.012.
    ocr = _b(0.35, 0.16, 0.19, 0.06, id_="e1")           # [0.16,0.22], cy=0.19
    la = _la(0.34, 0.185, 0.20, 0.012)                   # [0.185,0.197], contains 0.19
    ink = {"e1": (0.18, 0.21)}
    r = VisionService()._adopt_la_vertical_geometry([ocr], [la], DOC_LH, ink)[0]
    # hull(la [0.185,0.197] ∪ ink [0.18,0.21]) = [0.18,0.21]
    assert r.y <= 0.18 + 1e-9 and (r.y + r.height) >= 0.21 - 1e-9   # ink fully covered
    assert r.height > 0.012 + 1e-9                                   # never LA's tiny height
    assert abs(r.y - 0.18) < 1e-9 and abs((r.y + r.height) - 0.21) < 1e-9


def test_la_extends_below_ink_union_takes_the_taller_hull():
    # If LA reaches a flourish below the measured ink, the union keeps LA's reach.
    ocr = _b(0.35, 0.16, 0.19, 0.06, id_="e1")
    la = _la(0.34, 0.185, 0.20, 0.05)                    # [0.185,0.235], contains cy 0.19
    ink = {"e1": (0.19, 0.21)}
    r = VisionService()._adopt_la_vertical_geometry([ocr], [la], DOC_LH, ink)[0]
    assert abs(r.y - 0.185) < 1e-9 and abs((r.y + r.height) - 0.235) < 1e-9


# ---- failure paths all keep the original over-covering box (0 leak) ----------

def test_no_matching_la_keeps_original():
    ocr = _b(0.35, 0.17, 0.19, 0.06, id_="e1")
    la_other_col = _la(0.70, 0.18, 0.20, 0.03)           # different column, no x-overlap
    r = VisionService()._adopt_la_vertical_geometry(
        [ocr], [la_other_col], DOC_LH, {"e1": (0.18, 0.21)})[0]
    assert (r.y, r.height) == (0.17, 0.06)               # unchanged


def test_missing_ink_hull_keeps_original():
    # Oversize box with a clean single matching LA row, but the caller supplied
    # no measured ink floor for it -> cannot safely tighten -> keep original.
    ocr = _b(0.35, 0.17, 0.19, 0.06, id_="e1")
    la = _la(0.34, 0.19, 0.20, 0.03)                     # contains cy 0.20
    r = VisionService()._adopt_la_vertical_geometry([ocr], [la], DOC_LH, {})[0]
    assert (r.y, r.height) == (0.17, 0.06)               # unchanged


def test_visual_and_textless_boxes_untouched():
    seal = _b(0.3, 0.1, 0.1, 0.1, id_="s1", source="visual_features",
              type_="official_seal", text="公章")
    la = _la(0.3, 0.12, 0.1, 0.03)
    r = VisionService()._adopt_la_vertical_geometry(
        [seal], [la], DOC_LH, {"s1": (0.11, 0.19)})[0]
    assert (r.y, r.height) == (0.1, 0.1)                 # visual box not corrected


def test_no_la_boxes_returns_input():
    ocr = _b(0.35, 0.17, 0.19, 0.06, id_="e1")
    out = VisionService()._adopt_la_vertical_geometry([ocr], [], DOC_LH, {"e1": (0.18, 0.21)})
    assert out[0] is ocr
