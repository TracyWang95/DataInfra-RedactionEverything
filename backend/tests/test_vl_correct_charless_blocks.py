"""VL 纠正 PP-OCRv6 读乱的 charless 硬行: 1:1 同区 + PP无字框 才采纳 VL 文本.

签字上方日期 2016年12月20号 被 v6 读成 "201010" 且 chars=0(v6自己没把握)。VL parsing 读对。
仅当【charless PP 块 与 唯一一个 VL 块 互为同区(1:1) 且 文本不同】才把 PP 文本换成 VL 的。
两道硬闸: (1) 带字框的块绝不动文本(否则文本↔字框发散 -> 身份证两列巨框回潮);
(2) VL 跨多行的合并块跳过(非 1:1)。只改文本不改几何。纯几何, 无阈值。
"""
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.ocr_paddle_extract import _vl_correct_charless_blocks


def _blk(x1, y1, x2, y2, text, chars=None):
    return OCRTextBlock(text=text, polygon=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                        chars=chars or [])


def _texts(blocks):
    return [b.text for b in blocks]


def test_charless_1to1_disagreement_adopts_vl():
    pp = _blk(464, 461, 603, 484, "201010")  # v6 garble, charless
    vl = _blk(463, 460, 604, 485, "2016年12月20号")
    out = _vl_correct_charless_blocks([pp], [vl])
    assert _texts(out) == ["2016年12月20号"]


def test_block_with_charboxes_never_touched():
    # 身份证行有字框 -> 即便 VL 文本不同也不动(否则文本↔字框发散成巨框)
    pp = _blk(100, 100, 400, 130, "4021198901031424",
              chars=[{"c": "4", "x1": 100, "y1": 100, "x2": 110, "y2": 130}])
    vl = _blk(100, 100, 400, 130, "身份证号码4021...X")
    out = _vl_correct_charless_blocks([pp], [vl])
    assert _texts(out) == ["4021198901031424"]  # 原样


def test_vl_spanning_two_pp_blocks_not_1to1_skipped():
    # VL 一块跨两个 PP 行 -> 非 1:1 -> 不纠正(避免跨行涂抹)
    pp1 = _blk(100, 100, 300, 130, "行一乱码")
    pp2 = _blk(100, 140, 300, 170, "行二乱码")
    vl_wide = _blk(100, 100, 300, 170, "行一行二")
    out = _vl_correct_charless_blocks([pp1, pp2], [vl_wide])
    assert _texts(out) == ["行一乱码", "行二乱码"]


def test_charless_agreement_unchanged():
    pp = _blk(100, 100, 300, 130, "农行上海戬浜支行")
    vl = _blk(100, 100, 300, 130, "农行上海戬浜支行")
    out = _vl_correct_charless_blocks([pp], [vl])
    assert _texts(out) == ["农行上海戬浜支行"]


def test_no_vl_blocks_unchanged():
    pp = _blk(100, 100, 300, 130, "201010")
    assert _texts(_vl_correct_charless_blocks([pp], [])) == ["201010"]
