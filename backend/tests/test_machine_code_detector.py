import io

import cv2
import numpy as np
from PIL import Image

from app.models.schemas import BoundingBox
from app.services.vision.machine_code_detector import (
    QR_CODE_SLUG,
    detect_machine_code_regions,
)
from app.services.vision_service import VisionService

_PAGE_SIZE = (1200, 1300)  # (width, height) like a scanned document page
_QR_SIDE_PX = 60  # same on-page size as the missed corner QR in the customs scan
_QR_POSITION = (1100, 40)  # top-right corner placement
_QR_PAYLOAD = "CUSTOMS-2252024100123456"


def _page_with_small_qr() -> Image.Image:
    matrix = cv2.QRCodeEncoder_create().encode(_QR_PAYLOAD)
    qr = cv2.resize(matrix, (_QR_SIDE_PX, _QR_SIDE_PX), interpolation=cv2.INTER_NEAREST)
    width, height = _PAGE_SIZE
    page = np.full((height, width), 255, dtype=np.uint8)
    x, y = _QR_POSITION
    page[y : y + _QR_SIDE_PX, x : x + _QR_SIDE_PX] = qr
    return Image.fromarray(page).convert("RGB")


def _blank_page_with_text_like_marks() -> Image.Image:
    width, height = _PAGE_SIZE
    page = np.full((height, width), 255, dtype=np.uint8)
    # Dark text-line and table-rule rectangles: plausible document ink that a
    # decoder must never report as a machine code.
    for top in range(100, 1200, 90):
        page[top : top + 18, 80:1100] = 20
    page[95:1190, 80:84] = 20
    return Image.fromarray(page).convert("RGB")


def _image_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_decoder_finds_small_corner_qr_with_exact_box() -> None:
    regions = detect_machine_code_regions(_page_with_small_qr())

    assert len(regions) == 1
    region = regions[0]
    assert region.code_type == QR_CODE_SLUG
    assert region.text == _QR_PAYLOAD
    width, height = _PAGE_SIZE
    x, y = _QR_POSITION
    # Decoded quad must sit on the pasted QR (allow a few px of quad rounding).
    assert abs(region.x * width - x) <= 6
    assert abs(region.y * height - y) <= 6
    assert abs(region.width * width - _QR_SIDE_PX) <= 12
    assert abs(region.height * height - _QR_SIDE_PX) <= 12


def test_decoder_reports_nothing_on_page_without_codes() -> None:
    assert detect_machine_code_regions(_blank_page_with_text_like_marks()) == []


def test_supplement_machine_codes_adds_decoded_qr_box() -> None:
    service = VisionService()
    image_data = _image_bytes(_page_with_small_qr())

    boxes = service._supplement_machine_codes(image_data, 1, [], [QR_CODE_SLUG, "barcode"])

    assert len(boxes) == 1
    box = boxes[0]
    assert box.type == QR_CODE_SLUG
    assert box.source == "visual_features"
    assert box.source_detail == f"qr_decoder:{QR_CODE_SLUG}"
    assert box.page == 1


def test_supplement_machine_codes_skips_box_la_already_found() -> None:
    service = VisionService()
    image_data = _image_bytes(_page_with_small_qr())
    width, height = _PAGE_SIZE
    x, y = _QR_POSITION
    existing = BoundingBox(
        id="locate_qr",
        x=x / width,
        y=y / height,
        width=_QR_SIDE_PX / width,
        height=_QR_SIDE_PX / height,
        type=QR_CODE_SLUG,
        page=1,
        source="visual_features",
    )

    boxes = service._supplement_machine_codes(image_data, 1, [existing], [QR_CODE_SLUG])

    assert boxes == []


def test_supplement_machine_codes_respects_requested_categories() -> None:
    service = VisionService()
    image_data = _image_bytes(_page_with_small_qr())

    boxes = service._supplement_machine_codes(image_data, 1, [], ["barcode"])

    assert boxes == []
