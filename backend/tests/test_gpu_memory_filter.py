"""VISIBLE_GPU_INDICES 过滤: '本地服务'面板只显示本项目使用的卡。"""
from app.core.gpu_memory import filter_visible_gpu_cards


def _cards(*idxs):
    return [{"index": i, "used_mb": 1000 + i, "total_mb": 32607} for i in idxs]


def test_filters_to_project_cards():
    # 8卡共享机, 本项目只用 6,7 -> 面板只显示这两张
    out = filter_visible_gpu_cards(_cards(0, 1, 2, 3, 4, 5, 6, 7), "6,7")
    assert [c["index"] for c in out] == [6, 7]


def test_empty_spec_shows_all():
    # 空 spec = 向后兼容, 全部显示
    out = filter_visible_gpu_cards(_cards(0, 1), "")
    assert [c["index"] for c in out] == [0, 1]


def test_space_and_comma_separated():
    out = filter_visible_gpu_cards(_cards(0, 1, 2, 3), "1 3")
    assert [c["index"] for c in out] == [1, 3]
    out2 = filter_visible_gpu_cards(_cards(0, 1, 2, 3), " 0, 2 ")
    assert [c["index"] for c in out2] == [0, 2]


def test_no_match_falls_back_to_all():
    # 配错(本机没有这些卡) -> 回退全部, 不让面板空白
    out = filter_visible_gpu_cards(_cards(0, 1), "6,7")
    assert [c["index"] for c in out] == [0, 1]


def test_garbage_spec_shows_all():
    out = filter_visible_gpu_cards(_cards(0, 1), "abc")
    assert [c["index"] for c in out] == [0, 1]


def test_empty_cards_stays_empty():
    assert filter_visible_gpu_cards([], "6,7") == []
