import base64
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.api import files as files_mod
from app.api import redaction as redaction_mod
from app.core.config import settings


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(redaction_mod.router, prefix=settings.API_PREFIX)
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_file_store():
    backup = dict(files_mod.file_store)
    files_mod.file_store.clear()
    yield
    files_mod.file_store.clear()
    files_mod.file_store.update(backup)


def test_preview_image_returns_base64_and_respects_selected_and_page(client, tmp_path):
    path = tmp_path / "sample.png"
    image = Image.new("RGB", (10, 10), "white")
    image.save(path)
    files_mod.file_store["img-1"] = {
        "id": "img-1",
        "original_filename": "sample.png",
        "file_path": str(path),
        "file_type": "image",
        "file_size": path.stat().st_size,
    }
    res = client.post(
        f"{settings.API_PREFIX}/redaction/img-1/preview-image?page=2",
        json={
            "bounding_boxes": [
                {"id": "b1", "x": 0.0, "y": 0.0, "width": 0.4, "height": 0.4, "page": 1, "type": "PERSON", "selected": True},
                {"id": "b2", "x": 0.5, "y": 0.5, "width": 0.4, "height": 0.4, "page": 2, "type": "PERSON", "selected": True},
                {"id": "b3", "x": 0.0, "y": 0.5, "width": 0.4, "height": 0.4, "page": 2, "type": "PERSON", "selected": False},
            ],
            "config": {
                "image_redaction_method": "fill",
                "image_fill_color": "#000000",
                "image_redaction_strength": 25,
            },
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["file_id"] == "img-1"
    assert body["page"] == 2
    rendered = Image.open(io.BytesIO(base64.b64decode(body["image_base64"]))).convert("RGB")
    assert rendered.getpixel((7, 7)) == (0, 0, 0)
    assert rendered.getpixel((1, 7)) == (255, 255, 255)
    assert rendered.getpixel((1, 1)) == (255, 255, 255)
