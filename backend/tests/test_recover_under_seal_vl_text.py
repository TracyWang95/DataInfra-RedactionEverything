"""章下 VL 文本 targeted 召回: 只救与某个章区域相交的 VL 文本块.

红章盖住"海南工程服务有限公司"这条印刷行 -> PP-Structure 把它打成碎片(NER 定不了型)
或读乱, VL parsing 仍读得出整行。只当 VL 块【与某个章区域相交】才召回 -> 把收益锁死在
章遮挡文字; 非章区(身份证/日期巨框)的 VL 块与任何章都不相交, 绝不召回, 老污染进不来。
且是"新增 charless 块", 不改 PP 字框, 不会重现巨框。纯矩形相交, 无阈值。
"""
from dataclasses import dataclass
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.ocr_paddle_extract import _recover_under_seal_vl_text


@dataclass
class _Seal:
    left: int
    top: int
    width: int
    height: int


def _blk(x1, y1, x2, y2, text="x"):
    return OCRTextBlock(text=text, polygon=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]])


def test_over_seal_recovered_even_with_structure_fragments():
    # 海南工程 VL 块与红章相交 -> 召回, 哪怕 PP-Structure 那片有碎片块
    vl = _blk(431, 357, 665, 381, "海南工程服务有限公司")
    seal = _Seal(448, 249, 165, 164)  # 红章 (448,249)-(613,413)
    fragments = [_blk(428, 360, 467, 383, "海南"), _blk(527, 352, 668, 380, "工程服务有限公司")]
    out = _recover_under_seal_vl_text([vl], fragments, [seal])
    assert [b.text for b in out] == ["海南工程服务有限公司"]


def test_not_over_any_seal_not_recovered():
    # VL 块不与任何章相交(身份证/普通行等非章区)-> 不召回, 老污染进不来
    vl = _blk(100, 100, 400, 130, "身份证号码4021198901031424")
    seal = _Seal(448, 249, 165, 164)
    out = _recover_under_seal_vl_text([vl], [], [seal])
    assert out == []


def test_no_seals_recovers_nothing():
    vl = _blk(431, 357, 665, 381)
    assert _recover_under_seal_vl_text([vl], [], []) == []
