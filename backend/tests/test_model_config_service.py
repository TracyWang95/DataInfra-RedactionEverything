from __future__ import annotations

from app.services import model_config_service


def test_localhost_service_resolution_prefers_direct_port(monkeypatch):
    monkeypatch.setattr(model_config_service, "_tcp_connects", lambda host, port, timeout=0.45: True)
    monkeypatch.setattr(model_config_service, "_wsl_host_candidates", lambda: ["172.20.1.10"])
    model_config_service._WSL_SERVICE_CACHE.clear()

    assert model_config_service.resolve_localhost_service_base_url("http://127.0.0.1:8082") == "http://127.0.0.1:8082"


def test_localhost_service_resolution_uses_wsl_when_localhost_is_down(monkeypatch):
    def fake_tcp(host: str, port: int, timeout: float = 0.45) -> bool:
        return host == "172.20.1.10" and port == 8082

    monkeypatch.setattr(model_config_service, "_tcp_connects", fake_tcp)
    monkeypatch.setattr(model_config_service, "_wsl_host_candidates", lambda: ["172.20.1.10"])
    model_config_service._WSL_SERVICE_CACHE.clear()

    assert model_config_service.resolve_localhost_service_base_url("http://127.0.0.1:8082") == "http://172.20.1.10:8082"


def test_localhost_service_resolution_preserves_remote_url(monkeypatch):
    monkeypatch.setattr(model_config_service, "_tcp_connects", lambda host, port, timeout=0.45: False)
    monkeypatch.setattr(model_config_service, "_wsl_host_candidates", lambda: ["172.20.1.10"])
    model_config_service._WSL_SERVICE_CACHE.clear()

    assert model_config_service.resolve_localhost_service_base_url("http://10.0.0.8:8082") == "http://10.0.0.8:8082"
