"""has_image_client：对 8081 /detect 的请求契约（mock HTTP）。"""
import asyncio
import base64
from unittest.mock import MagicMock

import httpx
import pytest

from app.core import has_image_client as client_mod


def test_detect_privacy_regions_posts_json_and_returns_boxes(monkeypatch):
    monkeypatch.setattr(client_mod.settings, "HAS_IMAGE_BASE_URL", "http://test:8081")
    monkeypatch.setattr(client_mod.settings, "HAS_IMAGE_CONF", 0.25)
    monkeypatch.setattr(client_mod.settings, "HAS_IMAGE_TIMEOUT", 30.0)

    captured = {}

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(
                return_value={
                    "boxes": [
                        {
                            "x": 0.1,
                            "y": 0.2,
                            "width": 0.3,
                            "height": 0.4,
                            "category": "face",
                            "confidence": 0.9,
                        }
                    ]
                }
            )
            return resp

    monkeypatch.setattr(client_mod.httpx, "AsyncClient", FakeClient)

    img = b"\xff\xd8\xff"
    out = asyncio.run(client_mod.detect_privacy_regions(img, conf=0.5, category_slugs=["face", "qr_code"]))

    assert captured["url"] == "http://test:8081/detect"
    assert captured["json"]["conf"] == 0.5
    assert captured["json"]["categories"] == ["face", "qr_code"]
    raw_b64 = base64.b64encode(img).decode("utf-8")
    assert captured["json"]["image_base64"] == raw_b64
    assert len(out) == 1
    assert out[0]["category"] == "face"


def test_detect_privacy_regions_omits_categories_when_none(monkeypatch):
    monkeypatch.setattr(client_mod.settings, "HAS_IMAGE_BASE_URL", "http://127.0.0.1:8081")
    monkeypatch.setattr(client_mod.settings, "HAS_IMAGE_CONF", 0.25)
    monkeypatch.setattr(client_mod.settings, "HAS_IMAGE_TIMEOUT", 30.0)

    captured = {}

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, url, json=None):
            captured["json"] = json
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value={"boxes": []})
            return resp

    monkeypatch.setattr(client_mod.httpx, "AsyncClient", FakeClient)

    asyncio.run(client_mod.detect_privacy_regions(b"x", category_slugs=None))
    assert "categories" not in captured["json"]


def test_detect_privacy_regions_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(client_mod.settings, "HAS_IMAGE_BASE_URL", "http://127.0.0.1:8081")
    monkeypatch.setattr(client_mod.settings, "HAS_IMAGE_CONF", 0.25)
    monkeypatch.setattr(client_mod.settings, "HAS_IMAGE_TIMEOUT", 30.0)

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, url, json=None):
            resp = MagicMock()
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "err", request=MagicMock(), response=MagicMock()
            )
            return resp

    monkeypatch.setattr(client_mod.httpx, "AsyncClient", FakeClient)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client_mod.detect_privacy_regions(b"x"))
