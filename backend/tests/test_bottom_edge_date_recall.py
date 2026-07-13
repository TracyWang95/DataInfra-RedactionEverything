"""底边签署日期被误当扫描边缘伪影丢弃 (19合同.webp 底部两个 2025年12月23日 漏检).

`is_page_edge_ocr_artifact` 的底边条带规则 (贴底>0.975 + 宽>0.10 + 矮<0.035) 用来杀
扫描页脚噪声条,却误杀了落在文档最后一行的签署日期。判据:扫描边缘噪声不会被 OCR
解码成连贯多字符文本,真日期会 → 带实质解码文本的 region 豁免几何边缘过滤。

真值来自服务器复现 (原图 500x611): 底部日期 box=(51,585,106x14) / (328,585,104x13)。
"""
from app.services.vision.ocr_artifact_filter import is_page_edge_ocr_artifact

PAGE_W, PAGE_H = 500, 611


def test_bottom_line_signing_date_not_dropped():
    # 19合同.webp 底部左/右签署日期的真实几何 + 真实文本
    assert not is_page_edge_ocr_artifact(51, 585, 106, 14, PAGE_W, PAGE_H, "DATE", "2025年12月23日")
    assert not is_page_edge_ocr_artifact(328, 585, 104, 13, PAGE_W, PAGE_H, "DATE", "2025年12月23日")


def test_textless_bottom_strip_still_dropped():
    # 同样几何,但无实质文本 (扫描页脚噪声条) → 仍判为伪影
    assert is_page_edge_ocr_artifact(51, 585, 106, 14, PAGE_W, PAGE_H, "DATE", "")
    assert is_page_edge_ocr_artifact(51, 585, 106, 14, PAGE_W, PAGE_H, "DATE", None)
    assert is_page_edge_ocr_artifact(51, 585, 106, 14, PAGE_W, PAGE_H, "DATE", "—")


def test_wide_thin_bottom_scanline_still_dropped():
    # 近全宽的极薄底边扫描线 (无文本) → 伪影
    assert is_page_edge_ocr_artifact(20, 605, 460, 6, PAGE_W, PAGE_H, "DATE", None)


def test_middle_date_unaffected():
    # 中间"签订时间"日期离底边远,本就不受影响 (回归)
    assert not is_page_edge_ocr_artifact(170, 358, 142, 12, PAGE_W, PAGE_H, "DATE", "【2025】年【12】月【23】日")


def test_substantial_text_exempts_other_edges():
    # 带真文本的 region 落在任意边缘都算内容 (左边缘竖条规则不该杀真文本)
    assert not is_page_edge_ocr_artifact(2, 300, 60, 40, PAGE_W, PAGE_H, "PERSON", "张伟华")
    # 无文本的左边缘竖条仍被杀
    assert is_page_edge_ocr_artifact(2, 300, 60, 40, PAGE_W, PAGE_H, "PERSON", None)
