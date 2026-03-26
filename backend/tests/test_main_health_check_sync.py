"""主应用 check_sync：HaS Image /health 中 status=unavailable 须判为离线。"""
from unittest.mock import MagicMock

from app.main import check_sync


def test_check_sync_ready_true_when_json_ready_missing(monkeypatch):
    """无 ready 字段时默认视为可用（兼容旧 OCR 等）。"""

    class CM:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            r = MagicMock()
            r.status_code = 200
            r.json = lambda: {"model": "paddle"}
            return r

    monkeypatch.setattr("app.main.httpx.Client", lambda **kw: CM())
    name, ok = check_sync("http://x/health", "Default")
    assert ok is True
    assert name == "paddle"


def test_check_sync_offline_when_status_unavailable(monkeypatch):
    class CM:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            r = MagicMock()
            r.status_code = 200
            r.json = lambda: {
                "status": "unavailable",
                "ready": False,
                "model": "HaS-Image-YOLO11",
            }
            return r

    monkeypatch.setattr("app.main.httpx.Client", lambda **kw: CM())
    name, ok = check_sync("http://x/health", "HaS Image YOLO")
    assert ok is False
    assert name == "HaS-Image-YOLO11"


def test_check_sync_offline_on_connection_error(monkeypatch):
    class CM:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            raise OSError("connection refused")

    monkeypatch.setattr("app.main.httpx.Client", lambda **kw: CM())
    name, ok = check_sync("http://127.0.0.1:8081/health", "HaS Image YOLO")
    assert ok is False
    assert name == "HaS Image YOLO"
