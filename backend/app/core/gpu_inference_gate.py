from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.core.config import settings

logger = logging.getLogger(__name__)

_SHARED_GPU_MODEL_LOCK: asyncio.Lock | None = None


def _shared_gpu_model_lock() -> asyncio.Lock:
    global _SHARED_GPU_MODEL_LOCK
    if _SHARED_GPU_MODEL_LOCK is None:
        _SHARED_GPU_MODEL_LOCK = asyncio.Lock()
    return _SHARED_GPU_MODEL_LOCK


@asynccontextmanager
async def shared_gpu_inference_slot(label: str) -> AsyncIterator[None]:
    """Serialize large local GPU model calls on single-card demo deployments."""
    if not bool(getattr(settings, "SERIALIZE_SHARED_GPU_MODELS", True)):
        yield
        return

    lock = _shared_gpu_model_lock()
    started = time.perf_counter()
    async with lock:
        waited_ms = round((time.perf_counter() - started) * 1000)
        if waited_ms > 0:
            logger.info("%s waited %dms for shared GPU inference slot", label, waited_ms)
        yield
