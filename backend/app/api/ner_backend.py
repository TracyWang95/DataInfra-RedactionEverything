"""
文本 NER 后端（HaS / llama-server）运行时配置 API
持久化至 data/ner_backend.json，优先级高于环境变量。
"""
from __future__ import annotations

import httpx
from typing import Optional

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.llamacpp_probe import probe_llamacpp
from app.core.ner_runtime import NerBackendRuntime, load_ner_runtime, save_ner_runtime

router = APIRouter(prefix="/ner-backend", tags=["文本NER后端"])


def _with_hint(msg: str, hint: Optional[str]) -> str:
    return f"{msg} {hint}" if hint else msg


def _saved_vs_form_hint(body: NerBackendRuntime) -> Optional[str]:
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
    依次探测 /v1/models、/models、/health 等（不同 llama-server 构建路径不一）
    """
    hint = _saved_vs_form_hint(body)
    try:
        ok, name_or_err, used_url, strict = probe_llamacpp(body.llamacpp_base_url, timeout=8.0)
        if not ok:
            return {"success": False, "message": _with_hint(name_or_err, hint)}
        if strict:
            ok_msg = f"OpenAI 兼容接口正常 · {name_or_err}"
            if used_url:
                ok_msg += f" ({used_url})"
        else:
            ok_msg = name_or_err
            if used_url and used_url not in name_or_err:
                ok_msg += f" · {used_url}"
        return {"success": True, "message": _with_hint(ok_msg, hint)}
    except Exception as e:
        err = str(e)
        low = err.lower()
        conn_refused = "connection refused" in low or "actively refused" in low or "10061" in err
        timed_out = "timed out" in low or "timeout" in low
        if conn_refused:
            return {
                "success": False,
                "message": _with_hint(
                    (
                        "无法连接 HaS / llama-server（多为进程未启动或端口不对）。"
                        "请在本机启动 llama-server 并暴露 OpenAI 兼容 /v1，或运行项目 scripts/start_has.bat。"
                        f" 原始错误: {err}"
                    ),
                    hint,
                ),
            }
        if timed_out:
            return {
                "success": False,
                "message": _with_hint(
                    (
                        "连接 llama-server 超时。若服务已启动，可能是负载过高；否则请先启动进程再测。"
                        f" 原始错误: {err}"
                    ),
                    hint,
                ),
            }
        return {"success": False, "message": _with_hint(err, hint)}
