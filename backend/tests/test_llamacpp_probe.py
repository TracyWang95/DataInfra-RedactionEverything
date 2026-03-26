"""llamacpp_probe：URL 列表与全 404 分支。"""
from unittest.mock import MagicMock, patch

from app.core.llamacpp_probe import iter_llamacpp_probe_urls, probe_llamacpp


def test_iter_llamacpp_probe_urls_includes_v1_health():
    urls = iter_llamacpp_probe_urls("http://127.0.0.1:8080/v1")
    assert "http://127.0.0.1:8080/v1/models" in urls
    assert "http://127.0.0.1:8080/v1/health" in urls
    assert "http://127.0.0.1:8080/health" in urls


@patch("app.core.llamacpp_probe.httpx.Client")
def test_probe_all_404_returns_false_with_hint(mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.json.side_effect = AssertionError("should not parse")

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = None
    mock_client.get.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    ok, msg, url, strict = probe_llamacpp("http://127.0.0.1:8080/v1", timeout=1.0)
    assert ok is False
    assert "404" in msg or "上述路径" in msg
    assert url is None
    assert strict is False


@patch("app.core.llamacpp_probe.httpx.Client")
def test_probe_v1_health_ok(mock_client_cls):
    calls = []

    def side_effect(url, **kwargs):
        r = MagicMock()
        if "/v1/models" in url:
            r.status_code = 404
        elif "/v1/health" in url:
            r.status_code = 200
            r.json.return_value = {"status": "ok"}
        else:
            r.status_code = 404
        calls.append(url)
        return r

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = None
    mock_client.get.side_effect = side_effect
    mock_client_cls.return_value = mock_client

    ok, name, hit, strict = probe_llamacpp("http://127.0.0.1:8080/v1", timeout=1.0)
    assert ok is True
    assert strict is True
    assert "llama-server" in name or name
    assert hit and "/health" in hit
