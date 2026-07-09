"""task_queue 的并发配额配置：区间夹紧 + runtime_settings.json 持久化。

从 task_queue.py 拆出。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.services.task_queue_metrics import _safe_int

logger = logging.getLogger(__name__)


_MIN_JOB_CONCURRENCY = 1
_MAX_JOB_CONCURRENCY = 16


def _clamp_job_concurrency(value: Any) -> int:
    return max(_MIN_JOB_CONCURRENCY, min(_MAX_JOB_CONCURRENCY, _safe_int(value, default=3)))


def _runtime_settings_path() -> str:
    from app.core.config import settings

    return os.path.join(settings.DATA_DIR, "runtime_settings.json")


def load_persisted_job_concurrency(default: int) -> int:
    try:
        from app.core.persistence import load_json

        data = load_json(_runtime_settings_path(), default={}) or {}
        if isinstance(data, dict) and "job_concurrency" in data:
            return _clamp_job_concurrency(data.get("job_concurrency"))
    except Exception:
        logger.warning("Unable to load persisted job concurrency", exc_info=True)
    return _clamp_job_concurrency(default)


def save_persisted_job_concurrency(value: int) -> int:
    next_value = _clamp_job_concurrency(value)
    try:
        from app.core.persistence import load_json, save_json

        path = _runtime_settings_path()
        data = load_json(path, default={}) or {}
        if not isinstance(data, dict):
            data = {}
        data["job_concurrency"] = next_value
        save_json(path, data)
    except Exception:
        logger.warning("Unable to persist job concurrency", exc_info=True)
    return next_value
