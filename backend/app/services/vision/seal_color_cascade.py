"""Colored-ink components of a page — the physical signal behind seal recovery.

A stamp is COLORED INK on paper: red, blue, or purple ink is strongly separable
from paper and black text in chroma space (max(R,G,B) - min(R,G,B)) and tightly
localized regardless of how faint or broken it looks. The fragment-seal pass
uses these components to place its confirm tiles and to grow a confirmed box
over the stamp's own ink. (Black-on-white photocopy seals have no chroma and are
out of this channel's reach — the fragment tiles read those by shape instead.)
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
# floor is 45 or 80 (a wide stable gap).
_CHROMA_FLOOR = 45
# Drop specks below this fraction of page area (single-pixel chroma noise).
_AREA_FLOOR_FRAC = 5e-5


def raw_colored_component_bboxes(image_data: bytes) -> list[tuple[float, float, float, float]]:
    """Normalized bboxes of UNDILATED colored-ink components (>= speck floor).

    Fragment bridging can pull non-seal ink into a stamp's cluster — on the
    Yueyang photo three red underlines bridged into the seal's cluster, and
    inheriting the whole cluster extent painted a page-wide box. The raw
    (undilated) components let the caller grow a confirmed seal box over the
    stamp's OWN ink piece by piece: components touching the confirmed box are
    its ink; detached ones get judged individually.

    One component is never ink: a document photographed on a colored surface (a
    wooden desk) produces a blob that SURROUNDS the paper and so reaches all
    four image borders. Its bbox spans the whole frame, intersects every box on
    the page, and turns any seal/fingerprint snap into a page-wide box. An ink
    impression ON the paper is interior — it cannot touch all four borders. That
    is topology, not a threshold, so the frame-spanning scene is dropped here.
    """
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_data))).convert("RGB")
    width, height = image.size
    arr = np.asarray(image).astype(np.int16)
    mask = (arr.max(axis=2) - arr.min(axis=2)) > _CHROMA_FLOOR
    if not mask.any():
        return []
    labels, count = ndi.label(mask)
    area_floor = width * height * _AREA_FLOOR_FRAC
    out: list[tuple[float, float, float, float]] = []
    for index in range(1, count + 1):
        ys, xs = np.where(labels == index)
        if len(xs) < area_floor:
            continue
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        if x0 == 0 and y0 == 0 and x1 == width - 1 and y1 == height - 1:
            continue  # the photographed background, not ink on the document
        out.append((x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height))
    return out
