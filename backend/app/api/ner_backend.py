"""
文本 NER 后端（HaS / llama-server）运行时配置 API
持久化至 data/ner_backend.json，优先级高于环境变量。
兼容字段仍接受 ollama 相关键名，前端仅暴露 HaS。
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
    if rt.backend != body.backend:
        return (
            "【说明】侧栏「HaS」状态依据**已保存**的配置；您当前表单所选后端与已保存不一致，"
            "请先点「保存配置」或改回与侧栏一致后再测。"
        )
    if body.backend == "llamacpp":
        if rt.llamacpp_base_url.rstrip("/") != body.llamacpp_base_url.rstrip("/"):
            return (
                "【说明】侧栏依据已保存的 API 地址；当前输入框地址与已保存不同，测试结果以输入框为准。"
            )
    if body.backend == "ollama":
        if rt.ollama_base_url.rstrip("/") != body.ollama_base_url.rstrip("/") or (
            (rt.ollama_model or "").strip() != (body.ollama_model or "").strip()
        ):
            return "【说明】侧栏依据已保存的 Ollama 配置；当前表单与已保存不一致时，两侧结果可能不同。"
    return None


def _effective_defaults() -> NerBackendRuntime:
    s = get_settings()
    return NerBackendRuntime(
        backend=s.HAS_NER_BACKEND,
        llamacpp_base_url=s.HAS_LLAMACPP_BASE_URL,
        ollama_base_url=s.HAS_OLLAMA_BASE_URL,
        ollama_model=s.HAS_OLLAMA_MODEL,
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
    - llamacpp: 依次探测 /v1/models、/models、/health 等（不同 llama-server 构建路径不一）
    - ollama: GET {root}/api/tags，并检查模型名是否在列表中
    """
    hint = _saved_vs_form_hint(body)
    try:
        if body.backend == "ollama":
            chat = body.ollama_base_url.rstrip("/")
            root = chat.replace("/v1", "").rstrip("/") or "http://127.0.0.1:11434"
            url = f"{root}/api/tags"
            with httpx.Client(timeout=8.0, trust_env=False) as client:
                r = client.get(url)
            if r.status_code != 200:
                return {"success": False, "message": _with_hint(f"Ollama 不可达: HTTP {r.status_code} ({url})", hint)}
            data = r.json()
            names: list[str] = []
            for m in data.get("models", []) or []:
                if isinstance(m, dict) and m.get("name"):
                    names.append(m["name"])
            model = (body.ollama_model or "").strip()
            if model and names and model not in names:
                preview = ", ".join(names[:5]) + ("…" if len(names) > 5 else "")
                return {
                    "success": False,
                    "message": _with_hint(
                        f"未找到模型「{model}」。已安装示例: {preview or '(无)'}",
                        hint,
                    ),
                }
            if model:
                return {
                    "success": True,
                    "message": _with_hint(f"Ollama 在线，模型「{model}」可用 ({url})", hint),
                }
            return {"success": True, "message": _with_hint(f"Ollama 在线 ({url})", hint)}

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
        if body.backend == "llamacpp" and conn_refused:
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
        if body.backend == "llamacpp" and timed_out:
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
        if body.backend == "ollama" and (conn_refused or timed_out):
            return {
                "success": False,
                "message": _with_hint(
                    (
                        "无法连接 Ollama（请确认已运行 `ollama serve` 且地址/端口正确）。 "
                        f"原始错误: {err}"
                    ),
                    hint,
                ),
            }
        return {"success": False, "message": _with_hint(err, hint)}
