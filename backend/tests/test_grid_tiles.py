"""TDD for the body-grid retry tiling that recovers full-frame-missed faint
marks (thumbprint, handwritten signature): the grid must cover the whole page
and keep a small mark whole inside at least one tile (a mark split across every
tile it touches would never be grounded)."""
from app.services.vision.locate_grounding import _grid_tiles


def _covers_point(tiles, px, py):
    return any(x0 <= px <= x1 and y0 <= py <= y1 for x0, y0, x1, y1 in tiles)


def _mark_whole(tiles, m):
    mx0, my0, mx1, my1 = m
    return any(x0 <= mx0 and y0 <= my0 and mx1 <= x1 and my1 <= y1 for x0, y0, x1, y1 in tiles)


def test_grid_is_four_tiles_covering_the_frame():
    W, H = 1080, 1920
    tiles = _grid_tiles(W, H)
    assert len(tiles) == 4
    for px, py in [(0, 0), (W - 1, H - 1), (W // 2, H // 2), (0, H - 1), (W - 1, 0)]:
        assert _covers_point(tiles, px, py), f"({px},{py}) uncovered"


def test_mark_up_to_overlap_is_whole_regardless_of_position():
    # THE seam guarantee (answers "what if the object lands on the cut"): with
    # three-fifths windows overlapping by a fifth, ANY mark up to a fifth of the
    # page is whole in some tile no matter where it sits — swept densely across
    # the frame including the seams. Content-independent, not a lucky cut. Real
    # thumbprints/signatures measure 9-11% of the page, comfortably under this.
    W, H = 1080, 1920
    tiles = _grid_tiles(W, H)
    mw, mh = int(0.19 * W), int(0.19 * H)  # just under the 1/5 step guarantee
    for i in range(1, 40):
        for j in range(1, 40):
            cx, cy = i / 40, j / 40
            mx0 = max(0, min(W - mw, int(cx * W - mw / 2)))
            my0 = max(0, min(H - mh, int(cy * H - mh / 2)))
            assert _mark_whole(tiles, (mx0, my0, mx0 + mw, my0 + mh)), \
                f"19%% mark at ({cx:.3f},{cy:.3f}) split across every tile"


def test_tiles_downscale_less_than_full_frame():
    # each tile is 2/5 of the page — read at native resolution it keeps a faint
    # small mark sharp where 3/5 upscaled blurred it away. Guard the tile is
    # meaningfully smaller than the page.
    W, H = 1080, 1920
    for x0, y0, x1, y1 in _grid_tiles(W, H):
        assert (x1 - x0) <= 0.62 * W and (y1 - y0) <= 0.62 * H
