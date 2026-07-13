"""
llama-server / OpenAI 兼容服务探测：不同版本/构建暴露的路径不一致。
官方文档：GET /v1/models、GET /v1/health、GET /health 等；部分环境可能仅部分路由可用。
"""
from __future__ import annotations

import concurrent.futures

import httpx


def parse_llamacpp_models_json(data: dict) -> tuple[str, bool]:
    """与 main.py /health/services 中 check_sync 对 /v1/models 的解析一致。"""
    name = "HaS"
    if "model" in data:
        name = str(data["model"])
    elif "data" in data and isinstance(data["data"], list) and data["data"]:
        name = str(data["data"][0].get("id", name))
    elif "models" in data and isinstance(data["models"], list) and data["models"]:
        name = str(data["models"][0].get("name", name))
    ready = data.get("ready", True)
    return name, ready


def iter_llamacpp_probe_urls(chat_base: str) -> list[str]:
    """
    chat_base: OpenAI 兼容根路径，如 http://127.0.0.1:8080/v1
    返回去重后的探测 URL 顺序列表。
    """
    chat = chat_base.rstrip("/")
    root = chat.replace("/v1", "").rstrip("/") or chat
    candidates = [
        f"{chat}/models",
        f"{chat}/health",
        f"{root}/v1/models",
        f"{root}/models",
        f"{root}/health",
        f"{root}/v1/health",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _is_health_url(url: str) -> bool:
    u = url.rstrip("/")
    return u.endswith("/health") or "/health" in url


def _parse_health_json(data: dict, url: str) -> tuple[bool, str]:
    """GET /health 与 GET /v1/health：常见 {\"status\": \"ok\"} 或含 model。"""
    name = str(data.get("model") or data.get("name") or "llama-server")
    st = data.get("status")
    if st in ("error", "failed"):
        return False, f"服务异常 (status={st}) ({url})"
    if st == "ok":
        return True, name
    ready = data.get("ready", True)
    if not ready:
        return False, f"服务未就绪 ({url})"
    return True, name


def _fetch_url_sync(url: str, per_timeout: float) -> tuple[str, httpx.Response | None, str]:
    """单次 GET；失败时 response 为 None，第三项为错误说明。"""
    try:
        with httpx.Client(timeout=per_timeout, trust_env=False) as client:
            r = client.get(url)
        return (url, r, "")
    except Exception as e:
        return (url, None, str(e))


def probe_llamacpp(
    chat_base: str,
    timeout: float = 8.0,
) -> tuple[bool, str, str | None, bool]:
    """
    探测 llama-server 可用端点（各 URL **并行**请求，避免顺序探测导致 /health/services 卡十几秒）。
    返回 (成功, 展示名称或错误说明, 实际命中的 URL, 是否严格 OpenAI models/health JSON)。

    第四项 True：已解析到模型/健康 JSON；False：仅探活成功（有 HTTP 响应但非标准 models 列表）。
    """
    last_detail = ""
    http_responses: list[tuple[str, int]] = []
    urls = iter_llamacpp_probe_urls(chat_base)
    if not urls:
        return (False, "无探测 URL", None, False)

    # 单次请求超时：并行后总耗时约等于「最慢的一条」，而不是「各条之和」
    per_timeout = min(2.5, max(0.8, timeout / max(len(urls), 1)))
    by_url: dict[str, httpx.Response | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(urls))) as ex:
        futures = {ex.submit(_fetch_url_sync, u, per_timeout): u for u in urls}
        done, not_done = concurrent.futures.wait(
            futures.keys(),
            timeout=min(timeout + 1.0, 12.0),
        )
        for fut in not_done:
            fut.cancel()
        for fut in done:
            try:
                u, r, err = fut.result()
                by_url[u] = r
                if err and not last_detail:
                    last_detail = err
            except Exception as e:
                last_detail = str(e)

    for url in urls:
        r = by_url.get(url)
        if r is None:
            continue
        http_responses.append((url, r.status_code))

        if r.status_code == 503:
            try:
                data = r.json()
            except Exception:
                return (
                    False,
                    f"服务暂不可用 HTTP 503（可能仍在加载模型）({url})",
                    url,
                    False,
                )
            err = data.get("error") if isinstance(data, dict) else None
            msg = ""
            if isinstance(err, dict) and err.get("message"):
                msg = str(err["message"])
            return (
                True,
                f"llama-server 已响应（模型加载中 HTTP 503）{msg or ''} · {url}",
                url,
                False,
            )

        if r.status_code != 200:
            last_detail = f"HTTP {r.status_code}"
            continue
        try:
            data = r.json()
        except Exception:
            return (
                True,
                f"服务器已响应但返回非 JSON（可能为 Web UI 或旧版接口）({url})",
                url,
                False,
            )

        if not isinstance(data, dict):
            last_detail = "响应 JSON 非对象"
            continue

        if _is_health_url(url):
            ok_h, name_or_err = _parse_health_json(data, url)
            if not ok_h:
                return False, name_or_err, url, False
            return True, name_or_err, url, True

        name, ready = parse_llamacpp_models_json(data)
        if not ready:
            return False, f"服务未就绪 (ready=false) · {name}", url, True
        return True, name, url, True

    if http_responses and all(c == 404 for _, c in http_responses):
        return (
            False,
            "上述路径均为 HTTP 404：端口上可能有进程，但不是 llama-server 的 OpenAI 路由，"
            "或使用了 --api-prefix（请把「API 根路径」写成带此前缀的 …/v1）。"
            "官方 llama-server 需能访问 GET /v1/models 或 /v1/health。",
            None,
            False,
        )

    if http_responses and any(c != 404 for _, c in http_responses):
        summary = "；".join(f"{u} → HTTP {c}" for u, c in http_responses[:6])
        if len(http_responses) > 6:
            summary += " …"
        return (
            True,
            f"服务器已响应（{summary}），但未返回可用的 /v1/models 或 health JSON；"
            "若 NER 仍可用，说明实际推理走 POST /v1/chat/completions，可忽略本提示。",
            http_responses[0][0],
            False,
        )

    return (
        False,
        last_detail or "无法连接或无任何 HTTP 响应（请确认进程与端口）",
        None,
        False,
    )
