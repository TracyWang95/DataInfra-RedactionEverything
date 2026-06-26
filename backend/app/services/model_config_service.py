"""Model runtime configuration for text NER, OCR, and visual features."""

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
from app.models.schemas import (
    ModelConfig,
    ModelConfigList,
    ModelConfigPreset,
    ModelConfigPresetList,
    ModelTaskType,
)

logger = logging.getLogger(__name__)

TASK_TEXT_NER: ModelTaskType = "text_ner"
TASK_OCR: ModelTaskType = "ocr"
TASK_VISUAL_FEATURE: ModelTaskType = "visual_feature"
MODEL_TASKS: tuple[ModelTaskType, ...] = (TASK_TEXT_NER, TASK_OCR, TASK_VISUAL_FEATURE)

TEXT_NER_SERVICE_ID = "has_text_0209_06b"
PADDLE_OCR_SERVICE_ID = "paddle_ocr_service"
MINERU_PIPELINE_SERVICE_ID = "mineru_pipeline_service"
VISUAL_FEATURES_SERVICE_ID = "visual_features_service"
HAS_IMAGE_GLM_SERVICE_ID = "has_image_yolo11_glm46v_flash"

_BUILTIN_IDS = frozenset(
    {
        TEXT_NER_SERVICE_ID,
        PADDLE_OCR_SERVICE_ID,
        MINERU_PIPELINE_SERVICE_ID,
        VISUAL_FEATURES_SERVICE_ID,
        HAS_IMAGE_GLM_SERVICE_ID,
    }
)

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_WSL_SERVICE_CACHE: dict[tuple[str, int], tuple[float, str | None]] = {}
_WSL_SERVICE_CACHE_TTL_SEC = 30.0

_SERVING_STATUSES = frozenset({"busy", "running", "processing", "inferencing"})
_LOADING_STATUSES = frozenset({"loading", "starting", "warming_up", "warming-up"})
_UNAVAILABLE_STATUSES = frozenset({"unavailable", "offline", "degraded", "error", "failed"})


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def _legacy_ner_runtime_base_url() -> str | None:
    try:
        from app.core.ner_runtime import load_ner_runtime

        runtime = load_ner_runtime()
        if runtime and runtime.llamacpp_base_url:
            return runtime.llamacpp_base_url
    except Exception:
        logger.debug("Unable to read legacy NER runtime config", exc_info=True)
    return None


def _text_ner_base_url() -> str:
    legacy = _legacy_ner_runtime_base_url()
    if legacy:
        return legacy
    if settings.HAS_TEXT_RUNTIME.strip().lower() == "vllm":
        return settings.HAS_TEXT_VLLM_BASE_URL
    if settings.HAS_BASE_URL:
        return settings.HAS_BASE_URL
    return settings.HAS_LLAMACPP_BASE_URL or "http://127.0.0.1:8080/v1"


def _display_model_name(raw: str) -> str:
    """Show a short model id in UI/health; strip local filesystem paths."""
    value = str(raw or "").strip()
    if not value:
        return value
    if "/" in value or "\\" in value:
        leaf = os.path.basename(value.replace("\\", "/"))
        if leaf:
            return leaf
    return value


def _text_ner_runtime_model_name() -> str:
    return settings.HAS_TEXT_MODEL_NAME or "HaS_Text_0209_0.6B"


def _text_ner_model_name() -> str:
    return _display_model_name(_text_ner_runtime_model_name())


def _visual_features_base_url() -> str:
    return str(getattr(settings, "VISUAL_FEATURES_BASE_URL", None) or "http://127.0.0.1:8090")


def _visual_features_runtime_model_name() -> str:
    return str(
        getattr(settings, "VISUAL_FEATURES_MODEL_NAME", None)
        or getattr(settings, "LOCATE_ANYTHING_MODEL", None)
        or "LocateAnything-3B-HF"
    )


def _visual_features_model_name() -> str:
    return _display_model_name(_visual_features_runtime_model_name())


def _default_configs() -> ModelConfigList:
    configs = [
        ModelConfig(
            id=TEXT_NER_SERVICE_ID,
            name="HaS Text 0209 0.6B",
            provider="local",
            task_type=TASK_TEXT_NER,
            enabled=True,
            base_url=_text_ner_base_url(),
            model_name=_text_ner_model_name(),
            temperature=0.0,
            top_p=0.6,
            max_tokens=max(128, min(32768, int(getattr(settings, "HAS_NER_MAX_TOKENS", 8192) or 8192))),
            enable_thinking=False,
            description="Default semantic NER model for text, OCR text, and structured-data enrichment.",
        ),
        ModelConfig(
            id=PADDLE_OCR_SERVICE_ID,
            name="PaddleOCR-VL 1.6",
            provider="local",
            task_type=TASK_OCR,
            enabled=True,
            base_url=settings.OCR_BASE_URL,
            model_name="PaddleOCR-VL-1.6",
            temperature=0.8,
            top_p=0.6,
            max_tokens=4096,
            enable_thinking=False,
            description="Default OCR/layout service. The adapter may combine PP-StructureV3 and PaddleOCR-VL.",
        ),
        ModelConfig(
            id=MINERU_PIPELINE_SERVICE_ID,
            name="MinerU Pipeline",
            provider="local",
            task_type=TASK_OCR,
            enabled=False,
            base_url=_env("MINERU_PIPELINE_BASE_URL", "http://127.0.0.1:8083"),
            model_name="mineru-pipeline",
            temperature=0.1,
            top_p=0.6,
            max_tokens=4096,
            enable_thinking=False,
            description="Optional OCR/layout adapter for deployments that expose the same /ocr and /structure contract.",
        ),
        ModelConfig(
            id=VISUAL_FEATURES_SERVICE_ID,
            name="LocateAnything-3B-HF",
            provider="local",
            task_type=TASK_VISUAL_FEATURE,
            enabled=True,
            base_url=_visual_features_base_url(),
            model_name=_visual_features_model_name(),
            temperature=0.1,
            top_p=0.6,
            max_tokens=max(8192, int(getattr(settings, "LOCATE_ANYTHING_MAX_NEW_TOKENS", 8192) or 8192)),
            enable_thinking=False,
            description="Default visual feature localization service for fixed and custom visual labels.",
        ),
        ModelConfig(
            id=HAS_IMAGE_GLM_SERVICE_ID,
            name="HaS Image YOLO11 + GLM-4.6V-Flash",
            provider="local",
            task_type=TASK_VISUAL_FEATURE,
            enabled=False,
            base_url=_env("HAS_IMAGE_GLM_BASE_URL", "http://127.0.0.1:8091"),
            model_name="has-image-yolo11+glm-4.6v-flash",
            temperature=0.1,
            top_p=0.6,
            max_tokens=8192,
            enable_thinking=False,
            description="Optional visual adapter for deployments that combine YOLO11 detection with GLM-4.6V-Flash grounding.",
        ),
    ]
    return ModelConfigList(
        configs=configs,
        active_id=VISUAL_FEATURES_SERVICE_ID,
        active_by_task={
            TASK_TEXT_NER: TEXT_NER_SERVICE_ID,
            TASK_OCR: PADDLE_OCR_SERVICE_ID,
            TASK_VISUAL_FEATURE: VISUAL_FEATURES_SERVICE_ID,
        },
        preset_id="balanced-local",
    )


_PRESETS = [
    ModelConfigPreset(
        id="balanced-local",
        name="Balanced local",
        description="HaS Text 0209 0.6B + PaddleOCR-VL 1.6 + LocateAnything-3B-HF.",
        active_by_task={
            TASK_TEXT_NER: TEXT_NER_SERVICE_ID,
            TASK_OCR: PADDLE_OCR_SERVICE_ID,
            TASK_VISUAL_FEATURE: VISUAL_FEATURES_SERVICE_ID,
        },
        recommended_chips=["NVIDIA CUDA 16GB+"],
    ),
    ModelConfigPreset(
        id="mineru-document",
        name="Document OCR with MinerU",
        description="HaS Text 0209 0.6B + MinerU Pipeline + LocateAnything-3B-HF.",
        active_by_task={
            TASK_TEXT_NER: TEXT_NER_SERVICE_ID,
            TASK_OCR: MINERU_PIPELINE_SERVICE_ID,
            TASK_VISUAL_FEATURE: VISUAL_FEATURES_SERVICE_ID,
        },
        recommended_chips=["NVIDIA CUDA 24GB+", "Ascend/other chips with a MinerU adapter"],
    ),
    ModelConfigPreset(
        id="has-image-glm",
        name="HaS image and GLM vision",
        description="HaS Text 0209 0.6B + PaddleOCR-VL 1.6 + HaS Image YOLO11/GLM-4.6V-Flash.",
        active_by_task={
            TASK_TEXT_NER: TEXT_NER_SERVICE_ID,
            TASK_OCR: PADDLE_OCR_SERVICE_ID,
            TASK_VISUAL_FEATURE: HAS_IMAGE_GLM_SERVICE_ID,
        },
        recommended_chips=["NVIDIA CUDA 24GB+", "Adapter-managed mixed chips"],
    ),
]
_PRESET_BY_ID = {preset.id: preset for preset in _PRESETS}


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


def _normalize_task_type(value: str | None, config_id: str) -> ModelTaskType:
    if value in MODEL_TASKS:
        return value  # type: ignore[return-value]
    if config_id == TEXT_NER_SERVICE_ID:
        return TASK_TEXT_NER
    if config_id in {PADDLE_OCR_SERVICE_ID, MINERU_PIPELINE_SERVICE_ID}:
        return TASK_OCR
    return TASK_VISUAL_FEATURE


def _builtin_override(config: ModelConfig) -> ModelConfig:
    task_type = _normalize_task_type(config.task_type, config.id)
    update: dict[str, Any] = {"task_type": task_type}
    if config.id == TEXT_NER_SERVICE_ID:
        update.update(
            {
                "enabled": True,
                "base_url": config.base_url or _text_ner_base_url(),
                "model_name": _display_model_name(config.model_name or _text_ner_runtime_model_name()),
                "temperature": min(float(config.temperature or 0.0), 0.2),
            }
        )
    elif config.id == PADDLE_OCR_SERVICE_ID:
        update.update(
            {
                "enabled": True,
                "base_url": config.base_url or settings.OCR_BASE_URL,
                "model_name": config.model_name or "PaddleOCR-VL-1.6",
            }
        )
    elif config.id == MINERU_PIPELINE_SERVICE_ID:
        update.update(
            {
                "base_url": config.base_url or _env("MINERU_PIPELINE_BASE_URL", "http://127.0.0.1:8083"),
                "model_name": config.model_name or "mineru-pipeline",
            }
        )
    elif config.id == VISUAL_FEATURES_SERVICE_ID:
        update.update(
            {
                "enabled": True,
                "base_url": config.base_url or _visual_features_base_url(),
                "model_name": _display_model_name(
                    config.model_name or _visual_features_runtime_model_name()
                ),
                "max_tokens": max(
                    8192,
                    int(config.max_tokens or 0),
                    int(getattr(settings, "LOCATE_ANYTHING_MAX_NEW_TOKENS", 8192) or 8192),
                ),
            }
        )
    elif config.id == HAS_IMAGE_GLM_SERVICE_ID:
        update.update(
            {
                "base_url": config.base_url or _env("HAS_IMAGE_GLM_BASE_URL", "http://127.0.0.1:8091"),
                "model_name": config.model_name or "has-image-yolo11+glm-4.6v-flash",
                "max_tokens": max(8192, int(config.max_tokens or 0)),
            }
        )
    return config.model_copy(update=update)


def _selectable_for_task(config: ModelConfig, task_type: str) -> bool:
    return config.enabled and config.task_type == task_type


def _default_id_for_task(task_type: str) -> str:
    if task_type == TASK_TEXT_NER:
        return TEXT_NER_SERVICE_ID
    if task_type == TASK_OCR:
        return PADDLE_OCR_SERVICE_ID
    return VISUAL_FEATURES_SERVICE_ID


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
        normalized = config.model_copy(update={"task_type": _normalize_task_type(config.task_type, config.id)})
        if normalized.id in _BUILTIN_IDS:
            normalized = _builtin_override(normalized)
        if normalized != config:
            changed = True
        cleaned.append(normalized)

    defaults = _default_configs()
    for default in defaults.configs:
        if default.id not in seen:
            cleaned.append(default)
            seen.add(default.id)
            changed = True

    active_by_task = dict(raw.active_by_task or {})
    if raw.active_id and TASK_VISUAL_FEATURE not in active_by_task:
        active_by_task[TASK_VISUAL_FEATURE] = raw.active_id

    configs_by_id = {config.id: config for config in cleaned}
    for task_type in MODEL_TASKS:
        active_id = active_by_task.get(task_type)
        active = configs_by_id.get(str(active_id)) if active_id else None
        if active is None or not _selectable_for_task(active, task_type):
            fallback_id = _default_id_for_task(task_type)
            fallback = configs_by_id.get(fallback_id)
            if fallback is None or not _selectable_for_task(fallback, task_type):
                fallback = next((config for config in cleaned if _selectable_for_task(config, task_type)), None)
            active_by_task[task_type] = fallback.id if fallback else ""
            changed = True

    active_id = active_by_task.get(TASK_VISUAL_FEATURE) or VISUAL_FEATURES_SERVICE_ID
    if raw.active_id != active_id:
        changed = True

    preset_id = raw.preset_id if raw.preset_id in _PRESET_BY_ID else None
    if raw.preset_id != preset_id:
        changed = True

    return (
        ModelConfigList(
            configs=cleaned,
            active_id=active_id,
            active_by_task=active_by_task,
            preset_id=preset_id,
        ),
        changed,
    )


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


def get_configs_for_task(task_type: str) -> list[ModelConfig]:
    return [config for config in load_configs().configs if config.task_type == task_type]


def get_active_for_task(task_type: str) -> ModelConfig | None:
    configs = load_configs()
    config_id = configs.active_by_task.get(task_type)
    if config_id:
        active = next((config for config in configs.configs if config.id == config_id), None)
        if active and _selectable_for_task(active, task_type):
            return active
    fallback = next(
        (config for config in configs.configs if config.id == _default_id_for_task(task_type)),
        None,
    )
    if fallback and _selectable_for_task(fallback, task_type):
        return fallback
    return next((config for config in configs.configs if _selectable_for_task(config, task_type)), None)


def get_text_ner_config() -> ModelConfig | None:
    return get_active_for_task(TASK_TEXT_NER)


def get_text_ner_base_url() -> str:
    config = get_text_ner_config()
    if config and config.base_url:
        return resolve_localhost_service_base_url(config.base_url)
    return resolve_localhost_service_base_url(_text_ner_base_url())


def get_text_ner_runtime_model_name() -> str:
    """OpenAI/vLLM model id used for inference requests."""
    return _text_ner_runtime_model_name()


def get_text_ner_display_name() -> str:
    """Human-readable model id for UI and /health/services."""
    config = get_text_ner_config()
    if config and config.model_name:
        return _display_model_name(config.model_name)
    return _text_ner_model_name()


def get_text_ner_model_name() -> str:
    return get_text_ner_runtime_model_name()


def get_paddle_ocr_base_url() -> str:
    config = get_active_for_task(TASK_OCR)
    if config and config.base_url:
        return resolve_localhost_service_base_url(config.base_url)
    return resolve_localhost_service_base_url(settings.OCR_BASE_URL)


def get_ocr_model_name() -> str:
    config = get_active_for_task(TASK_OCR)
    if config and config.model_name:
        return config.model_name
    return "PaddleOCR-VL-1.6"


def is_mineru_ocr_active() -> bool:
    """True when the active OCR slot is the MinerU pipeline adapter."""
    config = get_active_for_task(TASK_OCR)
    if config is None:
        return False
    if config.id == MINERU_PIPELINE_SERVICE_ID:
        return True
    return "mineru" in str(config.model_name or "").lower()


def get_active_visual_feature_config() -> ModelConfig | None:
    return get_active_for_task(TASK_VISUAL_FEATURE)


def get_visual_features_base_url() -> str:
    config = get_active_visual_feature_config()
    if config and config.base_url:
        return resolve_localhost_service_base_url(config.base_url)
    return resolve_localhost_service_base_url(_visual_features_base_url())


def get_visual_features_config() -> ModelConfig | None:
    return get_active_visual_feature_config()


def get_active() -> ModelConfig | None:
    return get_active_visual_feature_config()


def is_visual_feature_runtime_config(config: ModelConfig) -> bool:
    return _selectable_for_task(config, TASK_VISUAL_FEATURE) and config.provider in {"local", "custom", "openai"}


def set_active_for_task(task_type: str, config_id: str) -> tuple[bool, str]:
    if task_type not in MODEL_TASKS:
        return False, "Unknown model task"
    configs = load_configs()
    target = next((config for config in configs.configs if config.id == config_id), None)
    if target is None:
        return False, "Config not found"
    if not target.enabled:
        return False, "Config is disabled"
    if target.task_type != task_type:
        return False, "Config belongs to another task"
    configs.active_by_task[task_type] = config_id
    if task_type == TASK_VISUAL_FEATURE:
        configs.active_id = config_id
    configs.preset_id = None
    save_configs(configs)
    return True, config_id


def set_active(config_id: str) -> tuple[bool, str]:
    return set_active_for_task(TASK_VISUAL_FEATURE, config_id)


def _normalize_config_for_save(config: ModelConfig, config_id: str | None = None) -> ModelConfig:
    target_id = config_id or config.id
    normalized = config.model_copy(update={"id": target_id, "task_type": _normalize_task_type(config.task_type, target_id)})
    if target_id in _BUILTIN_IDS:
        normalized = _builtin_override(normalized)
    return normalized


def create_config(config: ModelConfig) -> tuple[bool, str]:
    configs = load_configs()
    if any(item.id == config.id for item in configs.configs):
        return False, "Config id already exists"
    configs.configs.append(_normalize_config_for_save(config))
    configs, _ = _sanitize_model_config_list(configs)
    save_configs(configs)
    return True, ""


def update_config(config_id: str, config: ModelConfig) -> tuple[ModelConfig | None, str]:
    configs = load_configs()
    for index, current in enumerate(configs.configs):
        if current.id != config_id:
            continue
        updated = _normalize_config_for_save(config, config_id)
        if config.api_key is None and current.api_key:
            updated = updated.model_copy(update={"api_key": current.api_key})
        configs.configs[index] = updated
        configs.preset_id = None
        configs, _ = _sanitize_model_config_list(configs)
        save_configs(configs)
        return next((item for item in configs.configs if item.id == config_id), updated), ""
    return None, "Config not found"


def delete_config(config_id: str) -> tuple[bool, str]:
    if config_id in _BUILTIN_IDS:
        return False, "Built-in model configs cannot be deleted"
    configs = load_configs()
    next_configs = [config for config in configs.configs if config.id != config_id]
    if len(next_configs) == len(configs.configs):
        return False, "Config not found"
    configs.configs = next_configs
    configs.preset_id = None
    configs, _ = _sanitize_model_config_list(configs)
    save_configs(configs)
    return True, ""


def reset_configs() -> None:
    save_configs(_default_configs())


def get_presets() -> ModelConfigPresetList:
    return ModelConfigPresetList(presets=_PRESETS)


def apply_preset(preset_id: str) -> tuple[ModelConfigList | None, str]:
    preset = _PRESET_BY_ID.get(preset_id)
    if preset is None:
        return None, "Preset not found"
    configs = load_configs()
    by_id = {config.id: config for config in configs.configs}
    for task_type, config_id in preset.active_by_task.items():
        target = by_id.get(config_id)
        if target is None:
            return None, f"Preset config missing: {config_id}"
        if not target.enabled:
            enabled = target.model_copy(update={"enabled": True})
            configs.configs = [enabled if item.id == target.id else item for item in configs.configs]
            by_id[target.id] = enabled
        configs.active_by_task[task_type] = config_id
    configs.active_id = configs.active_by_task.get(TASK_VISUAL_FEATURE, VISUAL_FEATURES_SERVICE_ID)
    configs.preset_id = preset_id
    configs, _ = _sanitize_model_config_list(configs)
    save_configs(configs)
    return configs, ""


def sync_legacy_text_ner_base_url(base_url: str) -> None:
    configs = load_configs()
    for index, config in enumerate(configs.configs):
        if config.id == TEXT_NER_SERVICE_ID:
            configs.configs[index] = config.model_copy(update={"base_url": base_url, "enabled": True})
            configs.active_by_task[TASK_TEXT_NER] = TEXT_NER_SERVICE_ID
            configs.preset_id = None
            configs, _ = _sanitize_model_config_list(configs)
            save_configs(configs)
            return


def reset_text_ner_to_default() -> None:
    configs = load_configs()
    default = next(config for config in _default_configs().configs if config.id == TEXT_NER_SERVICE_ID)
    configs.configs = [default if config.id == TEXT_NER_SERVICE_ID else config for config in configs.configs]
    configs.active_by_task[TASK_TEXT_NER] = TEXT_NER_SERVICE_ID
    configs.preset_id = None
    configs, _ = _sanitize_model_config_list(configs)
    save_configs(configs)


async def test_paddle_ocr() -> dict[str, Any]:
    config = get_config(PADDLE_OCR_SERVICE_ID) or next(
        config for config in _default_configs().configs if config.id == PADDLE_OCR_SERVICE_ID
    )
    return await _probe_http_runtime(config, health_first=True)


async def test_config(config_id: str) -> tuple[dict[str, Any] | None, str]:
    config = get_config(config_id)
    if config is None:
        return None, "Config not found"
    health_first = config.task_type in {TASK_OCR, TASK_VISUAL_FEATURE} and config.provider == "local"
    return await _probe_http_runtime(config, health_first=health_first), ""
