"""Colored-ink seal proposal for the color->VLM cascade.

The grounding VLM's seal recall degrades on faint, edge-straddling, and
photocopy-fragmented stamps — page_04's binding seal is invisible to it at
every zoom. But a stamp is COLORED INK on paper: red, blue, or purple ink is
strongly separable from paper and black text in chroma space
(max(R,G,B) - min(R,G,B)), and tightly localized on the stamp regardless of
how faint or broken it looks. (Black-on-white photocopy seals have no chroma
and are out of this channel's reach — that tier needs a trained detector.)

This module is the RECALL half of a two-stage cascade: it proposes
colored-ink regions (clustering scattered fragments of a photocopied stamp
back into one region); the caller confirms each proposal with the VLM on a
tight crop (the PRECISION half, which rejects colored text / underlines /
logos). Because the VLM is the sole judge of "is this a seal", the proposal
stage is deliberately loose: the constants below are physical floors (what
counts as colored ink, how far apart fragments of one stamp sit, how small is
a speck), not tuned decision thresholds.
"""
from __future__ import annotations

import io

import numpy as np
import scipy.ndimage as ndi
from PIL import Image, ImageOps

# A pixel is colored ink when its channel spread (max-min) is meaningfully
# above zero — a physical property of red/blue/purple stamp ink over neutral
# paper and black text (both near-zero chroma), not a per-image tuned value.
# Ink sits far above paper/text; the red-pixel bbox is unchanged whether the
# floor is 45 or 80 (a wide stable gap). Proposal-only; the VLM confirms.
_CHROMA_FLOOR = 45
# Fragments of one photocopied stamp sit within a stamp-radius of each other;
# dilating by this fraction of the page's long side bridges them into one
# region without merging distinct stamps (which sit farther apart).
_BRIDGE_FRAC = 0.03
# Drop specks below this fraction of page area (single-pixel chroma noise).
_AREA_FLOOR_FRAC = 5e-5


def propose_colored_seal_regions(image_data: bytes) -> list[tuple[float, float, float, float]]:
    """Normalized (x, y, w, h) bboxes of clustered colored-ink regions.

    Recall-oriented proposals for the VLM to confirm; may over-propose
    (colored text, decorative rules) since the VLM gate rejects non-seals.
    """
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_data))).convert("RGB")
    width, height = image.size
    arr = np.asarray(image).astype(np.int16)
    hi = arr.max(axis=2)
    lo = arr.min(axis=2)
    mask = (hi - lo) > _CHROMA_FLOOR
    if not mask.any():
        return []
    radius = max(1, int(_BRIDGE_FRAC * max(width, height)))
    labels, count = ndi.label(ndi.binary_dilation(mask, iterations=radius))
    area_floor = width * height * _AREA_FLOOR_FRAC
    regions: list[tuple[float, float, float, float]] = []
    for index in range(1, count + 1):
        ys, xs = np.where((labels == index) & mask)
        if len(xs) < area_floor:
            continue
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        regions.append((x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height))
    return regions
