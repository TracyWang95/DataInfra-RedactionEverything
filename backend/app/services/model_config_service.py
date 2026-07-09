"""Model runtime configuration for OCR and unified visual features."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from app.core.config import settings
from app.core.persistence import load_json, save_json
from app.models.schemas import ModelConfig, ModelConfigList

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_WSL_SERVICE_CACHE: dict[tuple[str, int], tuple[float, str | None]] = {}
_WSL_SERVICE_CACHE_TTL_SEC = 30.0

PADDLE_OCR_SERVICE_ID = "paddle_ocr_service"
VISUAL_FEATURES_SERVICE_ID = "visual_features_service"
_BUILTIN_IDS = frozenset({PADDLE_OCR_SERVICE_ID, VISUAL_FEATURES_SERVICE_ID})

_SERVING_STATUSES = frozenset({"busy", "running", "processing", "inferencing"})
_LOADING_STATUSES = frozenset({"loading", "starting", "warming_up", "warming-up"})
_UNAVAILABLE_STATUSES = frozenset({"unavailable", "offline", "degraded", "error", "failed"})


def _visual_features_base_url() -> str:
    return str(
        getattr(settings, "VISUAL_FEATURES_BASE_URL", None)
        or "http://127.0.0.1:9090"
    )


def _visual_features_model_name() -> str:
    return str(
        getattr(settings, "VISUAL_FEATURES_MODEL_NAME", None)
        or "LocateAnything-3B"
    )


def _default_configs() -> ModelConfigList:
    return ModelConfigList(
        configs=[
            ModelConfig(
                id=PADDLE_OCR_SERVICE_ID,
                name="PaddleOCR-VL 1.6",
                provider="local",
                enabled=True,
                base_url=settings.OCR_BASE_URL,
                model_name="PaddleOCR-VL-1.6-0.9B",
                temperature=0.8,
                top_p=0.6,
                max_tokens=4096,
                enable_thinking=False,
                description="PaddleOCR-VL 1.6 OCR/layout service.",
            ),
            ModelConfig(
                id=VISUAL_FEATURES_SERVICE_ID,
                name="LocateAnything-3B Visual Features",
                provider="local",
                enabled=True,
                base_url=_visual_features_base_url(),
                model_name=_visual_features_model_name(),
                temperature=0.1,
                top_p=0.6,
                max_tokens=max(8192, int(getattr(settings, "LOCATE_ANYTHING_MAX_NEW_TOKENS", 8192) or 8192)),
                enable_thinking=False,
                description="LocateAnything-3B grounding unifies fixed visual classes and user-defined visual labels.",
            ),
        ],
        active_id=VISUAL_FEATURES_SERVICE_ID,
    )


def _tcp_connects(host: str, port: int, timeout: float = 0.45) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wsl_host_candidates() -> list[str]:
    candidates: list[str] = []
    for key in ("WSL_MODEL_HOST", "WSL_HOST"):
        value = os.environ.get(key, "").strip()
        if value and value not in candidates:
            candidates.append(value)
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["wsl.exe", "-e", "bash", "-lc", "hostname -I | awk '{print $1}'"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                encoding="utf-8",
                errors="ignore",
                text=True,
                timeout=2.0,
            )
            value = (result.stdout or "").strip().split()[0] if result.stdout else ""
            if value and value not in candidates:
                candidates.append(value)
        except Exception:
            logger.debug("Unable to discover WSL host for model service", exc_info=True)
    return candidates


def _with_host(base_url: str, host: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.hostname or parsed.port is None:
        return base_url
    if ":" in host and not host.startswith("["):
        netloc = f"[{host}]:{parsed.port}"
    else:
        netloc = f"{host}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def resolve_localhost_service_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    host = parsed.hostname
    port = parsed.port
    if not host or port is None or host not in _LOCAL_HOSTS:
        return base_url
    if _tcp_connects(host, port):
        return base_url

    cache_key = (host, port)
    now = time.monotonic()
    cached = _WSL_SERVICE_CACHE.get(cache_key)
    if cached and now - cached[0] < _WSL_SERVICE_CACHE_TTL_SEC:
        cached_host = cached[1]
        return _with_host(base_url, cached_host) if cached_host else base_url

    for candidate in _wsl_host_candidates():
        if _tcp_connects(candidate, port):
            _WSL_SERVICE_CACHE[cache_key] = (now, candidate)
            return _with_host(base_url, candidate)

    _WSL_SERVICE_CACHE[cache_key] = (now, None)
    return base_url


def _model_state_from_payload(data: dict[str, Any]) -> tuple[str, bool]:
    status = str(data.get("status", "")).strip().lower()
    ready = bool(data["ready"]) if "ready" in data else True
    if status in _SERVING_STATUSES:
        return "serving", True
    if status in _LOADING_STATUSES:
        return "loading", True
    if status in _UNAVAILABLE_STATUSES or not ready:
        return "not_ready", False
    return "ready", True


def _model_name_from_payload(data: dict[str, Any], default_name: str) -> str:
    if isinstance(data.get("model"), str):
        return str(data["model"])
    if isinstance(data.get("data"), list) and data["data"]:
        value = data["data"][0].get("id")
        if value:
            return str(value)
    if isinstance(data.get("models"), list) and data["models"]:
        value = data["models"][0].get("name")
        if value:
            return str(value)
    return default_name


def _json_endpoint(base_url: str, suffix: str) -> str:
    base = str(base_url or "").rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/{suffix.lstrip('/')}"
    return f"{base}/v1/{suffix.lstrip('/')}"


def _preflight_result(
    *,
    success: bool,
    status: str,
    message: str,
    provider: str,
    base_url: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "success": success,
        "status": status,
        "message": message,
        "provider": provider,
        "base_url": base_url,
        "detail": detail or {},
    }


async def _probe_http_runtime(config: ModelConfig, *, health_first: bool = True) -> dict[str, Any]:
    base = resolve_localhost_service_base_url(config.base_url or "")
    urls = [f"{base.rstrip('/')}/health", _json_endpoint(base, "models")]
    if not health_first:
        urls.reverse()

    last_error = ""
    async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
        for url in urls:
            try:
                response = await client.get(url)
                if response.status_code != 200:
                    last_error = f"{response.status_code} {response.reason_phrase}"
                    continue
                data = response.json()
                if not isinstance(data, dict):
                    last_error = "non-object response"
                    continue
                state, ready = _model_state_from_payload(data)
                model = _model_name_from_payload(data, config.model_name)
                status = "online" if ready else "degraded"
                return _preflight_result(
                    success=ready,
                    status=status,
                    message=f"{model} service is {state} at {base}.",
                    provider=config.provider,
                    base_url=base,
                    detail={
                        "model": model,
                        "model_state": state,
                        "reachable": True,
                        "ready": ready,
                    },
                )
            except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
                last_error = str(exc)
    return _preflight_result(
        success=False,
        status="offline",
        message=f"{config.model_name} service is unreachable at {base}.",
        provider=config.provider,
        base_url=base,
        detail={"reachable": False, "error": last_error},
    )


def is_visual_feature_runtime_config(config: ModelConfig) -> bool:
    return (
        config.enabled
        and config.id != PADDLE_OCR_SERVICE_ID
        and config.provider in {"local", "custom", "openai"}
    )


def _builtin_override(config: ModelConfig) -> ModelConfig:
    if config.id == PADDLE_OCR_SERVICE_ID:
        return config.model_copy(
            update={
                "name": "PaddleOCR-VL 1.6",
                "enabled": True,
                "base_url": settings.OCR_BASE_URL,
                "model_name": "PaddleOCR-VL-1.6-0.9B",
            }
        )
    if config.id == VISUAL_FEATURES_SERVICE_ID:
        return config.model_copy(
            update={
                "name": "LocateAnything-3B Visual Features",
                "enabled": True,
                "base_url": config.base_url or _visual_features_base_url(),
                "model_name": config.model_name or _visual_features_model_name(),
                "max_tokens": max(
                    8192,
                    int(config.max_tokens or 0),
                    int(getattr(settings, "LOCATE_ANYTHING_MAX_NEW_TOKENS", 8192) or 8192),
                ),
            }
        )
    return config


def _sanitize_model_config_list(raw: ModelConfigList) -> tuple[ModelConfigList, bool]:
    changed = False
    cleaned: list[ModelConfig] = []
    seen: set[str] = set()

    for config in raw.configs:
        if config.provider == "zhipu":
            changed = True
            continue
        if config.id in seen:
            changed = True
            continue
        seen.add(config.id)
        cleaned.append(_builtin_override(config))

    defaults = _default_configs()
    for default in defaults.configs:
        if default.id not in seen:
            cleaned.insert(0 if default.id == PADDLE_OCR_SERVICE_ID else len(cleaned), default)
            seen.add(default.id)
            changed = True

    active_id = raw.active_id
    if active_id not in seen:
        active_id = VISUAL_FEATURES_SERVICE_ID
        changed = True
    active = next((c for c in cleaned if c.id == active_id), None)
    if active is None or not is_visual_feature_runtime_config(active):
        active_id = VISUAL_FEATURES_SERVICE_ID
        changed = True

    return ModelConfigList(configs=cleaned, active_id=active_id), changed


def load_configs() -> ModelConfigList:
    raw = load_json(settings.MODEL_CONFIG_PATH, default=None)
    if raw is not None:
        try:
            configs, changed = _sanitize_model_config_list(ModelConfigList(**raw))
            if changed:
                save_configs(configs)
            return configs
        except Exception:
            logger.warning("Unable to load model config; falling back to defaults.", exc_info=True)
    return _sanitize_model_config_list(_default_configs())[0]


def save_configs(configs: ModelConfigList) -> None:
    save_json(settings.MODEL_CONFIG_PATH, configs)


def get_configs() -> ModelConfigList:
    return load_configs()


def get_config(config_id: str) -> ModelConfig | None:
    for config in load_configs().configs:
        if config.id == config_id:
            return config
    return None


def get_paddle_ocr_base_url() -> str:
    config = get_config(PADDLE_OCR_SERVICE_ID)
    if config and config.enabled and config.base_url:
        return resolve_localhost_service_base_url(config.base_url)
    return resolve_localhost_service_base_url(settings.OCR_BASE_URL)


def get_active_visual_feature_config() -> ModelConfig | None:
    configs = load_configs()
    if configs.active_id:
        active = get_config(configs.active_id)
        if active and is_visual_feature_runtime_config(active):
            return active
    return get_config(VISUAL_FEATURES_SERVICE_ID)


def get_visual_features_base_url() -> str:
    config = get_active_visual_feature_config()
    if config and config.base_url:
        return resolve_localhost_service_base_url(config.base_url)
    return resolve_localhost_service_base_url(_visual_features_base_url())


def get_visual_features_config() -> ModelConfig | None:
    return get_active_visual_feature_config()


def get_active() -> ModelConfig | None:
    return get_active_visual_feature_config()


def set_active(config_id: str) -> tuple[bool, str]:
    configs = load_configs()
    target = next((config for config in configs.configs if config.id == config_id), None)
    if target is None:
        return False, "Config not found"
    if not target.enabled:
        return False, "Config is disabled"
    if not is_visual_feature_runtime_config(target):
        return False, "Only visual feature runtimes can be activated"
    configs.active_id = config_id
    save_configs(configs)
    return True, config_id


def create_config(config: ModelConfig) -> tuple[bool, str]:
    configs = load_configs()
    if any(item.id == config.id for item in configs.configs):
        return False, "Config id already exists"
    configs.configs.append(config)
    save_configs(configs)
    return True, ""


def update_config(config_id: str, config: ModelConfig) -> tuple[ModelConfig | None, str]:
    configs = load_configs()
    updated = config.model_copy(update={"id": config_id})
    for index, current in enumerate(configs.configs):
        if current.id != config_id:
            continue
        if config_id in _BUILTIN_IDS:
            updated = _builtin_override(updated)
        configs.configs[index] = updated
        if configs.active_id == config_id and not is_visual_feature_runtime_config(updated):
            configs.active_id = VISUAL_FEATURES_SERVICE_ID
        save_configs(configs)
        return updated, ""
    return None, "Config not found"


def delete_config(config_id: str) -> tuple[bool, str]:
    if config_id in _BUILTIN_IDS:
        return False, "Built-in model configs cannot be deleted"
    configs = load_configs()
    next_configs = [config for config in configs.configs if config.id != config_id]
    if len(next_configs) == len(configs.configs):
        return False, "Config not found"
    configs.configs = next_configs
    if configs.active_id == config_id:
        configs.active_id = VISUAL_FEATURES_SERVICE_ID
    save_configs(configs)
    return True, ""


def reset_configs() -> None:
    save_configs(_default_configs())


async def test_paddle_ocr() -> dict[str, Any]:
    config = get_config(PADDLE_OCR_SERVICE_ID) or _default_configs().configs[0]
    return await _probe_http_runtime(config, health_first=True)


async def test_config(config_id: str) -> tuple[dict[str, Any] | None, str]:
    config = get_config(config_id)
    if config is None:
        return None, "Config not found"
    if config.id == PADDLE_OCR_SERVICE_ID:
        return await test_paddle_ocr(), ""
    return await _probe_http_runtime(config, health_first=(config.provider == "local")), ""
