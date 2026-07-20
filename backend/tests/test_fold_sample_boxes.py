"""n采样框折叠 (病例5实证: 一处手写签名被叠了3个框).

LOCATE_ANYTHING_VLLM_SAMPLES>1 时同一笔迹被模型画 n 次、每次略有出入,全部发出去
就是一处签名叠 2-3 个框。fold_sample_boxes 把"相交"的同 label 框(单链传递)折成
一个并集外壳=任一采样见过的最大范围(over-mask 方向,绝不比模型画的更紧);不相交
的保持独立,所以两处不同笔迹仍是两个框。布尔相交判定,无阈值无打分。
"""
from scripts.locate_anything_eval import fold_sample_boxes


def _b(x, y, w, h, label="signature"):
    return {"label": label, "x": x, "y": y, "width": w, "height": h}


def test_samples_of_one_mark_fold_to_hull():
    # 同一笔迹的3次采样(互相重叠) -> 1个外壳, 覆盖三者最大范围
    out = fold_sample_boxes([_b(10, 10, 40, 20), _b(12, 11, 42, 21), _b(9, 12, 38, 19)])
    assert len(out) == 1
    b = out[0]
    assert (b["x"], b["y"]) == (9, 10)                      # 左上取最小
    assert b["x"] + b["width"] == 54                        # 右取最大(12+42)
    assert b["y"] + b["height"] == 32                       # 下取最大(11+21)


def test_two_separate_marks_stay_two():
    # 两处不相交的笔迹 -> 不合并
    out = fold_sample_boxes([_b(10, 10, 20, 10), _b(100, 10, 20, 10)])
    assert len(out) == 2


def test_different_labels_never_merge():
    # 同位置但不同类目 -> 各自保留(签字与指纹叠放是真实情形)
    out = fold_sample_boxes([_b(10, 10, 20, 10), _b(10, 10, 20, 10, label="fingerprint")])
    assert {o["label"] for o in out} == {"signature", "fingerprint"}


def test_chain_folds_transitively():
    # A∩B, B∩C, 但 A 不∩ C -> 单链传递, 三者折成一个外壳
    out = fold_sample_boxes([_b(0, 0, 30, 10), _b(20, 0, 30, 10), _b(40, 0, 30, 10)])
    assert len(out) == 1
    assert out[0]["x"] == 0 and out[0]["x"] + out[0]["width"] == 70


def test_single_box_unchanged():
    one = [_b(5, 5, 10, 10)]
    assert fold_sample_boxes(one) == one


def test_touching_edges_do_not_merge():
    # 边缘相接但零重叠面积 = 不是同一物体的重复采样, 保持独立
    out = fold_sample_boxes([_b(0, 0, 10, 10), _b(10, 0, 10, 10)])
    assert len(out) == 2
