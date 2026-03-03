"""
法律文件脱敏平台 - FastAPI 应用入口
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api import files, redaction, entity_types, vision_pipeline, model_config
from app.models.schemas import HealthResponse

# 创建 FastAPI 应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="智能数据脱敏平台，支持 Word/PDF/图片等多格式文档的敏感信息自动识别与脱敏处理，基于 GB/T 37964-2019 国家标准",
    docs_url="/docs",
    redoc_url="/redoc",
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 确保上传和输出目录存在
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

# 挂载静态文件目录
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")
app.mount("/outputs", StaticFiles(directory=settings.OUTPUT_DIR), name="outputs")

# 注册路由
app.include_router(files.router, prefix=settings.API_PREFIX, tags=["文件管理"])
app.include_router(redaction.router, prefix=settings.API_PREFIX, tags=["脱敏处理"])
app.include_router(entity_types.router, prefix=settings.API_PREFIX, tags=["文本识别类型管理"])
app.include_router(vision_pipeline.router, prefix=settings.API_PREFIX, tags=["图像识别Pipeline管理"])
app.include_router(model_config.router, prefix=settings.API_PREFIX, tags=["推理模型配置"])


@app.on_event("startup")
async def check_services() -> None:
    """启动时检查外部服务连通性"""
    from app.services.ocr_service import ocr_service
    if ocr_service.is_available():
        print(f"[BOOT] OCR service online ({ocr_service.get_model_name()})")
    else:
        print(f"[BOOT] OCR service offline (expected at {ocr_service.base_url})")


@app.get("/", tags=["根路径"])
async def root():
    """API 根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthResponse, tags=["健康检查"])
async def health_check():
    """健康检查接口"""
    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
    )


@app.get("/health/services", tags=["健康检查"])
async def services_health():
    """
    各模型服务的真实健康状态
    前端轮询此接口来显示服务状态
    """
    import httpx
    import asyncio
    
    services = {}
    
    def check_sync(url: str, default_name: str) -> tuple:
        """同步检查HTTP服务（在线程池中运行）"""
        try:
            with httpx.Client(timeout=3.0, trust_env=False) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    name = default_name
                    if "model" in data:
                        name = data["model"]
                    elif "data" in data and isinstance(data["data"], list) and data["data"]:
                        name = data["data"][0].get("id", default_name)
                    ready = data.get("ready", True)
                    return name, ready
        except Exception:
            pass
        return default_name, False
    
    # 在线程池中并行检查所有服务（避免阻塞事件循环）
    loop = asyncio.get_event_loop()
    ocr_result, has_result, glm_result, mcp_result = await asyncio.gather(
        loop.run_in_executor(None, check_sync, f"{settings.OCR_BASE_URL}/health", "PaddleOCR-VL-1.5"),
        loop.run_in_executor(None, check_sync, f"{settings.HAS_BASE_URL}/models", "HaS-4.0-0.6B"),
        loop.run_in_executor(None, check_sync, f"{settings.GLM_LOCAL_BASE_URL}/v1/models", "GLM-4.6V-Flash"),
        loop.run_in_executor(None, check_sync, "http://127.0.0.1:8090/health", "Image-MCP"),
    )
    
    services["paddle_ocr"] = {"name": ocr_result[0], "status": "online" if ocr_result[1] else "offline"}
    services["has_ner"] = {"name": has_result[0], "status": "online" if has_result[1] else "offline"}
    services["glm_vision"] = {"name": glm_result[0], "status": "online" if glm_result[1] else "offline"}
    services["image_mcp"] = {"name": mcp_result[0], "status": "online" if mcp_result[1] else "offline"}
    
    # 汇总（MCP 是可选的，不影响 all_online）
    core_services = {k: v for k, v in services.items() if k != "image_mcp"}
    all_online = all(s["status"] == "online" for s in core_services.values())
    
    return {
        "all_online": all_online,
        "services": services,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )

