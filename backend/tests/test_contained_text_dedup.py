"""换行标题产生的重叠碎片框去重 (19合同 项目名称 "货合同"碎片).

OCR 把换行标题 "海油工程...供货合同" 同时返回整条 + 行碎片, 匹配后行2 上出现一个
"货合同"小框, ~97% 落在同类型的大框内。IoU 去重因体量差过大(IoU≈0.20)漏掉它,
按"较小框被包含率"再补一刀: ≥0.85 被同类型更大框包含 = 冗余, 丢小框留大框(遮盖
覆盖不缩)。同类型才合并——跨类型是模型断言的不同实体 [[test_cross_type_no_merge]]。

真几何来自服务器复现 (页面 500x611):
  A 整条标题 行1  (11,8,456x28)
  B 整条标题 行2  (10,44,264x31)
  C "货合同"碎片   (210,47,60x29)  <- 落在 B 内, 应丢
"""
from app.models.schemas import BoundingBox
from app.services.vision_service import VisionService

W, H = 500.0, 611.0


def _box(btype, x, y, w, h, id_, text=""):
    return BoundingBox(
        id=id_, x=x / W, y=y / H, width=w / W, height=h / H, type=btype, text=text,
        page=1, confidence=0.9, source="ocr_has",
    )


def test_wrapped_title_fragment_dropped():
    a = _box("PROJECT_NAME", 11, 8, 456, 28, "A", "海油工程-深技服渤中34-1油田低压压缩机橇供货合同")
    b = _box("PROJECT_NAME", 10, 44, 264, 31, "B", "海油工程-深技服渤中34-1油田低压压缩机橇供货合同")
    c = _box("PROJECT_NAME", 210, 47, 60, 29, "C", "货合同")
    kept = {r.id for r in VisionService()._drop_contained_same_type_text([a, b, c])}
    assert "C" not in kept, "货合同 碎片被 B 包含,应丢"
    assert kept == {"A", "B"}, "整条标题两行框保留"


def test_cross_type_contained_survives():
    # 小 DATE 落在大 signature 内 —— 不同类型,两者都留
    sig = _box("signature", 100, 100, 200, 80, "sig")
    date = _box("DATE", 120, 120, 60, 20, "date", "2025年")
    kept = {r.id for r in VisionService()._drop_contained_same_type_text([sig, date])}
    assert kept == {"sig", "date"}


def test_non_contained_same_type_all_kept():
    # 行1 与行2 无 y 重叠,互不包含 —— 都留
    a = _box("PROJECT_NAME", 11, 8, 456, 28, "A")
    b = _box("PROJECT_NAME", 10, 44, 264, 31, "B")
    kept = {r.id for r in VisionService()._drop_contained_same_type_text([a, b])}
    assert kept == {"A", "B"}


def test_coverage_never_shrinks_larger_kept():
    # 被包含的是较小框,保留的必是更大的那个(遮盖不缩)
    big = _box("INSTITUTION_NAME", 50, 200, 300, 40, "big")
    small = _box("INSTITUTION_NAME", 100, 205, 80, 30, "small")
    kept = VisionService()._drop_contained_same_type_text([big, small])
    assert [r.id for r in kept] == ["big"]
