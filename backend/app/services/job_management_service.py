# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
任务管理业务逻辑服务层 — 从 api/jobs.py 提取。

Job 状态推导、进度计算、导航提示、文件元数据收集、
向导状态管理、RedactionConfig 构建、队列投递、审核逻辑等。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from app.core.config import settings
from app.core.persistence import to_jsonable
from app.models.schemas import (
    BoundingBox,
    RedactionConfig,
)
from app.services.job_store import (
    InvalidStatusTransition,
    JobItemStatus,
    JobStatus,
    JobStore,
    JobType,
)
from app.services.wizard_furthest import coerce_wizard_furthest_step, infer_batch_step1_configured

logger = logging.getLogger(__name__)

DELETABLE_JOB_STATUSES = frozenset(
    {
        JobStatus.DRAFT.value,
        JobStatus.AWAITING_REVIEW.value,
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }
)

UPDATABLE_JOB_STATUSES = frozenset(
    {
        JobStatus.DRAFT.value,
        JobStatus.QUEUED.value,
        JobStatus.RUNNING.value,
        JobStatus.AWAITING_REVIEW.value,
    }
)


# ---------------------------------------------------------------------------
# Job status inference
# ---------------------------------------------------------------------------

def refresh_job_status(store: JobStore, job_id: str) -> None:
    """从 item 状态推导 job 状态（简化版）。"""
    job = store.get_job(job_id)
    if not job or job["status"] == JobStatus.CANCELLED.value:
        return
    items = store.list_items(job_id)
    if not items:
        return
    sts = [i["status"] for i in items]
    try:
        if all(s == JobItemStatus.COMPLETED.value for s in sts):
            store.update_job_status(job_id, JobStatus.COMPLETED)
        elif any(s == JobItemStatus.PROCESSING.value for s in sts):
            store.update_job_status(job_id, JobStatus.PROCESSING)
        elif any(s == JobItemStatus.AWAITING_REVIEW.value for s in sts):
            store.update_job_status(job_id, JobStatus.AWAITING_REVIEW)
        elif any(s == JobItemStatus.FAILED.value for s in sts):
            store.update_job_status(job_id, JobStatus.FAILED)
    except (InvalidStatusTransition, KeyError, ValueError):
        pass  # 状态已是目标值或转换不合法，忽略


# ---------------------------------------------------------------------------
# Progress & nav hints
# ---------------------------------------------------------------------------

def progress_from_items(items: list[dict[str, Any]]) -> dict[str, int]:
    total = len(items)
    by = {s.value: 0 for s in JobItemStatus}
    for it in items:
        st = it.get("status") or ""
        if st in by:
            by[st] += 1
    return {
        "total_items": total,
        "pending": by[JobItemStatus.PENDING.value],
        "processing": by.get(JobItemStatus.PROCESSING.value, 0),
        "queued": by[JobItemStatus.QUEUED.value],
        "parsing": by[JobItemStatus.PARSING.value],
        "ner": by[JobItemStatus.NER.value],
        "vision": by[JobItemStatus.VISION.value],
        "awaiting_review": by[JobItemStatus.AWAITING_REVIEW.value],
        "review_approved": by[JobItemStatus.REVIEW_APPROVED.value],
        "redacting": by[JobItemStatus.REDACTING.value],
        "completed": by[JobItemStatus.COMPLETED.value],
        "failed": by[JobItemStatus.FAILED.value],
        "cancelled": by[JobItemStatus.CANCELLED.value],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def job_type_from_str(s: str) -> JobType:
    """Parse job type string to enum. Raises ValueError on invalid input."""
    try:
        return JobType(s)
    except ValueError:
        raise ValueError(f"invalid job_type: {s}")


def job_config_dict(job_row: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(job_row.get("config_json") or "{}")
    except json.JSONDecodeError:
        return {}


def file_meta_for_item(file_id: str) -> dict[str, Any]:
    """Get file metadata for a job item."""
    from app.services.file_management_service import file_store, entity_count

    info = file_store.get(file_id)
    if not info:
        return {
            "filename": None,
            "file_type": None,
            "has_output": False,
            "entity_count": 0,
        }

    raw_file_type = info.get("file_type")
    file_type = getattr(raw_file_type, "value", raw_file_type)
    return {
        "filename": info.get("original_filename"),
        "file_type": file_type,
        "has_output": bool(info.get("output_path")),
        "entity_count": entity_count(info),
    }


def item_to_out(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a job item row to output dict with file metadata."""
    file_meta = file_meta_for_item(str(row["file_id"]))
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "file_id": row["file_id"],
        "sort_order": row["sort_order"],
        "status": row["status"],
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
    }


def job_to_summary(row: dict[str, Any], store: JobStore) -> dict[str, Any]:
    """Build job summary dict including progress and nav hints."""
    from app.services.file_management_service import file_store

    items = store.list_items(row["id"])
    first_awaiting: str | None = None
    redacted_count = 0
    awaiting_review_count = 0
    for i in items:
        fid = str(i["file_id"])
        has_output = bool((file_store.get(fid) or {}).get("output_path"))
        if has_output:
            redacted_count += 1
        elif i.get("status") in ("awaiting_review", "review_approved", "completed"):
            awaiting_review_count += 1
            if first_awaiting is None:
                first_awaiting = str(i["id"])
    cfg = job_config_dict(row)
    nav_hints: dict[str, Any] = {
        "item_count": len(items),
        "first_awaiting_review_item_id": first_awaiting,
        "batch_step1_configured": infer_batch_step1_configured(cfg, str(row["job_type"])),
        "redacted_count": redacted_count,
        "awaiting_review_count": awaiting_review_count,
    }
    wf = coerce_wizard_furthest_step(cfg.get("wizard_furthest_step"))
    if wf is not None:
        nav_hints["wizard_furthest_step"] = wf
    return {
        "id": row["id"],
        "job_type": row["job_type"],
        "title": row["title"],
        "status": row["status"],
        "skip_item_review": bool(row.get("skip_item_review")),
        "priority": int(row.get("priority") or 0),
        "config": cfg,
        "error_message": row.get("error_message"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "progress": progress_from_items(items),
        "nav_hints": nav_hints,
    }


# ---------------------------------------------------------------------------
# Task enqueue
# ---------------------------------------------------------------------------

def enqueue_task(task_type: str, job_id: str, item_id: str, file_id: str) -> None:
    """投递任务到进程内队列。"""
    try:
        from app.services.task_queue import get_task_queue, TaskItem
        queue = get_task_queue()
        queue.enqueue(TaskItem(
            job_id=job_id,
            item_id=item_id,
            file_id=file_id,
            task_type=task_type,
        ))
    except (RuntimeError, ValueError):
        logger.exception("enqueue_task: 投递 %s 失败（item=%s）", task_type, item_id[:8])


# ---------------------------------------------------------------------------
# RedactionConfig construction
# ---------------------------------------------------------------------------

def build_redaction_config(job_row: dict[str, Any]) -> RedactionConfig:
    cfg = job_config_dict(job_row)
    return RedactionConfig(
        replacement_mode=cfg.get("replacement_mode", "structured"),
        entity_types=cfg.get("entity_type_ids") or [],
        custom_replacements=cfg.get("custom_replacements") or {},
        image_redaction_method=cfg.get("image_redaction_method"),
        image_redaction_strength=cfg.get("image_redaction_strength") or 25,
        image_fill_color=cfg.get("image_fill_color") or "#000000",
    )


def group_boxes_by_page(boxes: list[BoundingBox]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for box in boxes:
        page = int(getattr(box, "page", 1) or 1)
        grouped.setdefault(page, []).append(to_jsonable(box))
    return grouped


def resolve_committed_output_path(
    file_info: dict[str, Any],
    result: Any,
    stored_info: dict[str, Any],
) -> Optional[str]:
    candidates: list[str] = []

    for raw in (getattr(result, "output_path", None), stored_info.get("output_path")):
        if isinstance(raw, str) and raw.strip():
            candidates.append(raw.strip())

    output_file_id = getattr(result, "output_file_id", None)
    if isinstance(output_file_id, str) and output_file_id.strip():
        source_path = str(file_info.get("file_path") or "")
        ext = os.path.splitext(source_path)[1]
        raw_file_type = getattr(file_info.get("file_type"), "value", file_info.get("file_type"))
        if raw_file_type == "doc":
            ext = ".docx"
        if ext:
            candidates.append(os.path.join(settings.OUTPUT_DIR, f"{output_file_id}{ext}"))

    seen: set[str] = set()
    for candidate in candidates:
        real = os.path.realpath(candidate)
        if real in seen:
            continue
        seen.add(real)
        if os.path.exists(real):
            return real

    return None


# ---------------------------------------------------------------------------
# Job / item validation helpers
# ---------------------------------------------------------------------------

def get_job_and_item(store: JobStore, job_id: str, item_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Look up job and item, raise ValueError if not found."""
    job = store.get_job(job_id)
    if not job:
        raise ValueError("job not found")
    item = store.get_item(item_id)
    if not item or item["job_id"] != job_id:
        raise ValueError("item not found")
    return job, item


def review_draft_response(store: JobStore, item_id: str) -> dict[str, Any]:
    item = store.get_item(item_id)
    if not item:
        raise ValueError("item not found")
    draft = store.get_item_review_draft(item_id)
    if draft is None:
        return {"exists": False, "entities": [], "bounding_boxes": [], "updated_at": None}
    return {
        "exists": True,
        "entities": draft.get("entities") or [],
        "bounding_boxes": draft.get("bounding_boxes") or [],
        "updated_at": draft.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# File detaching
# ---------------------------------------------------------------------------

async def detach_job_from_files(job_id: str, items: list[dict[str, Any]]) -> int:
    from app.services.file_management_service import _file_store_lock, file_store

    detached = 0
    file_ids = {str(item["file_id"]) for item in items if item.get("file_id")}
    async with _file_store_lock:
        for file_id in file_ids:
            info = file_store.get(file_id)
            if not isinstance(info, dict):
                continue
            if info.get("job_id") != job_id:
                continue
            info.pop("job_id", None)
            info["upload_source"] = "batch"
            file_store.set(file_id, info)
            detached += 1
    return detached


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def create_job(store: JobStore, job_type_str: str, title: str, config: Any,
               skip_item_review: bool, priority: int) -> dict[str, Any]:
    """Create a new job and return its summary."""
    jt = job_type_from_str(job_type_str)
    jid = store.create_job(
        job_type=jt,
        title=title,
        config=config,
        skip_item_review=skip_item_review,
        priority=priority,
    )
    row = store.get_job(jid)
    assert row
    return job_to_summary(row, store)


def list_jobs(store: JobStore, job_type: Optional[str], page: int, page_size: int) -> dict[str, Any]:
    """List jobs with pagination and optional type filter."""
    jt_filter: Optional[JobType] = job_type_from_str(job_type) if job_type else None
    rows, total = store.list_jobs(job_type=jt_filter, page=page, page_size=page_size)
    jobs = [job_to_summary(r, store) for r in rows]
    return {"jobs": jobs, "total": total, "page": page, "page_size": page_size}


def get_job_detail(store: JobStore, job_id: str) -> dict[str, Any]:
    """Get full job detail with items. Raises ValueError if not found."""
    row = store.get_job(job_id)
    if not row:
        raise ValueError("job not found")
    items = store.list_items(job_id)
    base = job_to_summary(row, store)
    base["items"] = [item_to_out(i) for i in items]
    return base


def update_draft(store: JobStore, job_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Update a draft job. Raises ValueError on errors."""
    row = store.get_job(job_id)
    if not row:
        raise ValueError("job not found")
    if row["status"] not in UPDATABLE_JOB_STATUSES:
        raise ValueError("terminal jobs cannot be updated")
    if not patch:
        return job_to_summary(row, store)
    if not store.update_job_draft(job_id, patch):
        raise ValueError("nothing to update")
    store.touch_job_updated(job_id)
    row2 = store.get_job(job_id)
    assert row2
    return job_to_summary(row2, store)


def add_item(store: JobStore, job_id: str, file_id: str, sort_order: Optional[int]) -> dict[str, Any]:
    """Add an item to a draft job. Raises ValueError on errors."""
    row = store.get_job(job_id)
    if not row:
        raise ValueError("job not found")
    if row["status"] not in (JobStatus.DRAFT.value,):
        raise ValueError("only draft jobs accept new items")
    iid = store.add_item(job_id, file_id, sort_order=sort_order)
    store.touch_job_updated(job_id)
    ir = store.get_item(iid)
    assert ir
    return item_to_out(ir)


def submit_job(store: JobStore, job_id: str) -> dict[str, Any]:
    """Submit a job for processing. Raises ValueError on errors."""
    row = store.get_job(job_id)
    if not row:
        raise ValueError("job not found")
    items = store.list_items(job_id)
    if not items:
        raise ValueError("no items to submit")
    try:
        store.submit_job(job_id)
    except ValueError:
        raise
    # 将所有 PENDING item 入队
    for it in store.list_items(job_id):
        if it["status"] == JobItemStatus.PENDING.value:
            enqueue_task("recognition", job_id, it["id"], it["file_id"])
    row2 = store.get_job(job_id)
    assert row2
    return job_to_summary(row2, store)


def cancel_job(store: JobStore, job_id: str) -> dict[str, Any]:
    """Cancel a job. Raises ValueError if not found."""
    row = store.get_job(job_id)
    if not row:
        raise ValueError("job not found")
    store.cancel_job(job_id)
    row2 = store.get_job(job_id)
    assert row2
    return job_to_summary(row2, store)


def requeue_failed(store: JobStore, job_id: str) -> dict[str, Any]:
    """Re-queue all failed items. Raises ValueError on errors."""
    row = store.get_job(job_id)
    if not row:
        raise ValueError("job not found")
    items = store.list_items(job_id)
    count = 0
    errors: list[str] = []
    for it in items:
        if it["status"] == JobItemStatus.FAILED.value:
            try:
                store.update_item_status(it["id"], JobItemStatus.PENDING)
                count += 1
            except InvalidStatusTransition as e:
                errors.append(str(e))
    if count == 0 and not errors:
        raise ValueError("没有失败的项可以重新排队")
    if count == 0 and errors:
        raise ValueError(f"状态转换失败: {'; '.join(errors)}")
    # 把 job 拉回可运行状态
    try:
        job_status = row["status"]
        if job_status in (JobStatus.FAILED.value, JobStatus.COMPLETED.value):
            store.update_job_status(job_id, JobStatus.QUEUED)
        elif job_status == JobStatus.CANCELLED.value:
            pass
    except InvalidStatusTransition:
        pass
    # 重新入队
    for it in store.list_items(job_id):
        if it["status"] == JobItemStatus.PENDING.value:
            enqueue_task("recognition", job_id, it["id"], it["file_id"])
    row2 = store.get_job(job_id)
    assert row2
    return job_to_summary(row2, store)


async def delete_job(store: JobStore, job_id: str) -> dict[str, Any]:
    """Delete a job and detach its files. Raises ValueError on errors."""
    row = store.get_job(job_id)
    if not row:
        raise ValueError("job not found")
    if row["status"] not in DELETABLE_JOB_STATUSES:
        raise ValueError("active jobs must be cancelled before deletion")

    items = store.list_items(job_id)
    try:
        store.delete_job(job_id)
    except KeyError:
        raise ValueError("job not found")
    detached_file_count = await detach_job_from_files(job_id, items)
    return {
        "id": job_id,
        "deleted": True,
        "deleted_item_count": len(items),
        "detached_file_count": detached_file_count,
    }


# ---------------------------------------------------------------------------
# Review operations
# ---------------------------------------------------------------------------

def get_review_draft(store: JobStore, job_id: str, item_id: str) -> dict[str, Any]:
    get_job_and_item(store, job_id, item_id)
    return review_draft_response(store, item_id)


def save_review_draft(store: JobStore, job_id: str, item_id: str, payload: dict) -> dict[str, Any]:
    get_job_and_item(store, job_id, item_id)
    store.save_item_review_draft(item_id, payload)
    store.touch_job_updated(job_id)
    return review_draft_response(store, item_id)


def approve_review(store: JobStore, job_id: str, item_id: str, reviewer: str = "local") -> dict[str, Any]:
    """Approve an item review and enqueue redaction. Raises ValueError on errors."""
    get_job_and_item(store, job_id, item_id)
    try:
        store.approve_item_review(item_id, reviewer=reviewer)
    except ValueError:
        raise
    ir = store.get_item(item_id)
    assert ir
    store.touch_job_updated(job_id)
    refresh_job_status(store, job_id)
    # 触发匿名化任务
    enqueue_task("redaction", job_id, item_id, ir["file_id"])
    return item_to_out(ir)


def reject_review(store: JobStore, job_id: str, item_id: str, reviewer: str = "local") -> dict[str, Any]:
    """Reject an item review and re-enqueue recognition. Raises ValueError on errors."""
    get_job_and_item(store, job_id, item_id)
    try:
        store.reject_item_review(item_id, reviewer=reviewer)
    except ValueError:
        raise
    ir = store.get_item(item_id)
    assert ir
    store.touch_job_updated(job_id)
    refresh_job_status(store, job_id)
    enqueue_task("recognition", job_id, item_id, ir["file_id"])
    return item_to_out(ir)


async def commit_review(
    store: JobStore,
    job_id: str,
    item_id: str,
    entities: list,
    bounding_boxes: list,
    payload: dict,
    reviewer: str = "local",
) -> dict[str, Any]:
    """
    Commit item review: save draft, run redaction, update file_store.
    Raises ValueError on errors.
    """
    from app.services.file_management_service import _file_store_lock, file_store
    from app.services.redactor import Redactor

    job, item = get_job_and_item(store, job_id, item_id)
    if item["status"] in (JobItemStatus.CANCELLED.value, JobItemStatus.FAILED.value):
        raise ValueError(f"item not committable: {item['status']}")
    if item["status"] == JobItemStatus.COMPLETED.value:
        return item_to_out(item)

    store.save_item_review_draft(item_id, payload)
    if item["status"] == JobItemStatus.PENDING.value:
        store.update_item_status(item_id, JobItemStatus.AWAITING_REVIEW)
    store.mark_item_redacting(item_id)
    store.touch_job_updated(job_id)
    refresh_job_status(store, job_id)

    async with _file_store_lock:
        file_info = file_store.get(item["file_id"])
    if not file_info:
        store.update_item_status(item_id, JobItemStatus.AWAITING_REVIEW, error_message="file not found")
        refresh_job_status(store, job_id)
        raise ValueError("file not found")

    config = build_redaction_config(job)

    try:
        redactor = Redactor()
        result = await redactor.redact(
            file_info=file_info,
            entities=entities,
            bounding_boxes=bounding_boxes,
            config=config,
        )
        async with _file_store_lock:
            info = file_store.get(item["file_id"])
            if info is None:
                info = dict(file_info)
            info["output_path"] = result["output_path"]
            info["entity_map"] = result.get("entity_map", {})
            info["redacted_count"] = int(result.get("redacted_count", 0))
            info["entities"] = to_jsonable(entities)
            info["bounding_boxes"] = group_boxes_by_page(bounding_boxes)
            file_store.set(item["file_id"], info)

        store.complete_item_review(item_id, reviewer=reviewer)
        store.touch_job_updated(job_id)
        refresh_job_status(store, job_id)
    except Exception as exc:  # broad catch: commit_review must report all failures to caller
        import traceback
        logger.error("commit_review Exception for item %s: %s\n%s", item_id, str(exc), traceback.format_exc())
        try:
            store.update_item_status(item_id, JobItemStatus.AWAITING_REVIEW, error_message=str(exc))
        except (InvalidStatusTransition, KeyError, ValueError):
            store.update_item_status(item_id, JobItemStatus.FAILED, error_message=str(exc))
        store.touch_job_updated(job_id)
        refresh_job_status(store, job_id)
        raise

    item_done = store.get_item(item_id)
    assert item_done
    return item_to_out(item_done)
