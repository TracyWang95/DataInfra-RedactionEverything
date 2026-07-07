"""
健康检查辅助函数
同步探测外部 HTTP 服务状态（供 /health/services 在线程池中调用）。
"""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import BACKEND_DIR, get_has_chat_base_url, get_has_display_name


@dataclass(frozen=True)
class ServiceHealth:
    name: str
    status: str
    detail: dict[str, Any] = field(default_factory=dict)

    def as_service_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name, "status": self.status}
        if self.detail:
            payload["detail"] = self.detail
        return payload

# ---------------------------------------------------------------------------
# Shared HTTP client (connection-pooled singleton)
# ---------------------------------------------------------------------------
_health_check_client = httpx.Client(timeout=45.0, trust_env=False)

_SERVING_STATUSES = frozenset({"busy", "running", "processing", "inferencing"})
_LOADING_STATUSES = frozenset({"loading", "starting", "warming_up", "warming-up"})
_UNAVAILABLE_STATUSES = frozenset({"unavailable", "offline", "degraded", "error", "failed"})


def _payload_model_name(data: dict[str, Any], default_name: str) -> str:
    if "model" in data:
        return str(data["model"])
    if "data" in data and isinstance(data["data"], list) and data["data"]:
        return str(data["data"][0].get("id", default_name))
    if "models" in data and isinstance(data["models"], list) and data["models"]:
        return str(data["models"][0].get("name", default_name))
    return default_name


def _normalize_http_health_payload(
    data: dict[str, Any],
    default_name: str,
    *,
    service_kind: str,
) -> ServiceHealth:
    name = _payload_model_name(data, default_name)
    status_text = str(data.get("status", "")).strip().lower()
    ready = bool(data["ready"]) if "ready" in data else True

    detail: dict[str, Any] = {
        "reachable": True,
        "ready": ready,
    }
    for key in (
        "runtime",
        "runtime_mode",
        "gpu_available",
        "device",
        "gpu_only_mode",
        "cpu_fallback_risk",
        "structure_ready",
        "weights",
    ):
        if key in data:
            detail[key] = data[key]
    _apply_runtime_contract(detail, service_kind=service_kind)

    if status_text in _SERVING_STATUSES or status_text in _LOADING_STATUSES:
        detail["model_state"] = "serving" if status_text in _SERVING_STATUSES else "loading"
        status = "degraded" if detail.get("cpu_fallback_risk") else "online"
        return ServiceHealth(name=name, status=status, detail=detail)
    if status_text in _UNAVAILABLE_STATUSES:
        detail["model_state"] = "not_ready"
        return ServiceHealth(name=name, status="degraded", detail=detail)
    if not ready:
        detail["model_state"] = "not_ready"
        return ServiceHealth(name=name, status="degraded", detail=detail)

    detail["model_state"] = "ready"
    if service_kind == "ocr" and "gpu_available" not in detail:
        detail["gpu_available"] = None
    status = "degraded" if detail.get("cpu_fallback_risk") else "online"
    return ServiceHealth(name=name, status=status, detail=detail)


def _apply_runtime_contract(detail: dict[str, Any], *, service_kind: str) -> None:
    """Normalize model runtime fields without claiming CPU as healthy GPU."""
    has_runtime_signal = any(
        key in detail
        for key in (
            "runtime",
            "runtime_mode",
            "gpu_available",
            "device",
            "gpu_only_mode",
            "cpu_fallback_risk",
        )
    )
    if service_kind == "model" and not has_runtime_signal:
        return
    if service_kind == "visual_features" and not has_runtime_signal:
        # A healthy LocateAnything response proves reachability/readiness but
        # not the exact device; keep the service online while surfacing the
        # runtime as unknown instead of claiming CPU fallback.
        detail.setdefault("runtime", "locateanything")
        detail.setdefault("runtime_mode", "unknown")
        detail.setdefault("cpu_fallback_risk", False)
        return

    gpu_available = detail.get("gpu_available")
    device = str(detail.get("device") or "").strip().lower()
    gpu_only_mode = detail.get("gpu_only_mode")

    if "runtime" not in detail:
        if service_kind == "ocr":
            detail["runtime"] = "paddleocr"
        elif service_kind == "visual_features":
            detail["runtime"] = "locateanything"

    if detail.get("runtime_mode") not in {"gpu", "cpu", "unknown"}:
        if gpu_available is True or device.startswith("gpu") or "cuda" in device:
            detail["runtime_mode"] = "gpu"
        elif gpu_available is False or device in {"cpu", "xpu", "unknown"}:
            detail["runtime_mode"] = "cpu" if device == "cpu" or gpu_available is False else "unknown"
        else:
            detail["runtime_mode"] = "unknown"

    if "cpu_fallback_risk" not in detail:
        detail["cpu_fallback_risk"] = bool(
            detail.get("runtime_mode") != "gpu"
            or gpu_only_mode is False
            or (gpu_only_mode is True and gpu_available is False)
        )

    if gpu_only_mode is True and detail.get("runtime_mode") != "gpu":
        detail["cpu_fallback_risk"] = True


def check_sync(url: str, default_name: str, timeout: float = 3.0) -> tuple:
    """Check an HTTP service synchronously for health endpoints."""
    try:
        resp = _health_check_client.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            name = default_name
            if "model" in data:
                name = data["model"]
            elif "data" in data and isinstance(data["data"], list) and data["data"]:
                name = data["data"][0].get("id", default_name)
            elif "models" in data and isinstance(data["models"], list) and data["models"]:
                name = data["models"][0].get("name", default_name)
            # Honor explicit ready flags; missing ready means the endpoint is usable.
            status = str(data.get("status", "")).lower()
            if status in _SERVING_STATUSES or status in _LOADING_STATUSES:
                return name, True
            ready = bool(data["ready"]) if "ready" in data else True
            if status == "unavailable":
                ready = False
            return name, ready
    except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError):
        pass
    return default_name, False


def check_service_health_sync(
    url: str,
    default_name: str,
    timeout: float = 3.0,
    service_kind: str = "model",
) -> ServiceHealth:
    """Check a generic model microservice and return product-facing status.

    A responding service that reports busy/loading is online: it may be doing
    useful inference work. A responding service that is not ready is degraded,
    not offline.
    """
    try:
        resp = _health_check_client.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                return _normalize_http_health_payload(data, default_name, service_kind=service_kind)
        return ServiceHealth(
            name=default_name,
            status="degraded",
            detail={"reachable": True, "http_status": resp.status_code, "model_state": "not_ready"},
        )
    except httpx.TimeoutException:
        if _tcp_port_open(url):
            return ServiceHealth(
                name=default_name,
                status="online",
                detail={
                    "reachable": True,
                    "probe": "health_timeout_port_open",
                    "model_state": "serving",
                },
            )
        return ServiceHealth(
            name=default_name,
            status="offline",
            detail={"reachable": False, "model_state": "unreachable"},
        )
    except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError):
        return ServiceHealth(
            name=default_name,
            status="offline",
            detail={"reachable": False, "model_state": "unreachable"},
        )


def _tcp_port_open(url: str, timeout: float = 0.75) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_ocr_sync(url: str, default_name: str, timeout: float = 5.0) -> tuple[str, str]:
    """Check OCR service with delivery-oriented status semantics.

    PaddleOCR-VL can hold the single-worker service while it is running a long
    inference. During that window /health may time out even though the process
    and port are alive. For product-facing service status, a live model process
    is still online; queue/progress state belongs to the task UI.
    """
    try:
        resp = _health_check_client.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            name = data.get("model", default_name)
            status = str(data.get("status", "")).lower()
            if status in _SERVING_STATUSES or status in _LOADING_STATUSES:
                return name, "online"
            if status in _UNAVAILABLE_STATUSES:
                return name, "degraded"
            ready = bool(data["ready"]) if "ready" in data else True
            return name, "online" if ready else "degraded"
    except httpx.TimeoutException:
        if _tcp_port_open(url):
            return default_name, "online"
    except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError):
        pass
    return default_name, "offline"


def check_ocr_health_sync(url: str, default_name: str, timeout: float = 5.0) -> ServiceHealth:
    """OCR health with the same non-misleading online/degraded/offline contract."""
    try:
        resp = _health_check_client.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                return _normalize_http_health_payload(data, default_name, service_kind="ocr")
        return ServiceHealth(
            name=default_name,
            status="degraded",
            detail={"reachable": True, "http_status": resp.status_code, "model_state": "not_ready"},
        )
    except httpx.TimeoutException:
        if _tcp_port_open(url):
            return ServiceHealth(
                name=default_name,
                status="online",
                detail={
                    "reachable": True,
                    "probe": "health_timeout_port_open",
                    "model_state": "serving",
                },
            )
    except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError):
        pass
    return ServiceHealth(
        name=default_name,
        status="offline",
        detail={"reachable": False, "model_state": "unreachable"},
    )


def check_has_ner() -> tuple:
    """HaS Text: OpenAI-compatible vLLM/llama.cpp endpoint; a busy open port is still usable."""
    from app.core.llamacpp_probe import probe_llamacpp

    default_name = get_has_display_name()
    ok, _name, _, _strict = probe_llamacpp(get_has_chat_base_url(), timeout=3.0)
    if ok:
        return default_name, "online"
    if _tcp_port_open(get_has_chat_base_url()):
        return default_name, "online"
    return default_name, "offline"


def _has_text_runtime_detail() -> dict[str, Any]:
    runtime = _runtime_config_value("HAS_TEXT_RUNTIME").lower()
    if runtime == "vllm":
        return {
            "runtime": "vllm server",
            "runtime_mode": "gpu",
            "gpu_available": True,
            "gpu_enabled": True,
            "gpu_only_mode": True,
            "gpu_provider": "cuda",
            "device": "CUDA0",
            "cpu_fallback_risk": False,
            "runtime_expectation": "cuda-gpu",
            "model": _runtime_config_value("HAS_TEXT_MODEL_NAME") or "HaS_4.0_0.6B",
        }
    gpu_layers = _runtime_config_value("HAS_TEXT_N_GPU_LAYERS") or "-1"
    device = _runtime_config_value("HAS_TEXT_DEVICE")
    gpu_provider = _runtime_config_value("HAS_TEXT_GPU_PROVIDER")
    allow_cpu = _runtime_config_value("HAS_TEXT_ALLOW_CPU").lower() in {"1", "true", "yes", "on"}
    detail: dict[str, Any] = {
        "runtime": "llama.cpp server",
        "gpu_layers": gpu_layers if gpu_layers else None,
        "device": device if device else None,
        "gpu_provider": gpu_provider if gpu_provider else None,
        "gpu_only_mode": not allow_cpu and gpu_layers != "0",
    }
    if gpu_layers == "0":
        detail["gpu_enabled"] = False
        detail["runtime_mode"] = "cpu"
        detail["gpu_provider"] = "none"
    elif gpu_layers:
        detail["gpu_enabled"] = True
        detail["runtime_mode"] = "gpu"
        if not detail["gpu_provider"]:
            detail["gpu_provider"] = _infer_gpu_provider(device)
    else:
        detail["gpu_enabled"] = None
        detail["runtime_mode"] = "unknown"
    detail["runtime_expectation"] = "cuda-gpu"
    detail["cpu_fallback_risk"] = allow_cpu or detail["runtime_mode"] != "gpu"
    return detail


def get_visual_features_runtime_detail() -> dict[str, Any]:
    device = _runtime_config_value("LOCATE_ANYTHING_DEVICE") or "cuda"
    provider = _infer_gpu_provider(device)
    return {
        "runtime": "transformers-locateanything",
        "runtime_mode": "gpu",
        "gpu_available": True,
        "gpu_enabled": True,
        "device": device if device else None,
        "gpu_provider": provider,
        "gpu_only_mode": True,
        "cpu_fallback_risk": False,
        "runtime_expectation": "cuda-gpu",
        "max_new_tokens": int(_runtime_config_value("LOCATE_ANYTHING_MAX_NEW_TOKENS") or 8192),
    }


def _infer_gpu_provider(device: str) -> str:
    value = str(device or "").strip().lower()
    if not value:
        return "configured"
    if "vulkan" in value:
        return "vulkan"
    if "cuda" in value or value.isdigit():
        return "cuda"
    if "metal" in value:
        return "metal"
    return "configured"


def _runtime_config_value(name: str) -> str:
    env_value = os.environ.get(name, "").strip()
    if env_value:
        return env_value
    return _read_runtime_dotenv_value(name)


def _read_runtime_dotenv_value(name: str) -> str:
    for env_path in (BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"):
        value = _read_dotenv_value(env_path, name)
        if value:
            return value
    return ""


def _read_dotenv_value(path: Path, name: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    prefix = f"{name}="
    export_prefix = f"export {name}="
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(export_prefix):
            value = line[len(export_prefix):]
        elif line.startswith(prefix):
            value = line[len(prefix):]
        else:
            continue
        return value.strip().strip("\"'")
    return ""


def check_has_ner_health() -> ServiceHealth:
    """HaS Text status without exposing transient OpenAI-compatible server busy/loading copy."""
    from app.core.llamacpp_probe import probe_llamacpp

    default_name = get_has_display_name()
    ok, name_or_detail, hit_url, strict = probe_llamacpp(get_has_chat_base_url(), timeout=3.0)
    detail = _has_text_runtime_detail()
    detail.update({"strict_probe": strict, "probe_url": hit_url})
    if ok:
        display_name = name_or_detail if strict else default_name
        model_state = "ready" if strict else "responding_slowly"
        if not strict and name_or_detail:
            detail["probe_message"] = name_or_detail
        return ServiceHealth(
            name=display_name or default_name,
            status="degraded" if detail.get("cpu_fallback_risk") else "online",
            detail={**detail, "reachable": True, "model_state": model_state},
        )
    if _tcp_port_open(get_has_chat_base_url()):
        return ServiceHealth(
            name=default_name,
            status="degraded" if detail.get("cpu_fallback_risk") else "online",
            detail={
                **detail,
                "reachable": True,
                "probe": "health_failed_port_open",
                "model_state": "responding_slowly",
            },
        )
    return ServiceHealth(
        name=default_name,
        status="offline",
        detail={**detail, "reachable": False, "model_state": "unreachable"},
    )
