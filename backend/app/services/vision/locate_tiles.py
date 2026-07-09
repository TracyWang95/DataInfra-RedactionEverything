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
_MACHINE_CODE_SIBLINGS = frozenset({"qr_code", "barcode"})


def _axis_positions(total: int, window: int) -> list[int]:
    """start / center / end anchor offsets for a sliding window."""
    last = max(0, total - window)
    return sorted({0, last // 2, last})


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

    A faint, small, body-placed mark (thumbprint, handwritten signature) is lost
    once the full page is downscaled to the model input, but salient inside a
    three-fifths-scale window (empirically: the 受案回执 photo's prints AND the
    stamped-over signature, invisible full-frame, all come back at conf 0.82 in
    these tiles — larger two-thirds tiles already lose the faintest, the
    signature, to less salience, so three-fifths is the floor that still recalls).

    The windows overlap by a FIFTH of the page: a content-independent GUARANTEE
    (not a lucky cut) that any mark up to a fifth of the page is whole inside at
    least one tile wherever it sits, even across a nominal seam (see
    test_grid_tiles). That covers the real marks with margin — measured
    thumbprints/signatures run 9-11% of the page — and it is enough because the
    retry only runs for objects the full frame MISSED, and the full frame only
    misses small/faint marks (it already sees anything large enough to straddle
    a fifth-of-page overlap)."""
    win_w = max(1, width * 3 // 5)
    win_h = max(1, height * 3 // 5)
    return [
        (x0, y0, min(width, x0 + win_w), min(height, y0 + win_h))
        for y0 in (0, height - win_h)
        for x0 in (0, width - win_w)
    ]
