"""Grid-tile 复检 (zero-recall tile retry) geometry and gating.

Pure window-geometry helpers plus the slug sets that gate which categories are
re-detected on native-resolution tiles. Split out of ``locate_grounding`` for
single-responsibility; behavior is verbatim. See ``locate_grounding`` for the
orchestration that consumes these.
"""
from __future__ import annotations

# Zero-recall tile retry: LA's input is downscaled to its max side, so small
# page artifacts (binding-seal slivers on the margins, watermark QR codes at
# the page foot) can vanish at full-page scale while detecting reliably on a
# native-resolution crop. When a requested category yields nothing on the
# full frame, re-run just that category on a validated tile set. Window
# geometry is start/center/end anchoring with half-size windows: any object
# smaller than half a window lies fully inside at least one tile, so nothing
# that size can be lost to a tile seam. Tile hits are pure gap-filling: any
# tile box intersecting a full-frame box is discarded (the full frame
# outranks the zoom - a zoomed handwritten signature must not come back as a
# phantom "seal" on top of the signature the full frame already found).
_TILE_RETRY_MARGIN_SLUGS = frozenset({"official_seal"})
_TILE_RETRY_BOTTOM_SLUGS = frozenset({"qr_code"})
# Body-grid retry: a red thumbprint or a handwritten signature is a small,
# faint, body-placed mark the full-frame pass loses to downscaling — proven on
# the 受案回执 photo, invisible full-frame yet recalled at conf 0.82 inside a
# lower-page crop. They are recovered by re-running on an overlapping grid that
# covers the WHOLE page (not just margins/foot), gated on the full-frame miss.
_TILE_RETRY_GRID_SLUGS = frozenset({"fingerprint", "signature"})
# LA reads degraded machine codes as either sibling; both mask identically.


def _axis_positions(total: int, window: int) -> list[int]:
    """start / center / end anchor offsets for a sliding window."""
    last = max(0, total - window)
    return sorted({0, last // 2, last})


def _slide_positions(total: int, window: int) -> list[int]:
    """Half-window-step offsets covering the whole axis.

    Start/center/end (``_axis_positions``) only guarantees an object is whole
    inside a tile if it sits AT one of those three anchors; a fragment seal can
    be anywhere along the binding edge. Stepping by half the window makes every
    point of the axis fall within a full window of some position, so any stamp
    up to half a tile long is whole inside at least one tile wherever it sits.
    """
    if total <= window:
        return [0]
    # Half-window step: the coverage guarantee. Any object up to half a tile is
    # whole inside at least one tile wherever it sits — a property, not a tuned
    # density.
    step = max(1, window // 2)
    pos = list(range(0, total - window + 1, step))
    if pos[-1] != total - window:
        pos.append(total - window)
    return pos


def _fragment_seal_tiles(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Square, native-resolution tiles along ALL FOUR page margins.

    A 骑缝章 (binding/fragment seal) sits on the bound edge of the page and only
    a partial arc shows; which edge it is depends on orientation (the right edge
    of a portrait page becomes the bottom edge once the page is a rotated
    landscape scan), so all four are covered.

    Two shape decisions, both from measured model behaviour, not tuned scores:

    * SQUARE, not the tall W//3 x H//2 strip ``_margin_tiles`` cut. LocateAnything's
      vision tower cannot localise inside a ~1:8 sliver and returns the whole
      strip as one box (measured: occupancy 1.0, useless for redaction); a square
      crop lets it PLACE the stamp (measured: occupancy 0.02-0.16, tight — and it
      works on a greyscale/B&W scan too, where the stamp is pure shape with no
      red ink to fall back on).
    * Consumed at NATIVE resolution (see ``_detect_on_tiles`` max_image_side). A
      small square upscaled to the model's 1280 side gains no salience (the stamp
      already fills the crop) and a 206->1280x1280 encode OOMs the shared card
      (measured: the vision encode raised CUDA-capacity 503s). Native keeps the
      encode small and the stamp sharp.

    Depth into the page is a third of the crossing dimension — enough of the
    stamp's radius past the cut edge for the arc to read as a stamp; the step is
    half the tile so coverage along the edge is a guarantee, not a lucky cut.
    """
    tiles: set[tuple[int, int, int, int]] = set()
    depth_lr = max(1, width // 3)
    for x0 in (0, width - depth_lr):
        for y0 in _slide_positions(height, depth_lr):
            tiles.add((x0, y0, x0 + depth_lr, min(height, y0 + depth_lr)))
    depth_tb = max(1, height // 3)
    for y0 in (0, height - depth_tb):
        for x0 in _slide_positions(width, depth_tb):
            tiles.add((x0, y0, min(width, x0 + depth_tb), y0 + depth_tb))
    return sorted(tiles)


def _ink_centered_tiles(
    width: int,
    height: int,
    components: list[tuple[float, float, float, float]],
) -> list[tuple[int, int, int, int]]:
    """Square tiles CENTRED on coloured-ink margin evidence.

    The blind grid guarantees a stamp is WHOLE in some tile, but not CENTRED —
    a partial arc sitting off-centre against a tile seam is detected only
    probabilistically, so a stamp landing in just one or two grid tiles came
    back intermittently. When there IS colour (a colour scan), the ink says
    exactly where the stamp is: put a tile's centre on it and the stamp fills
    the crop, which the model reads reliably. Tile side is the same margin depth
    as the grid; a component whose centre already sits inside a kept tile adds
    nothing, so a block of red text collapses to a few tiles rather than one per
    speck. Physical evidence places the tiles — there is no density to tune.
    Empty (a B&W scan) → nothing here, the blind grid stands.
    """
    side = max(1, min(width, height) // 3)
    half = side // 2
    kept: list[tuple[int, int, int, int]] = []
    for cx, cy, cw, ch in components:
        px = int((cx + cw / 2) * width)
        py = int((cy + ch / 2) * height)
        x0 = min(max(0, px - half), max(0, width - side))
        y0 = min(max(0, py - half), max(0, height - side))
        tile = (x0, y0, min(width, x0 + side), min(height, y0 + side))
        if any(tx0 <= px <= tx1 and ty0 <= py <= ty1 for tx0, ty0, tx1, ty1 in kept):
            continue  # this ink already sits inside a kept tile
        kept.append(tile)
    return kept


def _margin_tiles(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """L/R margin strips: binding seals sit on page edges by definition.
    Strip width W//3 - validated on real binding-seal pages: narrower strips
    starve the model of page context and edge slivers stop being recognised
    as stamps."""
    strip = max(1, width // 3)
    window = max(1, height // 2)
    tiles = []
    for x0 in (0, width - strip):
        for y0 in _axis_positions(height, window):
            tiles.append((x0, y0, x0 + strip, min(height, y0 + window)))
    return tiles


def _bottom_tiles(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Bottom H//4 row in three overlapped half-width windows: scanner
    watermark QR codes live at the page foot; QR codes elsewhere are
    body-scale and the full frame sees them."""
    row_top = height - max(1, height // 4)
    window = max(1, width // 2)
    return [
        (x0, row_top, min(width, x0 + window), height)
        for x0 in _axis_positions(width, window)
    ]


def _grid_tiles(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """A 2x2 grid of overlapping three-fifths windows covering the WHOLE frame.

    A faint, small, body-placed mark (thumbprint) is lost once the full page is
    downscaled but salient inside a three-fifths-scale window; the windows overlap
    by a FIFTH of the page (a mark up to a fifth is whole in some tile wherever it
    sits — see test_grid_tiles). Signatures no longer use this path — they go to
    the specialized conditional-detr detector, which does its OWN internal tiling.
    Fine 2/5 native tiling was tried for small signatures on the LA path, but with
    signatures on detr it only served fingerprint and over-fired it on the 海油
    red seals (6 phantom 指纹). Coarse restored."""
    win_w = max(1, width * 3 // 5)
    win_h = max(1, height * 3 // 5)
    return [
        (x0, y0, min(width, x0 + win_w), min(height, y0 + win_h))
        for y0 in (0, height - win_h)
        for x0 in (0, width - win_w)
    ]
