from __future__ import annotations

from app.services import model_config_service


def _use_temp_model_config(monkeypatch, tmp_path):
    monkeypatch.setattr(model_config_service.settings, "MODEL_CONFIG_PATH", str(tmp_path / "model_config.json"))


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


def test_default_configs_have_active_task_slots(monkeypatch, tmp_path):
    _use_temp_model_config(monkeypatch, tmp_path)

    configs = model_config_service.load_configs()

    assert configs.active_by_task[model_config_service.TASK_TEXT_NER] == model_config_service.TEXT_NER_SERVICE_ID
    assert configs.active_by_task[model_config_service.TASK_OCR] == model_config_service.PADDLE_OCR_SERVICE_ID
    assert configs.active_by_task[model_config_service.TASK_VISUAL_FEATURE] == model_config_service.VISUAL_FEATURES_SERVICE_ID
    assert model_config_service.get_text_ner_config().task_type == model_config_service.TASK_TEXT_NER
    assert model_config_service.get_active_visual_feature_config().task_type == model_config_service.TASK_VISUAL_FEATURE


def test_set_active_ocr_model_changes_ocr_base_url(monkeypatch, tmp_path):
    _use_temp_model_config(monkeypatch, tmp_path)

    mineru = model_config_service.get_config(model_config_service.MINERU_PIPELINE_SERVICE_ID)
    assert mineru is not None
    updated, error = model_config_service.update_config(
        mineru.id,
        mineru.model_copy(update={"enabled": True, "base_url": "http://127.0.0.1:8083"}),
    )
    assert error == ""
    assert updated is not None

    success, message = model_config_service.set_active_for_task(
        model_config_service.TASK_OCR,
        model_config_service.MINERU_PIPELINE_SERVICE_ID,
    )

    assert success, message
    assert model_config_service.get_paddle_ocr_base_url() == "http://127.0.0.1:8083"
    assert model_config_service.is_mineru_ocr_active() is True


def test_is_mineru_ocr_active_false_for_paddle(monkeypatch, tmp_path):
    _use_temp_model_config(monkeypatch, tmp_path)

    success, message = model_config_service.set_active_for_task(
        model_config_service.TASK_OCR,
        model_config_service.PADDLE_OCR_SERVICE_ID,
    )
    assert success, message
    assert model_config_service.is_mineru_ocr_active() is False


def test_apply_preset_enables_optional_models(monkeypatch, tmp_path):
    _use_temp_model_config(monkeypatch, tmp_path)

    configs, error = model_config_service.apply_preset("mineru-document")

    assert error == ""
    assert configs is not None
    assert configs.preset_id == "mineru-document"
    assert configs.active_by_task[model_config_service.TASK_OCR] == model_config_service.MINERU_PIPELINE_SERVICE_ID
    assert model_config_service.get_config(model_config_service.MINERU_PIPELINE_SERVICE_ID).enabled is True


def test_set_active_rejects_model_from_another_task(monkeypatch, tmp_path):
    _use_temp_model_config(monkeypatch, tmp_path)

    success, message = model_config_service.set_active_for_task(
        model_config_service.TASK_OCR,
        model_config_service.TEXT_NER_SERVICE_ID,
    )

    assert success is False
    assert message == "Config belongs to another task"
