# Copyright 2026 DataInfra-RedactionEverything Contributors

"""A document photographed on a warm-toned desk must not paint the whole page
as one seal / fingerprint.

Root cause of the CT-report regression: raw_colored_component_bboxes returned
the desk — a colored blob that surrounds the paper and therefore touches all
four image borders — as one page-spanning component. Any consumer that unions
or snaps to the components intersecting a box then inherited that full-frame
extent and exploded a tight stamp box to the whole page (hiding the stamp).

The scene background is the one component whose bbox spans the entire frame.
An ink impression on paper is interior — it never reaches all four borders.
That is topology, not a tuned threshold.
"""

import io

import numpy as np
from PIL import Image

from app.services.vision.seal_color_cascade import raw_colored_component_bboxes


def _encode(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return buf.getvalue()


def test_frame_spanning_scene_component_is_dropped():
    # A red desk (colored, touches every border) framing a white page with one
    # small red stamp interior to it.
    h, w = 200, 160
    arr = np.zeros((h, w, 3), np.uint8)
    arr[:, :] = (180, 40, 40)          # warm desk everywhere (high chroma)
    arr[20:180, 20:140] = (250, 250, 250)  # white paper inset
    arr[90:110, 60:90] = (210, 30, 30)     # the red stamp, interior

    comps = raw_colored_component_bboxes(_encode(arr))

    # The desk (full-frame) is gone; the stamp (interior) survives.
    assert comps, "the interior stamp must still be reported"
    assert all(
        not (x <= 0.0 and y <= 0.0 and x + cw >= 1.0 and y + ch >= 1.0)
        for x, y, cw, ch in comps
    ), "the frame-spanning scene component must be dropped"
    # what's left is the interior stamp, not a page-wide box
    assert max(cw * ch for _, _, cw, ch in comps) < 0.5


def test_interior_ink_touching_no_border_survives():
    h, w = 200, 160
    arr = np.full((h, w, 3), 250, np.uint8)   # all white paper, no desk
    arr[90:110, 60:90] = (210, 30, 30)        # one red stamp
    comps = raw_colored_component_bboxes(_encode(arr))
    assert len(comps) == 1
    x, y, cw, ch = comps[0]
    assert 0.0 < x and 0.0 < y and x + cw < 1.0 and y + ch < 1.0
