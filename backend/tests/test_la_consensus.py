"""LA 多采样共识: 过滤只出现1-2次的幻觉框, 保留每次都在的稳定框。"""
from app.models.entity_schemas import BoundingBox
from app.services.vision.la_consensus import consensus_boxes


def _b(x, y, w=0.1, h=0.1, type_="official_seal", conf=0.9):
    return BoundingBox(id=f"b{x}{y}", x=x, y=y, width=w, height=h, type=type_,
                       text=None, page=1, confidence=conf, source="visual_features")


def test_stable_box_in_all_runs_kept():
    # 同一个公章框在3次采样都出现(几何微抖) -> 保留
    runs = [[_b(0.30, 0.40)], [_b(0.305, 0.402)], [_b(0.298, 0.399)]]
    out = consensus_boxes(runs, min_votes=2)
    assert len(out) == 1 and out[0].type == "official_seal"


def test_hallucinated_box_in_one_run_filtered():
    # 稳定公章(3次都在) + 幻觉签字(只1次) -> 幻觉被过滤
    runs = [
        [_b(0.30, 0.40), _b(0.60, 0.70, type_="signature")],  # run0 有幻觉签字
        [_b(0.30, 0.40)],
        [_b(0.30, 0.40)],
    ]
    out = consensus_boxes(runs, min_votes=2)
    assert len(out) == 1 and out[0].type == "official_seal"  # 签字被过滤


def test_signature_in_majority_kept():
    # 签字3次里出现2次 -> 达到多数, 保留
    runs = [
        [_b(0.6, 0.7, type_="signature")],
        [_b(0.61, 0.702, type_="signature")],
        [],
    ]
    out = consensus_boxes(runs, min_votes=2)
    assert len(out) == 1 and out[0].type == "signature"


def test_different_types_not_merged():
    # 相同位置但不同type不聚为一簇
    runs = [
        [_b(0.3, 0.4, type_="official_seal"), _b(0.3, 0.4, type_="fingerprint")],
        [_b(0.3, 0.4, type_="official_seal"), _b(0.3, 0.4, type_="fingerprint")],
    ]
    out = consensus_boxes(runs, min_votes=2)
    assert {b.type for b in out} == {"official_seal", "fingerprint"}


def test_representative_is_median_geometry():
    # 小抖动(0.01/步, 单链相邻两两IoU≈0.68>0.5)聚为一簇, 代表框取中位数
    runs = [[_b(0.30, 0.40)], [_b(0.31, 0.41)], [_b(0.32, 0.42)]]
    out = consensus_boxes(runs, min_votes=2)
    assert len(out) == 1
    assert abs(out[0].x - 0.31) < 1e-9 and abs(out[0].y - 0.41) < 1e-9  # 中位数


def test_samples_one_returns_first_unchanged():
    runs = [[_b(0.3, 0.4), _b(0.6, 0.7, type_="signature")]]
    out = consensus_boxes(runs, min_votes=2)
    assert len(out) == 2  # 单次采样原样返回, 不过滤


def test_min_votes_one_is_union():
    # 并集模式: 保留任意 run 出现的框(治淡签字/手写单次采样time中time漏)
    runs = [[_b(0.3, 0.4)], [_b(0.9, 0.9, type_="signature")]]
    out = consensus_boxes(runs, min_votes=1)
    assert {b.type for b in out} == {"official_seal", "signature"}  # 两个都保留


def test_union_hull_covers_max_extent():
    # 同一手写笔画在 2/3 采样出现、位置/大小微异(IoU≈0.68>0.5 聚一簇) -> 并集外壳覆盖二者最大范围
    runs = [
        [_b(0.30, 0.40, w=0.10, h=0.10, type_="signature")],
        [],  # 这次采样漏了这一笔
        [_b(0.31, 0.41, w=0.10, h=0.10, type_="signature")],
    ]
    out = consensus_boxes(runs, min_votes=1)
    assert len(out) == 1  # 单次会漏, 并集保住
    b = out[0]
    assert abs(b.x - 0.30) < 1e-9 and abs(b.y - 0.40) < 1e-9       # 外壳左上=最小
    assert abs((b.x + b.width) - 0.41) < 1e-9                      # 外壳右=max(0.40,0.41)
    assert abs((b.y + b.height) - 0.51) < 1e-9                     # 外壳下=max(0.50,0.51)


def test_empty_runs():
    assert consensus_boxes([], min_votes=2) == []
    assert consensus_boxes([[], []], min_votes=2) == []
