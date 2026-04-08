"""
推理模型配置 — 业务逻辑层
（视觉：HaS Image 8081 微服务；与文本 NER 分离）
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings
from app.core.persistence import load_json, save_json
from app.models.schemas import ModelConfig, ModelConfigList

logger = logging.getLogger(__name__)


# ── 默认 / 内置常量 ──────────────────────────────────────

DEFAULT_CONFIGS = ModelConfigList(
    configs=[
        ModelConfig(
            id="paddle_ocr_service",
            name="PaddleOCR-VL 微服务 (8082)",
            provider="local",
            enabled=True,
            base_url="http://127.0.0.1:8082",
            model_name="PaddleOCR-VL-1.5",
            temperature=0.8,
            top_p=0.6,
            max_tokens=4096,
            enable_thinking=False,
            description="PaddleOCR-VL OCR；基址与后端环境变量 OCR_BASE_URL 一致",
        ),
        ModelConfig(
            id="has_image_service",
            name="HaS Image 微服务 (8081)",
            provider="local",
            enabled=True,
            base_url="http://127.0.0.1:8081",
            model_name="HaS-Image-YOLO11",
            temperature=0.8,
            top_p=0.6,
            max_tokens=4096,
            enable_thinking=False,
            description="Ultralytics YOLO11 实例分割；权重由环境变量 HAS_IMAGE_WEIGHTS 指定",
        ),
    ],
    active_id="has_image_service",
)

# 内置视觉后端，禁止删除
VISION_BUILTIN_IDS = frozenset({"paddle_ocr_service", "has_image_service"})

# 旧版条目，加载时剔除
_LEGACY_VISION_IDS = frozenset({"local_glm", "zhipu_glm4v", "zhipu_glm"})


# ── 内部工具 ─────────────────────────────────────────────

def _sanitize_model_config_list(raw: ModelConfigList) -> tuple[ModelConfigList, bool]:
    kept = [
        c
        for c in raw.configs
        if c.id not in _LEGACY_VISION_IDS and c.provider != "zhipu"
    ]
    changed = len(kept) != len(raw.configs)
    seen: set[str] = set()
    merged: list[ModelConfig] = []
    for d in DEFAULT_CONFIGS.configs:
        match = next((c for c in kept if c.id == d.id), None)
        if match:
            merged.append(match)
            seen.add(match.id)
        else:
            merged.append(d.model_copy(deep=True))
            changed = True
    for c in kept:
        if c.id not in seen:
            merged.append(c)
            seen.add(c.id)
    final_merged: list[ModelConfig] = []
    for c in merged:
        if c.id in VISION_BUILTIN_IDS and not c.enabled:
            final_merged.append(c.model_copy(update={"enabled": True}))
            changed = True
        else:
            final_merged.append(c)
    valid_ids = {c.id for c in final_merged}
    active = raw.active_id if raw.active_id in valid_ids else None
    if active is None:
        active = "has_image_service"
        changed = True
    out = ModelConfigList(configs=final_merged, active_id=active)
    return out, changed


# ── 持久化 ────────────────────────────────────────────────

def load_configs() -> ModelConfigList:
    """加载配置；自动迁移并移除已废弃的 GLM 视觉配置项"""
    raw = load_json(settings.MODEL_CONFIG_PATH, default=None)
    if raw is not None:
        try:
            lst = ModelConfigList(**raw)
            lst, changed = _sanitize_model_config_list(lst)
            if changed:
                save_configs(lst)
                logger.info("ModelConfig 已迁移：移除旧版 GLM 视觉配置，保留 HaS Image 等条目")
            return lst
        except Exception as e:
            logger.error("ModelConfig 加载配置失败: %s", e)
    return DEFAULT_CONFIGS.model_copy(deep=True)


def save_configs(configs: ModelConfigList) -> None:
    """保存配置"""
    save_json(settings.MODEL_CONFIG_PATH, configs)


# ── 业务方法 ──────────────────────────────────────────────

def get_configs() -> ModelConfigList:
    return load_configs()


def get_active() -> Optional[ModelConfig]:
    configs = load_configs()
    if configs.active_id:
        for cfg in configs.configs:
            if cfg.id == configs.active_id and cfg.enabled:
                return cfg
    for cfg in configs.configs:
        if cfg.enabled:
            return cfg
    return None


def set_active(config_id: str) -> tuple[bool, str]:
    """Returns (success, error_or_active_id)."""
    configs = load_configs()
    found = False
    for cfg in configs.configs:
        if cfg.id == config_id:
            if not cfg.enabled:
                return False, "该配置未启用"
            found = True
            break
    if not found:
        return False, "配置不存在"
    configs.active_id = config_id
    save_configs(configs)
    return True, config_id


def create_config(config: ModelConfig) -> tuple[bool, str]:
    """Returns (success, error_message)."""
    configs = load_configs()
    for cfg in configs.configs:
        if cfg.id == config.id:
            return False, "配置ID已存在"
    configs.configs.append(config)
    save_configs(configs)
    return True, ""


def update_config(config_id: str, config: ModelConfig) -> tuple[ModelConfig | None, str]:
    """Returns (updated_config_or_None, error_message)."""
    configs = load_configs()
    if config_id in VISION_BUILTIN_IDS:
        config.enabled = True
    for i, cfg in enumerate(configs.configs):
        if cfg.id == config_id:
            config.id = config_id
            configs.configs[i] = config
            save_configs(configs)
            return config, ""
    return None, "配置不存在"


def delete_config(config_id: str) -> tuple[bool, str]:
    """Returns (success, error_message)."""
    configs = load_configs()
    if config_id in VISION_BUILTIN_IDS:
        return False, "内置视觉后端（PaddleOCR-VL / HaS Image）不可删除"
    if len(configs.configs) <= 1:
        return False, "至少保留一个配置"
    for i, cfg in enumerate(configs.configs):
        if cfg.id == config_id:
            configs.configs.pop(i)
            if configs.active_id == config_id:
                configs.active_id = None
                for c in configs.configs:
                    if c.enabled:
                        configs.active_id = c.id
                        break
            save_configs(configs)
            return True, ""
    return False, "配置不存在"


def reset_configs() -> None:
    save_configs(DEFAULT_CONFIGS.model_copy(deep=True))


# ── 健康探测 ──────────────────────────────────────────────

async def _probe_paddle_ocr_health(base_override: Optional[str] = None) -> dict:
    """探测 PaddleOCR-VL：GET /health，检查 ready。"""
    import httpx

    base = (base_override or settings.OCR_BASE_URL).rstrip("/")
    timeout = float(getattr(settings, "OCR_HEALTH_PROBE_TIMEOUT", 45.0))
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.get(f"{base}/health")
    except Exception as e:
        return {
            "success": False,
            "message": f"无法连接 OCR 服务 ({base}): {e}",
            "base_url": base,
        }

    if resp.status_code != 200:
        return {
            "success": False,
            "message": f"OCR /health 返回 HTTP {resp.status_code}",
            "base_url": base,
        }

    try:
        j = resp.json()
    except Exception:
        return {"success": True, "message": f"OCR 已响应（{base}），但返回非 JSON", "base_url": base}

    model = j.get("model", "PaddleOCR-VL")
    ready = bool(j.get("ready", False))
    device = j.get("device", "")
    st = j.get("status", "")

    if not ready:
        return {
            "success": False,
            "message": f"{model} 已连接但未就绪（ready=false，可能仍在加载模型）",
            "base_url": base,
            "detail": {"model": model, "status": st, "device": device, "ready": ready},
        }

    extra = f"，设备 {device}" if device else ""
    return {
        "success": True,
        "message": f"{model} 在线且就绪{extra}",
        "base_url": base,
        "detail": {"model": model, "status": st, "device": device, "ready": ready},
    }


async def test_paddle_ocr() -> dict:
    """与推理后端列表中 PaddleOCR-VL 条目的「测试」同源。"""
    return await _probe_paddle_ocr_health(None)


async def test_config(config_id: str) -> tuple[dict | None, str]:
    """Returns (result_dict_or_None, error_message). None means config not found."""
    configs = load_configs()

    config = None
    for cfg in configs.configs:
        if cfg.id == config_id:
            config = cfg
            break

    if not config:
        return None, "配置不存在"

    if config.id == "paddle_ocr_service":
        base = (config.base_url or settings.OCR_BASE_URL).rstrip("/")
        return await _probe_paddle_ocr_health(base), ""

    try:
        if config.provider == "local":
            import httpx
            base = (config.base_url or "").rstrip("/")
            if not base:
                return {"success": False, "message": "未配置 base_url"}, ""
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                resp = await client.get(f"{base}/health")
                if resp.status_code == 200:
                    try:
                        j = resp.json()
                        if j.get("status") == "unavailable" or j.get("ready") is False:
                            return {
                                "success": False,
                                "message": "服务已响应但模型未就绪（检查 HAS_IMAGE_WEIGHTS 权重路径）",
                            }, ""
                    except Exception:
                        pass
                    return {"success": True, "message": "本地 HTTP 服务连接成功"}, ""
                return {"success": False, "message": f"服务返回状态码: {resp.status_code}"}, ""

        elif config.provider == "zhipu":
            if not config.api_key:
                return {"success": False, "message": "请先配置 API Key"}, ""
            from zhipuai import ZhipuAI
            client = ZhipuAI(api_key=config.api_key)
            response = client.chat.completions.create(
                model=config.model_name,
                messages=[{"role": "user", "content": "你好"}],
                max_tokens=10,
            )
            return {"success": True, "message": "智谱 API 连接成功"}, ""

        elif config.provider in ["openai", "custom"]:
            import httpx
            headers = {}
            if config.api_key:
                headers["Authorization"] = f"Bearer {config.api_key}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{config.base_url}/v1/models", headers=headers)
                if resp.status_code == 200:
                    return {"success": True, "message": "API 连接成功"}, ""
                else:
                    return {"success": False, "message": f"API 返回状态码: {resp.status_code}"}, ""

        return {"success": False, "message": "未知的提供商类型"}, ""

    except Exception as e:
        return {"success": False, "message": str(e)}, ""
