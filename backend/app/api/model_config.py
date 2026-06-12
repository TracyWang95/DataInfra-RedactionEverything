"""Model runtime configuration API."""

from fastapi import APIRouter, HTTPException

from app.models.schemas import ModelConfig, ModelConfigList, ModelConfigPresetList, ModelTaskType
from app.services import model_config_service

router = APIRouter(prefix="/model-config", tags=["model-config"])


def _missing_config_status(message: str | None) -> int:
    normalized = str(message or "").strip().lower()
    return 404 if normalized in {"config not found", "preset not found", "not found"} else 400


@router.get("", response_model=ModelConfigList)
async def get_model_configs() -> ModelConfigList:
    """Return all configured model runtimes."""
    return model_config_service.get_configs()


@router.get("/presets", response_model=ModelConfigPresetList)
async def get_model_config_presets() -> ModelConfigPresetList:
    """Return predefined model selection presets."""
    return model_config_service.get_presets()


@router.post("/presets/{preset_id}/apply", response_model=ModelConfigList)
async def apply_model_config_preset(preset_id: str) -> ModelConfigList:
    """Apply a predefined model selection preset."""
    configs, error = model_config_service.apply_preset(preset_id)
    if configs is None:
        raise HTTPException(status_code=_missing_config_status(error), detail=error)
    return configs


@router.get("/active", response_model=ModelConfig | None)
async def get_active_config() -> ModelConfig | None:
    """Return the legacy active visual feature runtime configuration."""
    return model_config_service.get_active()


@router.get("/tasks/{task_type}/active", response_model=ModelConfig | None)
async def get_active_task_config(task_type: ModelTaskType) -> ModelConfig | None:
    """Return the active runtime configuration for a task slot."""
    return model_config_service.get_active_for_task(task_type)


@router.post("/tasks/{task_type}/active/{config_id}")
async def set_active_task_config(task_type: ModelTaskType, config_id: str) -> dict[str, str | bool]:
    """Set the active runtime configuration for a task slot."""
    success, message = model_config_service.set_active_for_task(task_type, config_id)
    if not success:
        raise HTTPException(status_code=_missing_config_status(message), detail=message)
    return {"success": True, "task_type": task_type, "active_id": config_id}


@router.post("/active/{config_id}")
async def set_active_config(config_id: str) -> dict[str, str | bool]:
    """Set the legacy active visual feature runtime configuration."""
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
    return model_config_service.get_config(config.id) or config


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
