"""Batch job mode/file-type compatibility checks."""
from __future__ import annotations

from typing import Any

from app.models.schemas import FileType
from app.services.job_store import JobType


def normalize_batch_file_type(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def is_file_type_allowed_for_job_type(job_type: JobType | str, file_type: Any) -> bool:
    jt = str(getattr(job_type, "value", job_type) or "")
    ft = normalize_batch_file_type(file_type)
    if jt == JobType.SMART_BATCH.value:
        return True
    if jt == JobType.TEXT_BATCH.value:
        return ft != FileType.IMAGE.value
    if jt == JobType.IMAGE_BATCH.value:
        return ft in {FileType.IMAGE.value, FileType.PDF.value, FileType.PDF_SCANNED.value}
    return False


def validate_file_allowed_for_job_type(
    *,
    job_type: JobType | str,
    file_info: dict[str, Any] | None,
    file_id: str,
) -> None:
    if not file_info:
        raise ValueError(f"file not found: {file_id}")
    file_type = file_info.get("file_type")
    if is_file_type_allowed_for_job_type(job_type, file_type):
        return
    filename = file_info.get("original_filename") or file_id
    jt = str(getattr(job_type, "value", job_type) or "")
    ft = normalize_batch_file_type(file_type) or "unknown"
    raise ValueError(f"file type {ft} is not allowed for {jt}: {filename}")
