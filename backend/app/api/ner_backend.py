"""
文本 NER 后端（HaS / llama-server）运行时配置 API
持久化至 data/ner_backend.json，优先级高于环境变量。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.llamacpp_probe import probe_llamacpp
from app.core.ner_runtime import NerBackendRuntime, load_ner_runtime, save_ner_runtime

router = APIRouter(prefix="/ner-backend", tags=["文本NER后端"])
logger = logging.getLogger(__name__)


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
