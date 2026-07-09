"""task_queue 的纯函数辅助：调度成本估算 + GPU/视觉质量指标 + 时间原语。

从 task_queue.py 拆出。全部无状态、无副作用（仅函数内部延迟 import
settings/fitz/gpu_memory），因此可安全独立于队列对象存在。
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


# GPU memory ratio at/above which the queue treats the device as saturated.
# Fallback default; the effective value comes from settings.GPU_SATURATION_RATIO
# (multi-service cards with high static residency need a higher threshold).
_GPU_SATURATION_RATIO = 0.90


def _gpu_saturation_ratio() -> float:
    try:
        from app.core.config import settings

        return float(settings.GPU_SATURATION_RATIO)
    except Exception:
        return _GPU_SATURATION_RATIO
# File-size bucket (bytes) used to order small-vs-large files in the queue.
_FILE_SIZE_BUCKET_BYTES = 16_384


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((time.perf_counter() - started) * 1000)))


def _safe_int(value: Any, *, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _file_type_value(value: Any) -> str:
    value = getattr(value, "value", value)
    return str(value or "").strip().lower()


def _pdf_page_count_from_path(file_info: dict[str, Any]) -> int:
    file_path = file_info.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        return 0
    try:
        import fitz

        doc = fitz.open(file_path)
        try:
            return max(0, int(len(doc)))
        finally:
            doc.close()
    except Exception:
        logger.debug("unable to inspect PDF page count for queue priority", exc_info=True)
        return 0


def _estimate_recognition_task_cost(file_info: dict[str, Any]) -> tuple[int, int]:
    """Return coarse (priority class, work units) for shortest-visible-result scheduling."""
    ft = _file_type_value(file_info.get("file_type"))
    pages = _safe_int(file_info.get("page_count"), default=0)
    if pages <= 0 and ft in {"pdf", "pdf_scanned"}:
        pages = _pdf_page_count_from_path(file_info)
    pages = max(1, pages)

    if ft in {"txt", "doc", "docx"}:
        return (0, max(1, _safe_int(file_info.get("file_size"), default=1) // _FILE_SIZE_BUCKET_BYTES))
    if ft == "image":
        return (1, 1)
    if ft in {"pdf", "pdf_scanned"}:
        priority_class = 1 if pages == 1 and not bool(file_info.get("is_scanned")) else 2
        return (priority_class, pages)
    return (3, pages)


def _gpu_memory_ratio(gpu_memory: dict[str, Any] | None) -> float | None:
    if not isinstance(gpu_memory, dict):
        return None
    total_mb = _safe_int(gpu_memory.get("total_mb"), default=0)
    if total_mb <= 0:
        return None
    used_mb = max(0, _safe_int(gpu_memory.get("used_mb"), default=0))
    return max(0.0, min(1.0, used_mb / total_mb))


def _effective_vision_page_concurrency(
    file_info: dict[str, Any],
    pages: int,
    configured: int,
    *,
    gpu_memory: dict[str, Any] | None = None,
) -> int:
    """Return per-file page concurrency for vision recognition.

    Keep the runtime value explicit. Multi-page scanned PDFs are mostly gated
    by the process-wide HaS Text NER slot, so silently increasing concurrency
    can make page latency worse on laptop GPUs. Operators can still raise the
    configured value after measuring their own hardware.
    """
    pages = max(1, int(pages))
    configured = max(1, int(configured))
    gpu_ratio = _gpu_memory_ratio(gpu_memory)
    if gpu_ratio is not None and gpu_ratio >= _gpu_saturation_ratio():
        return 1
    return min(configured, pages)


def _vision_page_concurrency_reason(
    pages: int,
    configured: int,
    effective: int,
    gpu_memory: dict[str, Any] | None,
) -> str:
    gpu_ratio = _gpu_memory_ratio(gpu_memory)
    if effective == 1 and gpu_ratio is not None and gpu_ratio >= _gpu_saturation_ratio():
        return "gpu_memory_high"
    if effective < max(1, int(configured)):
        return "page_count"
    return "configured"


def _gpu_memory_metadata(gpu_memory: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(gpu_memory, dict):
        return {"available": False}
    ratio = _gpu_memory_ratio(gpu_memory)
    meta: dict[str, Any] = {
        "available": ratio is not None,
        "used_mb": _safe_int(gpu_memory.get("used_mb"), default=0),
        "total_mb": _safe_int(gpu_memory.get("total_mb"), default=0),
    }
    if ratio is not None:
        meta["used_ratio"] = round(ratio, 4)
    return meta


def _object_field(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def _page_vision_quality_from_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    return {
        "duration_ms": dict(_object_field(result, "duration_ms", {}) or {}),
        "cache_status": dict(_object_field(result, "cache_status", {}) or {}),
        "pipeline_status": dict(_object_field(result, "pipeline_status", {}) or {}),
        "warnings": list(_object_field(result, "warnings", []) or []),
    }


def _page_vision_quality_from_file_info(file_info: dict[str, Any], page: int) -> dict[str, Any]:
    quality_by_page = file_info.get("vision_quality") if isinstance(file_info, dict) else {}
    quality = {}
    if isinstance(quality_by_page, dict):
        quality = quality_by_page.get(page) or quality_by_page.get(str(page)) or {}
    return quality if isinstance(quality, dict) else {}


def _duration_breakdown_from_quality(quality: dict[str, Any]) -> dict[str, Any]:
    """Expose per-pipeline stage timings/status alongside top-level durations."""
    breakdown = dict(quality.get("duration_ms") or {})
    pipeline_status = quality.get("pipeline_status") or {}
    if not isinstance(pipeline_status, dict):
        return breakdown

    for pipeline_name, status in pipeline_status.items():
        if not isinstance(status, dict):
            continue
        stage_status = status.get("stage_duration_ms") or {}
        if not isinstance(stage_status, dict):
            continue
        prefix = str(pipeline_name or "pipeline")
        for key, value in stage_status.items():
            breakdown[f"{prefix}.{key}"] = value
    return breakdown
