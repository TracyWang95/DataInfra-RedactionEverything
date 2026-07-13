"""Model runtime configuration API."""

from fastapi import APIRouter, HTTPException

from app.models.schemas import ModelConfig, ModelConfigList
from app.services import model_config_service

router = APIRouter(prefix="/model-config", tags=["model-config"])


def _missing_config_status(message: str | None) -> int:
    return 404 if message in {"配置不存在", "config not found", "not found"} else 400


@router.get("", response_model=ModelConfigList)
async def get_model_configs() -> ModelConfigList:
    """Return all configured model runtimes."""
    return model_config_service.get_configs()


@router.get("/active", response_model=ModelConfig | None)
async def get_active_config() -> ModelConfig | None:
    """Return the active model runtime configuration."""
    return model_config_service.get_active()


@router.post("/active/{config_id}")
async def set_active_config(config_id: str) -> dict[str, str | bool]:
    """Set the active model runtime configuration."""
    success, message = model_config_service.set_active(config_id)
    if not success:
        raise HTTPException(status_code=_missing_config_status(message), detail=message)
    return {"success": True, "active_id": config_id}


@router.post("", response_model=ModelConfig)
async def create_model_config(config: ModelConfig) -> ModelConfig:
    """Create a model runtime configuration."""
    success, error = model_config_service.create_config(config)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return config


@router.put("/{config_id}", response_model=ModelConfig)
async def update_model_config(config_id: str, config: ModelConfig) -> ModelConfig:
    """Update a model runtime configuration."""
    updated, error = model_config_service.update_config(config_id, config)
    if updated is None:
        raise HTTPException(status_code=_missing_config_status(error), detail=error)
    return updated


@router.delete("/{config_id}")
async def delete_model_config(config_id: str) -> dict[str, bool]:
    """Delete a model runtime configuration."""
    success, error = model_config_service.delete_config(config_id)
    if not success:
        raise HTTPException(status_code=_missing_config_status(error), detail=error)
    return {"success": True}


@router.post("/reset")
async def reset_model_configs() -> dict[str, bool]:
    """Reset model runtime configuration to defaults."""
    model_config_service.reset_configs()
    return {"success": True}


@router.post("/test/paddle-ocr")
async def test_paddle_ocr_service() -> dict:
    """Test the PaddleOCR-VL runtime."""
    return await model_config_service.test_paddle_ocr()


@router.post("/test/{config_id}")
async def test_model_config(config_id: str) -> dict:
    """Test a configured model runtime."""
    result, error = await model_config_service.test_config(config_id)
    if result is None:
        raise HTTPException(status_code=_missing_config_status(error), detail=error)
    return result
