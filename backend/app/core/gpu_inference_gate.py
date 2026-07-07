from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.config import settings

logger = logging.getLogger(__name__)

# Loop-aware configurable gate. Size 1 keeps the historical fully-serialized
# behavior for single-card deployments where every local model shares one GPU;
# multi-instance vLLM deployments raise HAS_NER_GLOBAL_MAX_INFLIGHT so the
# server-side continuous batching actually sees concurrent requests.
_GATE_SEM: asyncio.Semaphore | None = None
_GATE_LOOP: asyncio.AbstractEventLoop | None = None
_GATE_SIZE: int | None = None


def _gate_semaphore() -> asyncio.Semaphore:
    global _GATE_SEM, _GATE_LOOP, _GATE_SIZE
    loop = asyncio.get_running_loop()
    size = max(1, int(getattr(settings, "HAS_NER_GLOBAL_MAX_INFLIGHT", 1)))
    if _GATE_SEM is None or _GATE_LOOP is not loop or _GATE_SIZE != size:
        _GATE_SEM = asyncio.Semaphore(size)
        _GATE_LOOP = loop
        _GATE_SIZE = size
    return _GATE_SEM


@asynccontextmanager
async def shared_gpu_inference_slot(label: str) -> AsyncIterator[None]:
    """Bound concurrent local GPU model calls to the configured inflight size."""
    if not bool(getattr(settings, "SERIALIZE_SHARED_GPU_MODELS", True)):
        yield
        return

    sem = _gate_semaphore()
    started = time.perf_counter()
    async with sem:
        waited_ms = round((time.perf_counter() - started) * 1000)
        if waited_ms > 0:
            logger.info("%s waited %dms for shared GPU inference slot", label, waited_ms)
        yield
