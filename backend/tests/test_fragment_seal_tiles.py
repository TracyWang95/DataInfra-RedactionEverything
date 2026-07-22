# Copyright 2026 DataInfra-RedactionEverything Contributors

"""Fragment (骑缝) seal tiles: square, all-four-margins, coverage-guaranteed.

A binding seal is a partial arc on the bound page edge — which edge depends on
orientation — so the tiles cover all four margins. They are square (the model
cannot localise inside a tall sliver) and stepped by half a tile so any stamp up
to half a tile is whole inside at least one tile wherever it sits on the edge.
"""

from app.services.vision.locate_tiles import _fragment_seal_tiles, _slide_positions


def _covers(tiles, box, frac=0.5):
    """Some tile contains `box` whole, where box is (x0,y0,x1,y1)."""
    bx0, by0, bx1, by1 = box
    return any(tx0 <= bx0 and ty0 <= by0 and bx1 <= tx1 and by1 <= ty1
               for tx0, ty0, tx1, ty1 in tiles)


def test_tiles_are_square():
    for x0, y0, x1, y1 in _fragment_seal_tiles(1240, 1755):
        # square within one pixel (integer division of the crossing dim)
        assert abs((x1 - x0) - (y1 - y0)) <= 1


def test_all_four_margins_present():
    tiles = _fragment_seal_tiles(1240, 1755)
    w, h = 1240, 1755
    assert any(x0 == 0 for x0, _, _, _ in tiles), "left margin"
    assert any(x1 == w for _, _, x1, _ in tiles), "right margin"
    assert any(y0 == 0 for _, y0, _, _ in tiles), "top margin"
    assert any(y1 == h for _, _, _, y1 in tiles), "bottom margin"


def test_portrait_binding_seal_on_right_edge_is_whole_in_a_tile():
    # a stamp arc ~0.15 of the page tall, on the right edge, anywhere down it
    w, h = 1240, 1755
    tiles = _fragment_seal_tiles(w, h)
    seal_h = int(h * 0.12)
    for cy in range(0, h - seal_h, 40):
        box = (int(w * 0.90), cy, w, cy + seal_h)
        assert _covers(tiles, box), f"right-edge seal at y={cy} not whole in any tile"


def test_landscape_binding_seal_on_bottom_edge_is_whole_in_a_tile():
    # page_06 is a rotated landscape scan: binding seal on the BOTTOM edge
    w, h = 1755, 1240
    tiles = _fragment_seal_tiles(w, h)
    seal_w = int(w * 0.12)
    for cx in range(0, w - seal_w, 40):
        box = (cx, int(h * 0.90), cx + seal_w, h)
        assert _covers(tiles, box), f"bottom-edge seal at x={cx} not whole in any tile"


def test_slide_positions_leave_no_gap():
    # every point of the axis is within a full window of some position
    total, window = 1755, 585
    pos = _slide_positions(total, window)
    for p in range(total):
        assert any(s <= p < s + window for s in pos), f"point {p} uncovered"
