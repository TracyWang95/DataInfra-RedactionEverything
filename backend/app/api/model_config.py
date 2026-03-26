"""
推理模型配置 API（视觉：HaS Image 8081 微服务；与文本 NER 分离）
"""
import os
import json
from typing import Optional, Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter(prefix="/model-config", tags=["model-config"])

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "model_config.json")


class ModelConfig(BaseModel):
    """模型配置"""
    id: str = Field(..., description="配置ID")
    name: str = Field(..., description="配置名称")
    provider: Literal["local", "zhipu", "openai", "custom"] = Field(..., description="提供商类型")
    enabled: bool = Field(default=True, description="是否启用")
    
    # API 配置
    base_url: Optional[str] = Field(None, description="API 基础 URL（本地/自定义）")
    api_key: Optional[str] = Field(None, description="API Key（云端服务）")
    model_name: str = Field(..., description="模型名称")
    
    # 生成参数
    temperature: float = Field(default=0.8, ge=0, le=2)
    top_p: float = Field(default=0.6, ge=0, le=1)
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    
    enable_thinking: bool = Field(default=False, description="保留字段")
    
    # 备注
    description: Optional[str] = Field(None, description="配置说明")


class ModelConfigList(BaseModel):
    """模型配置列表"""
    configs: list[ModelConfig]
    active_id: Optional[str] = Field(None, description="当前激活的配置ID")


# 默认配置（PaddleOCR-VL 与 HaS Image 同级；与左侧栏服务状态一致）
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

# 内置视觉后端，禁止删除（与 DEFAULT_CONFIGS 中 id 一致）
VISION_BUILTIN_IDS = frozenset({"paddle_ocr_service", "has_image_service"})

# 旧版「视觉模型配置」中的 GLM / 8081 llama 条目，加载时剔除并写回磁盘
_LEGACY_VISION_IDS = frozenset({"local_glm", "zhipu_glm4v", "zhipu_glm"})


def _sanitize_model_config_list(raw: ModelConfigList) -> tuple[ModelConfigList, bool]:
    kept = [
        c
        for c in raw.configs
        if c.id not in _LEGACY_VISION_IDS and c.provider != "zhipu"
    ]
    changed = len(kept) != len(raw.configs)
    # 合并：按 DEFAULT_CONFIGS 顺序补齐内置项，再附加用户自定义条目
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
    # 内置视觉后端始终启用（与侧栏服务并行，不可被误关）
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


def load_configs() -> ModelConfigList:
    """加载配置；自动迁移并移除已废弃的 GLM 视觉配置项"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            lst = ModelConfigList(**data)
            lst, changed = _sanitize_model_config_list(lst)
            if changed:
                save_configs(lst)
                print("[ModelConfig] 已迁移：移除旧版 GLM 视觉配置，保留 HaS Image 等条目")
            return lst
        except Exception as e:
            print(f"[ModelConfig] 加载配置失败: {e}")
    return DEFAULT_CONFIGS.model_copy(deep=True)


def save_configs(configs: ModelConfigList):
    """保存配置"""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(configs.model_dump(), f, ensure_ascii=False, indent=2)


@router.get("", response_model=ModelConfigList)
async def get_model_configs():
    """获取所有模型配置"""
    return load_configs()


@router.get("/active", response_model=Optional[ModelConfig])
async def get_active_config():
    """获取当前激活的模型配置"""
    configs = load_configs()
    if configs.active_id:
        for cfg in configs.configs:
            if cfg.id == configs.active_id and cfg.enabled:
                return cfg
    # 返回第一个启用的配置
    for cfg in configs.configs:
        if cfg.enabled:
            return cfg
    return None


@router.post("/active/{config_id}")
async def set_active_config(config_id: str):
    """设置激活的模型配置"""
    configs = load_configs()
    found = False
    for cfg in configs.configs:
        if cfg.id == config_id:
            if not cfg.enabled:
                raise HTTPException(status_code=400, detail="该配置未启用")
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="配置不存在")
    
    configs.active_id = config_id
    save_configs(configs)
    return {"success": True, "active_id": config_id}


@router.post("", response_model=ModelConfig)
async def create_model_config(config: ModelConfig):
    """创建新的模型配置"""
    configs = load_configs()
    
    # 检查 ID 是否重复
    for cfg in configs.configs:
        if cfg.id == config.id:
            raise HTTPException(status_code=400, detail="配置ID已存在")
    
    configs.configs.append(config)
    save_configs(configs)
    return config


@router.put("/{config_id}", response_model=ModelConfig)
async def update_model_config(config_id: str, config: ModelConfig):
    """更新模型配置"""
    configs = load_configs()

    if config_id in VISION_BUILTIN_IDS:
        config.enabled = True

    for i, cfg in enumerate(configs.configs):
        if cfg.id == config_id:
            config.id = config_id  # 保持 ID 不变
            configs.configs[i] = config
            save_configs(configs)
            return config
    
    raise HTTPException(status_code=404, detail="配置不存在")


@router.delete("/{config_id}")
async def delete_model_config(config_id: str):
    """删除模型配置"""
    configs = load_configs()

    if config_id in VISION_BUILTIN_IDS:
        raise HTTPException(status_code=400, detail="内置视觉后端（PaddleOCR-VL / HaS Image）不可删除")

    # 不允许删除最后一个配置
    if len(configs.configs) <= 1:
        raise HTTPException(status_code=400, detail="至少保留一个配置")
    
    for i, cfg in enumerate(configs.configs):
        if cfg.id == config_id:
            configs.configs.pop(i)
            # 如果删除的是激活配置，切换到第一个启用的配置
            if configs.active_id == config_id:
                configs.active_id = None
                for c in configs.configs:
                    if c.enabled:
                        configs.active_id = c.id
                        break
            save_configs(configs)
            return {"success": True}
    
    raise HTTPException(status_code=404, detail="配置不存在")


@router.post("/reset")
async def reset_model_configs():
    """重置为默认配置"""
    save_configs(DEFAULT_CONFIGS.model_copy(deep=True))
    return {"success": True}


async def _probe_paddle_ocr_health(base_override: Optional[str] = None) -> dict:
    """
    探测 PaddleOCR-VL：GET /health，检查 ready。
    base_override：推理后端列表中的基址；缺省用 settings.OCR_BASE_URL。
    """
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


@router.post("/test/paddle-ocr")
async def test_paddle_ocr_service():
    """与推理后端列表中 PaddleOCR-VL 条目的「测试」同源。"""
    return await _probe_paddle_ocr_health(None)


@router.post("/test/{config_id}")
async def test_model_config(config_id: str):
    """测试模型配置连通性"""
    configs = load_configs()
    
    config = None
    for cfg in configs.configs:
        if cfg.id == config_id:
            config = cfg
            break
    
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")

    if config.id == "paddle_ocr_service":
        base = (config.base_url or settings.OCR_BASE_URL).rstrip("/")
        return await _probe_paddle_ocr_health(base)

    try:
        if config.provider == "local":
            # HaS Image / 其他本地 HTTP：探测 /health
            import httpx
            base = (config.base_url or "").rstrip("/")
            if not base:
                return {"success": False, "message": "未配置 base_url"}
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                resp = await client.get(f"{base}/health")
                if resp.status_code == 200:
                    try:
                        j = resp.json()
                        if j.get("status") == "unavailable" or j.get("ready") is False:
                            return {
                                "success": False,
                                "message": "服务已响应但模型未就绪（检查 HAS_IMAGE_WEIGHTS 权重路径）",
                            }
                    except Exception:
                        pass
                    return {"success": True, "message": "本地 HTTP 服务连接成功"}
                return {"success": False, "message": f"服务返回状态码: {resp.status_code}"}
        
        elif config.provider == "zhipu":
            # 测试智谱 API
            if not config.api_key:
                return {"success": False, "message": "请先配置 API Key"}
            
            from zhipuai import ZhipuAI
            client = ZhipuAI(api_key=config.api_key)
            # 简单测试：获取模型列表
            response = client.chat.completions.create(
                model=config.model_name,
                messages=[{"role": "user", "content": "你好"}],
                max_tokens=10
            )
            return {"success": True, "message": "智谱 API 连接成功"}
        
        elif config.provider in ["openai", "custom"]:
            # 测试 OpenAI 兼容接口
            import httpx
            headers = {}
            if config.api_key:
                headers["Authorization"] = f"Bearer {config.api_key}"
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{config.base_url}/v1/models", headers=headers)
                if resp.status_code == 200:
                    return {"success": True, "message": "API 连接成功"}
                else:
                    return {"success": False, "message": f"API 返回状态码: {resp.status_code}"}
        
        return {"success": False, "message": "未知的提供商类型"}
    
    except Exception as e:
        return {"success": False, "message": str(e)}
