"""无 ner_backend.json 时，Ollama 模式应优先 HAS_OLLAMA_BASE_URL，而非遗留 HAS_BASE_URL。"""
import app.core.ner_runtime as ner_runtime_mod
from app.core import config as config_mod


def test_get_has_chat_base_url_prefers_ollama_url_when_backend_ollama(monkeypatch):
    monkeypatch.setattr(ner_runtime_mod, "load_ner_runtime", lambda: None)
    monkeypatch.setenv("HAS_NER_BACKEND", "ollama")
    monkeypatch.setenv("HAS_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("HAS_BASE_URL", "http://127.0.0.1:8080/v1")
    config_mod.get_settings.cache_clear()
    try:
        url = config_mod.get_has_chat_base_url()
        assert "11434" in url
        assert "8080" not in url
    finally:
        config_mod.get_settings.cache_clear()
