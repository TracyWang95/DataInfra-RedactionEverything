"""Runtime compatibility API for the text NER backend."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.llamacpp_probe import probe_llamacpp
from app.core.ner_runtime import NerBackendRuntime, load_ner_runtime, save_ner_runtime
from app.services import model_config_service

router = APIRouter(prefix="/ner-backend", tags=["text-ner-backend"])
logger = logging.getLogger(__name__)


def _with_hint(message: str, hint: str | None) -> str:
    return f"{message} {hint}" if hint else message


def _saved_vs_form_hint(body: NerBackendRuntime) -> str | None:
    runtime = load_ner_runtime()
    if runtime is None:
        return None
    if runtime.llamacpp_base_url.rstrip("/") != body.llamacpp_base_url.rstrip("/"):
        return (
            "Note: the sidebar health check uses the saved endpoint; this test used the endpoint currently in the form."
        )
    return None


def _effective_defaults() -> NerBackendRuntime:
    return NerBackendRuntime(llamacpp_base_url=model_config_service.get_text_ner_base_url())


@router.get("", response_model=NerBackendRuntime)
async def get_ner_backend() -> NerBackendRuntime:
    """Return the active text NER endpoint, preserving the legacy response shape."""
    runtime = load_ner_runtime()
    if runtime is not None:
        return runtime
    return _effective_defaults()


@router.put("", response_model=NerBackendRuntime)
async def put_ner_backend(body: NerBackendRuntime) -> NerBackendRuntime:
    """Save the text NER endpoint and mirror it into the unified model config."""
    save_ner_runtime(body)
    model_config_service.sync_legacy_text_ner_base_url(body.llamacpp_base_url)
    return body


@router.delete("")
async def delete_ner_backend() -> dict[str, str | bool]:
    """Clear the legacy runtime override and restore the text NER default config."""
    path = os.path.join(get_settings().DATA_DIR, "ner_backend.json")
    if os.path.exists(path):
        os.remove(path)
    model_config_service.reset_text_ner_to_default()
    return {"ok": True, "message": "Text NER endpoint reset to the environment default."}


@router.post("/test")
async def test_ner_backend(body: NerBackendRuntime) -> dict[str, bool | str]:
    """Test an OpenAI-compatible text NER endpoint without saving it first."""
    hint = _saved_vs_form_hint(body)
    try:
        ok, _probe_message, _used_url, strict = probe_llamacpp(body.llamacpp_base_url, timeout=8.0)
        if not ok:
            return {
                "success": False,
                "message": _with_hint(
                    "Text NER connectivity test failed; check the service URL and process state.",
                    hint,
                ),
            }
        message = "OpenAI-compatible endpoint is healthy." if strict else "Text NER service responded."
        return {"success": True, "message": _with_hint(message, hint)}
    except Exception:
        logger.warning("NER backend connectivity test failed", exc_info=True)
        return {
            "success": False,
            "message": _with_hint(
                "Text NER connectivity test failed; check the service URL and process state.",
                hint,
            ),
        }
