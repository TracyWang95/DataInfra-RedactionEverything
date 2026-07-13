"""
文本 NER 后端（HaS / llama-server）运行时配置 API
持久化至 data/ner_backend.json，优先级高于环境变量。
"""
from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.core.llamacpp_probe import probe_llamacpp
from app.core.ner_runtime import NerBackendRuntime, load_ner_runtime, save_ner_runtime

router = APIRouter(prefix="/ner-backend", tags=["文本NER后端"])
logger = logging.getLogger(__name__)


def _validate_base_url(base_url: str) -> None:
    """SSRF guard for the NER backend URL (defense-in-depth behind super_admin).

    Requires an http(s) URL with no embedded credentials. When
    NER_BACKEND_HOST_ALLOWLIST is set, the host must match an exact hostname
    or IP/CIDR entry — same shape as the structured-DB host allowlist. None
    (default) keeps the local/intranet self-hosted NER use case working.
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=422, detail="NER 后端地址必须是 http(s):// URL")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="NER 后端地址不得包含账号密码")
    allowlist = get_settings().NER_BACKEND_HOST_ALLOWLIST
    if allowlist is None:
        return
    host = parsed.hostname
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    for raw_entry in allowlist:
        entry = str(raw_entry).strip()
        if not entry:
            continue
        if host == entry:
            return
        if addr is not None:
            try:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return
            except ValueError:
                continue
    raise HTTPException(
        status_code=422,
        detail=f"NER 后端主机 '{host}' 不在 NER_BACKEND_HOST_ALLOWLIST 白名单内",
    )


def _with_hint(msg: str, hint: str | None) -> str:
    return f"{msg} {hint}" if hint else msg


def _saved_vs_form_hint(body: NerBackendRuntime) -> str | None:
    """侧栏健康检查读的是已保存配置；若与当前表单不一致，提示用户。"""
    rt = load_ner_runtime()
    if rt is None:
        return None
    if rt.llamacpp_base_url.rstrip("/") != body.llamacpp_base_url.rstrip("/"):
        return (
            "【说明】侧栏依据已保存的 API 地址；当前输入框地址与已保存不同，测试结果以输入框为准。"
        )
    return None


def _effective_defaults() -> NerBackendRuntime:
    s = get_settings()
    return NerBackendRuntime(
        llamacpp_base_url=s.HAS_LLAMACPP_BASE_URL,
    )


@router.get("", response_model=NerBackendRuntime)
async def get_ner_backend():
    """当前 NER 配置（无 json 文件时返回与环境变量一致的默认值）。"""
    rt = load_ner_runtime()
    if rt is not None:
        return rt
    return _effective_defaults()


@router.put("", response_model=NerBackendRuntime)
async def put_ner_backend(body: NerBackendRuntime):
    """保存 NER 配置（立即生效，无需重启）。"""
    _validate_base_url(body.llamacpp_base_url)
    save_ner_runtime(body)
    return body


@router.delete("")
async def delete_ner_backend():
    """删除运行时配置，恢复为环境变量 / .env 默认值。"""
    import os

    from app.core.config import get_settings
    path = os.path.join(get_settings().DATA_DIR, "ner_backend.json")
    if os.path.exists(path):
        os.remove(path)
    return {"ok": True, "message": "已清除前端覆盖，使用环境变量默认"}


@router.post("/test")
async def test_ner_backend(body: NerBackendRuntime):
    """
    连通性测试（使用请求体中的配置，无需先保存）。
    依次探测 /v1/models、models、health 等（不同 llama-server 构建路径不一）。
    """
    _validate_base_url(body.llamacpp_base_url)
    hint = _saved_vs_form_hint(body)
    try:
        ok, _probe_message, _used_url, strict = probe_llamacpp(body.llamacpp_base_url, timeout=8.0)
        if not ok:
            return {
                "success": False,
                "message": _with_hint("NER 后端连通性测试失败，请检查服务地址和进程状态。", hint),
            }
        if strict:
            ok_msg = "OpenAI 兼容接口正常"
        else:
            ok_msg = "NER 后端服务正常"
        return {"success": True, "message": _with_hint(ok_msg, hint)}
    except Exception:
        logger.warning("NER backend connectivity test failed", exc_info=True)
        return {
            "success": False,
            "message": _with_hint("NER 后端连通性测试失败，请检查服务地址和进程状态。", hint),
        }
