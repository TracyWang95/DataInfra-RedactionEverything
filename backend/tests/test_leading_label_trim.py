"""字段标签裁剪: NER 若把"甲方：/开户行："等字段标签也算进值, 用冒号+em间隙几何裁掉前导标签,
让框紧贴 PII 值。纯几何、无词表、只把起点右推、leak-safe。"""
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.ocr_cjk_geometry import _leading_label_trimmed_start


def _ch(c, x1, x2):
    return {"c": c, "x1": x1, "y1": 225, "x2": x2, "y2": 241}


def _blk(text, chars):
    return OCRTextBlock(text=text, polygon=[[0, 225], [500, 225], [500, 241], [0, 241]], chars=chars)


def test_full_width_colon_label_trimmed():
    # 甲方：中海油 — 冒号右缘154, 中左缘176 => gutter 22 >= em(~12) => 裁到"中"
    chars = [_ch("甲", 122, 134), _ch("方", 134, 146), _ch("：", 151, 154),
             _ch("中", 176, 188), _ch("海", 188, 200), _ch("油", 200, 212)]
    block = _blk("甲方：中海油", chars)
    assert _leading_label_trimmed_start(block, "甲方：中海油", 0, 6) == 3


def test_half_width_colon_label_trimmed():
    chars = [_ch("户", 122, 134), _ch("名", 134, 146), _ch(":", 151, 154),
             _ch("农", 176, 188), _ch("行", 188, 200)]
    block = _blk("户名:农行", chars)
    assert _leading_label_trimmed_start(block, "户名:农行", 0, 5) == 3


def test_bare_value_unchanged():
    chars = [_ch("中", 176, 188), _ch("海", 188, 200), _ch("油", 200, 212)]
    block = _blk("中海油", chars)
    assert _leading_label_trimmed_start(block, "中海油", 0, 3) == 0  # 无冒号 => 原样


def test_colon_without_gutter_not_trimmed():
    # 甲：乙 相邻无间隙(冒号右缘=下一字左缘) => 内容冒号, 不裁
    chars = [_ch("甲", 100, 112), _ch("：", 112, 124), _ch("乙", 124, 136)]
    block = _blk("甲：乙", chars)
    assert _leading_label_trimmed_start(block, "甲：乙", 0, 3) == 0


def test_no_char_boxes_unchanged():
    block = OCRTextBlock(text="甲方：中海油", polygon=[[0, 225], [500, 225], [500, 241], [0, 241]], chars=[])
    assert _leading_label_trimmed_start(block, "甲方：中海油", 0, 6) == 0
