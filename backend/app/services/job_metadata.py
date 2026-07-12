"""任务/文件元数据访问与 item 序列化 — 从 job_management_service.py 提取。

标量/解析 helper、file_store 元数据安全读取、识别队列优先级、
结构化数据集元数据、config 锁定，以及 job item 输出结构组装。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from app.core.config import settings
from app.models.errors import ConflictError, NotFoundError
from app.services.job_store import JobStore, JobType

logger = logging.getLogger(__name__)


def job_type_from_str(s: str) -> JobType:
    """Parse job type string to enum. Raises ValueError on invalid input."""
    try:
        return JobType(s)
    except ValueError:
        raise ValueError(f"invalid job_type: {s}")


def job_config_dict(job_row: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = job_row.get("config_json") or "{}"
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def assert_job_owner(row: dict[str, Any] | None, owner_id: str | None) -> None:
    if not row:
        raise NotFoundError("job not found")
    if owner_id and str(row.get("owner_id") or "local_user") != owner_id:
        raise NotFoundError("job not found")


def _status_value(value: Any, *, fallback: str = "unknown") -> str:
    if isinstance(value, Enum):
        value = value.value
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


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


_FILE_STORE_RETRYABLE_MESSAGES = (
    "unable to open database file",
    "database is locked",
    "disk i/o error",
)


def _safe_file_info(file_id: str) -> tuple[dict[str, Any] | None, str | None]:
    from app.services.file_management_service import file_store

    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            info = file_store.get(file_id)
            if info is None:
                return None, "file_not_found"
            if not isinstance(info, dict):
                return None, "invalid_file_metadata"
            return info, None
        except sqlite3.OperationalError as exc:
            last_exc = exc
            msg = str(exc).lower()
            if attempt == 0 and any(token in msg for token in _FILE_STORE_RETRYABLE_MESSAGES):
                time.sleep(0.05)
                continue
            break
        except Exception as exc:
            last_exc = exc
            break

    db_path = getattr(file_store, "db_path", None)
    logger.warning(
        "job file metadata unavailable for file %s: %s; file_store_db=%s data_dir=%s cwd=%s",
        file_id,
        last_exc,
        db_path,
        settings.DATA_DIR,
        os.getcwd(),
        exc_info=True,
    )
    return None, "file_metadata_unavailable"


def _pdf_page_count_from_path(info: dict[str, Any]) -> int:
    file_path = info.get("file_path")
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
        logger.debug("unable to inspect PDF page count for recognition queue ordering", exc_info=True)
        return 0


def _recognition_priority_meta(file_info: dict[str, Any] | None) -> dict[str, int]:
    info = file_info if isinstance(file_info, dict) else {}
    ft = _file_type_value(info.get("file_type"))
    pages = _safe_int(info.get("page_count"), default=0)
    if pages <= 0 and ft in {"pdf", "pdf_scanned"}:
        pages = _pdf_page_count_from_path(info)
    pages = max(1, pages)

    if ft in {"txt", "doc", "docx"}:
        priority_class = 0
        work_units = max(1, _safe_int(info.get("file_size"), default=1) // 16_384)
    elif ft == "image":
        priority_class = 1
        work_units = 1
    elif ft in {"pdf", "pdf_scanned"}:
        priority_class = 1 if pages == 1 and not bool(info.get("is_scanned")) else 2
        work_units = pages
    else:
        priority_class = 3
        work_units = pages

    return {
        "priority_class": priority_class,
        "estimated_work_units": max(1, work_units),
        "estimated_pages": pages,
    }


def _recognition_queue_sort_key(item: dict[str, Any]) -> tuple[int, int, int]:
    info, _warning = _safe_file_info(str(item.get("file_id") or ""))
    meta = _recognition_priority_meta(info)
    return (
        int(meta["priority_class"]),
        int(meta["estimated_work_units"]),
        _safe_int(item.get("sort_order")),
    )


def _recognition_queue_meta_for_item(item: dict[str, Any]) -> dict[str, int]:
    info, _warning = _safe_file_info(str(item.get("file_id") or ""))
    return _recognition_priority_meta(info)


def _redacted_output_state(info: dict[str, Any] | None) -> tuple[bool, str | None]:
    from app.services.file_management_service import safe_path_in_dir

    if not info:
        return False, "file_not_found"
    output_path = info.get("output_path")
    if not isinstance(output_path, str) or not output_path.strip():
        return False, "missing_redacted_output"
    if not safe_path_in_dir(output_path, settings.OUTPUT_DIR):
        return False, "unsafe_path"
    if not os.path.isfile(output_path):
        return False, "missing_redacted_output"
    return True, None


def _safe_entity_count(info: dict[str, Any] | None) -> int:
    if not info:
        return 0
    try:
        from app.services.file_management_service import entity_count

        return _safe_int(entity_count(info))
    except Exception:
        logger.warning("job file entity count unavailable", exc_info=True)
        return 0


def _is_structured_job(row_or_type: dict[str, Any] | str | None) -> bool:
    if isinstance(row_or_type, dict):
        row_or_type = row_or_type.get("job_type")
    return str(row_or_type or "") == JobType.STRUCTURED_BATCH.value


def _structured_file_meta(
    file_id: str,
    *,
    owner_id: str | None,
    job_id: str | None = None,
) -> dict[str, Any] | None:
    if not owner_id:
        return None
    try:
        from app.services.structured_service import structured_item_meta
        from app.services.structured_store import get_structured_store

        meta = structured_item_meta(file_id, owner_id=owner_id)
        if not meta:
            return None
        if job_id:
            exports = get_structured_store().list_exports(owner_id=owner_id, job_id=job_id)
            meta["has_output"] = any(str(export.get("dataset_id")) == file_id for export in exports)
        return meta
    except Exception:
        logger.warning("structured dataset metadata unavailable for dataset %s", file_id, exc_info=True)
        return None


def lock_job_config(store: JobStore, job_id: str, row: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist immutable config metadata before a job leaves draft state."""
    current_row = row or store.get_job(job_id)
    if not current_row:
        raise NotFoundError("job not found")
    cfg = job_config_dict(current_row)
    if cfg.get("config_locked_at"):
        return cfg
    current_version = cfg.get("config_version")
    try:
        next_version = int(current_version) if current_version is not None else 1
    except (TypeError, ValueError):
        next_version = 1
    if next_version < 1:
        next_version = 1
    cfg["config_version"] = next_version
    cfg["config_locked_at"] = datetime.now(UTC).isoformat()
    if not store.update_job_draft(job_id, {"config": cfg}):
        raise ConflictError("job config is locked")
    store.touch_job_updated(job_id)
    return cfg


def file_meta_for_item(
    file_id: str,
    *,
    owner_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Get file metadata for a job item."""
    info, _ = _safe_file_info(file_id)
    if not info:
        structured_meta = _structured_file_meta(file_id, owner_id=owner_id, job_id=job_id)
        if structured_meta:
            return structured_meta
        return {
            "filename": None,
            "file_type": None,
            "has_output": False,
            "entity_count": 0,
        }

    raw_file_type = info.get("file_type")
    file_type = getattr(raw_file_type, "value", raw_file_type)
    has_output, _ = _redacted_output_state(info)
    return {
        "filename": info.get("original_filename"),
        "file_type": _status_value(file_type, fallback=""),
        "has_output": has_output,
        "entity_count": _safe_entity_count(info),
    }


def item_to_out(row: dict[str, Any], *, owner_id: str | None = None, job_id: str | None = None) -> dict[str, Any]:
    """Convert a job item row to output dict with file metadata."""
    file_meta = file_meta_for_item(str(row["file_id"]), owner_id=owner_id, job_id=job_id or str(row["job_id"]))
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "file_id": row["file_id"],
        "sort_order": _safe_int(row.get("sort_order")),
        "status": _status_value(row.get("status")),
        "error_message": row.get("error_message"),
        "reviewed_at": row.get("reviewed_at"),
        "reviewer": row.get("reviewer"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "filename": file_meta["filename"],
        "file_type": file_meta["file_type"],
        "has_output": file_meta["has_output"],
        "entity_count": file_meta["entity_count"],
        "has_review_draft": bool(row.get("review_draft_json")),
        "review_draft_updated_at": row.get("review_draft_updated_at"),
        "progress_stage": row.get("progress_stage"),
        "progress_current": _safe_int(row.get("progress_current")),
        "progress_total": _safe_int(row.get("progress_total")),
        "progress_message": row.get("progress_message"),
        "progress_updated_at": row.get("progress_updated_at"),
    }
