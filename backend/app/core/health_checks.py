# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
健康检查辅助函数
同步探测外部 HTTP 服务状态（供 /health/services 在线程池中调用）。
"""
from __future__ import annotations

import httpx

from app.core.config import get_has_display_name, get_has_chat_base_url, get_has_health_check_url

# ---------------------------------------------------------------------------
# Shared HTTP client (connection-pooled singleton)
# ---------------------------------------------------------------------------
_health_check_client = httpx.Client(timeout=45.0, trust_env=False)


def check_sync(url: str, default_name: str, timeout: float = 3.0) -> tuple:
    """同步检查 HTTP 服务（供 /health/services 在线程池中调用）。复用连接池。"""
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
            # 显式带 ready 字段时以布尔为准（OCR / HaS Image）；缺省则视为就绪
            ready = bool(data["ready"]) if "ready" in data else True
            if data.get("status") == "unavailable":
                ready = False
            return name, ready
    except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError):
        pass
    return default_name, False


def check_has_ner() -> tuple:
    """HaS：llama-server 部分构建无 GET /v1/models，需多路径探测。"""
    from app.core.llamacpp_probe import probe_llamacpp

    default_name = get_has_display_name()
    ok, _name, _, _strict = probe_llamacpp(get_has_chat_base_url(), timeout=3.0)
    if ok:
        return default_name, True
    return default_name, False
