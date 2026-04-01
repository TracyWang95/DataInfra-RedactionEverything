"""主应用 check_sync：HaS Image /health 中 status=unavailable 须判为离线。"""
from unittest.mock import MagicMock

from app.main import check_sync


def _mock_get_response(json_data, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.json = lambda: json_data
    return r


def test_check_sync_ready_true_when_json_ready_missing(monkeypatch):
    """无 ready 字段时默认视为可用（兼容旧 OCR 等）。"""
    mock_client = MagicMock()
    mock_client.get = MagicMock(return_value=_mock_get_response({"model": "paddle"}))
    monkeypatch.setattr("app.main._health_check_client", mock_client)
    name, ok = check_sync("http://x/health", "Default")
    assert ok is True
    assert name == "paddle"


def test_check_sync_offline_when_status_unavailable(monkeypatch):
    mock_client = MagicMock()
    mock_client.get = MagicMock(return_value=_mock_get_response({
        "status": "unavailable",
        "ready": False,
        "model": "HaS-Image-YOLO11",
    }))
    monkeypatch.setattr("app.main._health_check_client", mock_client)
    name, ok = check_sync("http://x/health", "HaS Image YOLO")
    assert ok is False
    assert name == "HaS-Image-YOLO11"


def test_check_sync_offline_on_connection_error(monkeypatch):
    mock_client = MagicMock()
    mock_client.get = MagicMock(side_effect=OSError("connection refused"))
    monkeypatch.setattr("app.main._health_check_client", mock_client)
    name, ok = check_sync("http://127.0.0.1:8081/health", "HaS Image YOLO")
    assert ok is False
    assert name == "HaS Image YOLO"
