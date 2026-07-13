"""
任务管理业务逻辑服务层 — 从 api/jobs.py 提取。

Job 状态推导、进度计算、导航提示、文件元数据收集、
向导状态管理、RedactionConfig 构建、队列投递、审核逻辑等。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any

from app.core.persistence import to_jsonable
from app.core.sqlite_base import connect_sqlite
from app.models.errors import ConflictError, NotFoundError, ValidationError
from app.models.schemas import (
    BoundingBox,
    RedactionConfig,
)
from app.services.batch_mode_validation import validate_file_allowed_for_job_type
from app.services.job_metadata import (
    _is_structured_job,
    _recognition_queue_meta_for_item,
    _recognition_queue_sort_key,
    _redacted_output_state,
    _safe_entity_count,
    _safe_file_info,
    _safe_int,
    _status_value,
    assert_job_owner,
    item_to_out,
    job_config_dict,
    job_type_from_str,
    lock_job_config,
)

# file_meta_for_item 未被父模块内部调用，但属公共 API，显式再导出（保持 _jms.file_meta_for_item 可用）。
from app.services.job_metadata import file_meta_for_item as file_meta_for_item
from app.services.job_store import (
    InvalidStatusTransition,
    JobItemStatus,
    JobStatus,
    JobStore,
    JobType,
)
from app.services.job_visual_evidence import (
    _empty_visual_evidence,
    _iter_bounding_boxes,
    _merge_visual_evidence,
    _sorted_visual_evidence,
    _visual_evidence_summary,
    _visual_review_quality,
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

REVIEWABLE_ITEM_STATUSES = frozenset({JobItemStatus.AWAITING_REVIEW.value})

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
    except Exception:
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

_JOB_STORE_RETRYABLE_MESSAGES = (
    "database is locked",
    "database table is locked",
    "database is busy",
    "disk i/o error",
)
_REVIEW_DRAFT_BUSY_RETRY_AFTER_MS = 500


def _is_retryable_sqlite_error(exc: sqlite3.OperationalError) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in _JOB_STORE_RETRYABLE_MESSAGES)


def _empty_review_draft_response(*, degraded: bool = False) -> dict[str, Any]:
    response: dict[str, Any] = {
        "exists": False,
        "entities": [],
        "bounding_boxes": [],
        "updated_at": None,
    }
    if degraded:
        response["degraded"] = True
        response["retry_after_ms"] = _REVIEW_DRAFT_BUSY_RETRY_AFTER_MS
    return response



def job_to_summary(row: dict[str, Any], store: JobStore) -> dict[str, Any]:
    """Build job summary dict including progress and nav hints."""
    items = store.list_items(row["id"])
    is_structured = _is_structured_job(row)
    structured_export_dataset_ids: set[str] = set()
    if is_structured:
        try:
            from app.services.structured_store import get_structured_store

            structured_export_dataset_ids = {
                str(export.get("dataset_id"))
                for export in get_structured_store().list_exports(
                    owner_id=str(row.get("owner_id") or "local_user"),
                    job_id=str(row["id"]),
                )
                if export.get("dataset_id")
            }
        except Exception:
            logger.debug("unable to read structured exports for job %s", row["id"], exc_info=True)
    first_awaiting: str | None = None
    redacted_count = 0
    reviewable_count = 0
    skip_item_review = bool(row.get("skip_item_review"))
    for i in items:
        fid = str(i["file_id"])
        status = _status_value(i.get("status"))
        if is_structured:
            has_output = status == JobItemStatus.COMPLETED.value or fid in structured_export_dataset_ids
        else:
            info, _ = _safe_file_info(fid)
            has_output, _ = _redacted_output_state(info)
        if has_output:
            redacted_count += 1
        if status in REVIEWABLE_ITEM_STATUSES:
            reviewable_count += 1
            if first_awaiting is None:
                first_awaiting = str(i["id"])
    cfg = job_config_dict(row)
    item_count = len(items)
    nav_hints: dict[str, Any] = {
        "item_count": item_count,
        "first_awaiting_review_item_id": first_awaiting,
        "batch_step1_configured": infer_batch_step1_configured(cfg, str(row["job_type"])),
        "redacted_count": redacted_count,
        "awaiting_review_count": reviewable_count,
    }
    wf = coerce_wizard_furthest_step(cfg.get("wizard_furthest_step"))
    if wf is not None:
        nav_hints["wizard_furthest_step"] = wf
    return {
        "id": row["id"],
        "job_type": row["job_type"],
        "title": row["title"],
        "status": _status_value(row.get("status")),
        "skip_item_review": skip_item_review,
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

def enqueue_task(
    task_type: str,
    job_id: str,
    item_id: str,
    file_id: str,
    meta: dict[str, Any] | None = None,
) -> None:
    """投递任务到进程内队列。"""
    try:
        from app.services.task_queue import TaskItem, get_task_queue
        queue = get_task_queue()
        queue.enqueue(TaskItem(
            job_id=job_id,
            item_id=item_id,
            file_id=file_id,
            task_type=task_type,
            meta=dict(meta or {}),
        ))
    except Exception:
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
        image_redaction_strength=cfg.get("image_redaction_strength") or 75,
        image_fill_color=cfg.get("image_fill_color") or "#000000",
    )


def group_boxes_by_page(boxes: list[BoundingBox]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for box in boxes:
        page = int(getattr(box, "page", 1) or 1)
        grouped.setdefault(page, []).append(to_jsonable(box))
    return grouped




# ---------------------------------------------------------------------------
# Job / item validation helpers
# ---------------------------------------------------------------------------

def get_job_and_item(store: JobStore, job_id: str, item_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Look up job and item, raise ValueError if not found."""
    job = store.get_job(job_id)
    if not job:
        raise NotFoundError("job not found")
    item = store.get_item(item_id)
    if not item or item["job_id"] != job_id:
        raise NotFoundError("item not found")
    return job, item


def _review_draft_from_row(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("review_draft_json")
    if not raw:
        return _empty_review_draft_response()
    try:
        draft = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return _empty_review_draft_response()
    if not isinstance(draft, dict):
        return _empty_review_draft_response()
    return {
        "exists": True,
        "entities": draft.get("entities") or [],
        "bounding_boxes": draft.get("bounding_boxes") or [],
        "updated_at": row.get("review_draft_updated_at"),
    }


def _read_review_draft_fast(store: JobStore, job_id: str, item_id: str) -> dict[str, Any]:
    db_path = getattr(store, "_path", None)
    if not isinstance(db_path, str) or not db_path:
        get_job_and_item(store, job_id, item_id)
        return review_draft_response(store, item_id)

    with connect_sqlite(
        db_path,
        timeout=0.35,
        busy_timeout_ms=_REVIEW_DRAFT_BUSY_RETRY_AFTER_MS,
        wal=False,
    ) as conn:
        row = conn.execute(
            """
            SELECT
                i.review_draft_json,
                i.review_draft_updated_at
            FROM job_items AS i
            INNER JOIN jobs AS j ON j.id = i.job_id
            WHERE j.id = ? AND i.id = ?
            LIMIT 1
            """,
            (job_id, item_id),
        ).fetchone()
        if row:
            return _review_draft_from_row(dict(row))

        job_exists = conn.execute("SELECT 1 FROM jobs WHERE id = ? LIMIT 1", (job_id,)).fetchone()
        if not job_exists:
            raise NotFoundError("job not found")
        raise NotFoundError("item not found")


def review_draft_response(store: JobStore, item_id: str) -> dict[str, Any]:
    item = store.get_item(item_id)
    if not item:
        raise NotFoundError("item not found")
    draft = store.get_item_review_draft(item_id)
    if draft is None:
        return _empty_review_draft_response()
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
               skip_item_review: bool, priority: int, owner_id: str = "local_user") -> dict[str, Any]:
    """Create a new job and return its summary."""
    jt = job_type_from_str(job_type_str)
    jid = store.create_job(
        job_type=jt,
        title=title,
        config=config,
        skip_item_review=skip_item_review,
        priority=priority,
        owner_id=owner_id,
    )
    row = store.get_job(jid)
    if not row:
        raise RuntimeError("internal invariant: row is unexpectedly missing")
    return job_to_summary(row, store)


def _job_status_filter_values(status_filter: str | None) -> list[str] | None:
    if not status_filter:
        return None
    value = str(status_filter).strip().lower()
    if value in ("all", ""):
        return None
    if value == "active":
        return [
            JobStatus.QUEUED.value,
            JobStatus.PROCESSING.value,
            JobStatus.RUNNING.value,
            JobStatus.REDACTING.value,
        ]
    if value == "risk":
        return [JobStatus.FAILED.value, JobStatus.CANCELLED.value]
    allowed = {
        JobStatus.DRAFT.value,
        JobStatus.AWAITING_REVIEW.value,
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }
    if value not in allowed:
        raise ValueError("invalid job status filter")
    return [value]


def list_jobs(
    store: JobStore,
    job_type: str | None,
    page: int,
    page_size: int,
    status_filter: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """List jobs with pagination and optional type filter."""
    jt_filter: JobType | None = job_type_from_str(job_type) if job_type else None
    status_values = _job_status_filter_values(status_filter)
    rows, total = store.list_jobs(
        job_type=jt_filter,
        status_values=status_values,
        owner_id=owner_id,
        page=page,
        page_size=page_size,
    )
    jobs = [job_to_summary(r, store) for r in rows]
    return {
        "jobs": jobs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "stats": store.job_list_stats(job_type=jt_filter, owner_id=owner_id),
    }


def get_job_detail(store: JobStore, job_id: str, owner_id: str | None = None) -> dict[str, Any]:
    """Get full job detail with items. Raises ValueError if not found."""
    row = store.get_job(job_id)
    assert_job_owner(row, owner_id)
    if not row:
        raise RuntimeError("internal invariant: row is unexpectedly missing")
    items = store.list_items(job_id)
    base = job_to_summary(row, store)
    base["items"] = [
        item_to_out(i, owner_id=str(row.get("owner_id") or owner_id or "local_user"), job_id=job_id)
        for i in items
    ]
    return base


def _count_by_status(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _review_confirmed(item: dict[str, Any], has_output: bool, skip_item_review: bool) -> bool:
    if skip_item_review and has_output:
        return True
    status = str(item.get("status") or "")
    if status == JobItemStatus.COMPLETED.value:
        return has_output
    return status in (JobItemStatus.REVIEW_APPROVED.value, JobItemStatus.REDACTING.value)




def _delivery_blocking_reasons(
    item: dict[str, Any],
    has_output: bool,
    review_confirmed: bool,
    redacted_skip_reason: str | None,
) -> list[str]:
    reasons: list[str] = []
    if str(item.get("status")) == JobItemStatus.FAILED.value:
        reasons.append("failed")
    if not has_output:
        reasons.append("missing_redacted_output")
    elif redacted_skip_reason is not None:
        reasons.append(redacted_skip_reason)
    if not review_confirmed:
        reasons.append("review_not_confirmed")
    return list(dict.fromkeys(reasons))


def _file_delivery_status(is_selected: bool, ready_for_delivery: bool) -> str:
    if not is_selected:
        return "not_selected"
    return "ready_for_delivery" if ready_for_delivery else "action_required"


def _summary_delivery_status(selected_count: int, action_required_count: int) -> str:
    if selected_count == 0:
        return "no_selection"
    return "ready_for_delivery" if action_required_count == 0 else "action_required"


def build_export_report(
    store: JobStore,
    job_id: str,
    selected_file_ids: list[str] | None = None,
    include_files: bool = True,
) -> dict[str, Any]:
    """Build an authoritative batch export report from job_items and file_store.

    include_files=False（summary_only）：只做聚合、不保留每文件明细——十万级
    item 的 job 拉全量明细会同时压垮后端内存与浏览器；明细走 CSV 分卷导出。
    """
    row = store.get_job(job_id)
    if not row:
        raise NotFoundError("job not found")

    items = store.list_items(job_id)
    all_file_ids = [str(item["file_id"]) for item in items]
    selected = set(selected_file_ids) if selected_file_ids is not None else set(all_file_ids)
    skip_item_review = bool(row.get("skip_item_review"))

    report_files: list[dict[str, Any]] = []
    selected_items: list[dict[str, Any]] = []
    selected_detected_entities = 0
    redacted_selected_count = 0
    review_confirmed_selected_count = 0
    failed_selected_count = 0
    action_required_count = 0
    zip_included_count = 0
    zip_skipped: list[dict[str, str]] = []
    selected_visual_review_issue_count = 0
    selected_visual_review_issue_files = 0
    selected_visual_review_issue_pages_count = 0
    selected_visual_review_by_issue: dict[str, int] = {}
    selected_visual_evidence = _empty_visual_evidence()

    for item in items:
        file_id = str(item["file_id"])
        info, metadata_warning = _safe_file_info(file_id)
        is_selected = file_id in selected
        has_output, redacted_skip_reason = _redacted_output_state(info)
        review_confirmed = _review_confirmed(item, has_output, skip_item_review)
        ready_for_delivery = (
            _status_value(item.get("status")) != JobItemStatus.FAILED.value
            and has_output
            and review_confirmed
            and redacted_skip_reason is None
        )
        blocking_reasons = _delivery_blocking_reasons(
            item,
            has_output,
            review_confirmed,
            redacted_skip_reason,
        )
        delivery_status = _file_delivery_status(is_selected, ready_for_delivery)
        detected_entities = _safe_entity_count(info)
        visual_quality = _visual_review_quality(info)
        visual_evidence = _visual_evidence_summary(info)
        if is_selected:
            selected_items.append(item)
            selected_detected_entities += detected_entities
            _merge_visual_evidence(selected_visual_evidence, visual_evidence)
            if visual_quality["issue_count"] > 0:
                selected_visual_review_issue_files += 1
                selected_visual_review_issue_count += int(visual_quality["issue_count"])
                for issue, count in visual_quality["by_issue"].items():
                    selected_visual_review_by_issue[issue] = selected_visual_review_by_issue.get(issue, 0) + int(count)
            if visual_quality["review_hint"]:
                selected_visual_review_issue_pages_count += len(visual_quality["issue_pages"])
            if has_output:
                redacted_selected_count += 1
            if review_confirmed:
                review_confirmed_selected_count += 1
            if _status_value(item.get("status")) == JobItemStatus.FAILED.value:
                failed_selected_count += 1
            if not ready_for_delivery:
                action_required_count += 1
            if redacted_skip_reason is None:
                zip_included_count += 1
            else:
                zip_skipped.append({"file_id": file_id, "reason": redacted_skip_reason})

        if not include_files:
            continue
        raw_file_type = info.get("file_type") if info else None
        report_files.append(
            {
                "item_id": item["id"],
                "file_id": file_id,
                "filename": (info or {}).get("original_filename") or item.get("filename") or "",
                "file_type": getattr(raw_file_type, "value", raw_file_type) or "",
                "file_size": int((info or {}).get("file_size") or 0),
                "status": _status_value(item.get("status")),
                "has_output": has_output,
                "review_confirmed": review_confirmed,
                "entity_count": detected_entities,
                "page_count": _safe_int((info or {}).get("page_count")) or None,
                "selected_for_export": is_selected,
                "delivery_status": delivery_status,
                "error": item.get("error_message") or metadata_warning,
                "metadata_warning": metadata_warning,
                "ready_for_delivery": ready_for_delivery,
                "action_required": not ready_for_delivery,
                "blocking": not ready_for_delivery,
                "blocking_reasons": blocking_reasons,
                "redacted_export_skip_reason": redacted_skip_reason,
                "visual_review_hint": bool(visual_quality["review_hint"]),
                "visual_evidence": visual_evidence,
                "visual_review": visual_quality,
            }
        )

    selected_count = len(selected_items)
    delivery_status = _summary_delivery_status(selected_count, action_required_count)
    selected_visual_review_issue_labels = sorted(selected_visual_review_by_issue)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "job": {
            "id": row["id"],
            "job_type": row["job_type"],
            "status": _status_value(row.get("status")),
            "skip_item_review": skip_item_review,
            "config": job_config_dict(row),
        },
        "summary": {
            "total_files": len(items),
            "selected_files": selected_count,
            "redacted_selected_files": redacted_selected_count,
            "unredacted_selected_files": selected_count - redacted_selected_count,
            "review_confirmed_selected_files": review_confirmed_selected_count,
            "failed_selected_files": failed_selected_count,
            "detected_entities": selected_detected_entities,
            "redaction_coverage": redacted_selected_count / selected_count if selected_count else 0,
            "delivery_status": delivery_status,
            "action_required_files": action_required_count,
            "action_required": action_required_count > 0,
            "blocking_files": action_required_count,
            "blocking": action_required_count > 0,
            "ready_for_delivery": selected_count > 0 and action_required_count == 0,
            "by_status": _count_by_status(selected_items),
            "zip_redacted_included_files": zip_included_count,
            "zip_redacted_skipped_files": len(zip_skipped),
            "visual_review_hint": selected_visual_review_issue_count > 0,
            "visual_review_issue_files": selected_visual_review_issue_files,
            "visual_review_issue_count": selected_visual_review_issue_count,
            "visual_review_issue_pages_count": selected_visual_review_issue_pages_count,
            "visual_review_issue_labels": selected_visual_review_issue_labels,
            "visual_review_by_issue": dict(sorted(selected_visual_review_by_issue.items())),
            "visual_evidence": _sorted_visual_evidence(selected_visual_evidence),
        },
        "redacted_zip": {
            "included_count": zip_included_count,
            "skipped_count": len(zip_skipped),
            "skipped": zip_skipped,
        },
        "files": report_files,
    }


REPORT_FILE_CSV_HEADERS = [
    "item_id", "file_id", "filename", "file_type", "file_size", "page_count",
    "status", "has_output", "review_confirmed", "ready_for_delivery",
    "entity_count", "blocking_reasons", "error",
]

ENTITY_CSV_HEADERS = [
    "file_id", "filename", "record_kind", "page", "type", "text",
    "source", "confidence", "start", "end", "x", "y", "width", "height", "selected",
]


def iter_report_file_rows(
    store: JobStore,
    job_id: str,
    selected_file_ids: list[str] | None = None,
):
    """逐 item 产出文件级明细行（CSV 友好扁平结构），内存 O(1)。

    与 build_export_report 的 per-file 字段同源（同一批 helper），供十万级
    job 的明细导出使用——评测场景"每个文件一行"的可分析数据。
    """
    row = store.get_job(job_id)
    if not row:
        raise NotFoundError("job not found")
    skip_item_review = bool(row.get("skip_item_review"))
    selected = set(selected_file_ids) if selected_file_ids is not None else None

    for item in store.list_items(job_id):
        file_id = str(item["file_id"])
        if selected is not None and file_id not in selected:
            continue
        info, metadata_warning = _safe_file_info(file_id)
        has_output, redacted_skip_reason = _redacted_output_state(info)
        review_confirmed = _review_confirmed(item, has_output, skip_item_review)
        ready_for_delivery = (
            _status_value(item.get("status")) != JobItemStatus.FAILED.value
            and has_output
            and review_confirmed
            and redacted_skip_reason is None
        )
        blocking_reasons = _delivery_blocking_reasons(
            item, has_output, review_confirmed, redacted_skip_reason
        )
        raw_file_type = info.get("file_type") if info else None
        yield {
            "item_id": item["id"],
            "file_id": file_id,
            "filename": (info or {}).get("original_filename") or item.get("filename") or "",
            "file_type": getattr(raw_file_type, "value", raw_file_type) or "",
            "file_size": int((info or {}).get("file_size") or 0),
            "page_count": _safe_int((info or {}).get("page_count")) or "",
            "status": _status_value(item.get("status")),
            "has_output": has_output,
            "review_confirmed": review_confirmed,
            "ready_for_delivery": ready_for_delivery,
            "entity_count": _safe_entity_count(info),
            "blocking_reasons": ";".join(blocking_reasons or []),
            "error": item.get("error_message") or metadata_warning or "",
        }


def iter_entity_rows(
    store: JobStore,
    job_id: str,
    selected_file_ids: list[str] | None = None,
):
    """逐条产出识别结果明细行（文本实体 + 视觉区域），内存 O(1)。"""
    row = store.get_job(job_id)
    if not row:
        raise NotFoundError("job not found")
    selected = set(selected_file_ids) if selected_file_ids is not None else None

    for item in store.list_items(job_id):
        file_id = str(item["file_id"])
        if selected is not None and file_id not in selected:
            continue
        info, _warning = _safe_file_info(file_id)
        if not info:
            continue
        filename = info.get("original_filename") or ""
        for entity in info.get("entities") or []:
            if not isinstance(entity, dict):
                continue
            yield {
                "file_id": file_id,
                "filename": filename,
                "record_kind": "entity",
                "page": entity.get("page"),
                "type": entity.get("type"),
                "text": entity.get("text"),
                "source": entity.get("source"),
                "confidence": entity.get("confidence"),
                "start": entity.get("start"),
                "end": entity.get("end"),
            }
        for box in _iter_bounding_boxes(info):
            yield {
                "file_id": file_id,
                "filename": filename,
                "record_kind": "region",
                "page": box.get("page"),
                "type": box.get("type"),
                "text": box.get("text"),
                "source": box.get("source"),
                "confidence": box.get("confidence"),
                "x": box.get("x"),
                "y": box.get("y"),
                "width": box.get("width"),
                "height": box.get("height"),
                "selected": box.get("selected"),
            }


def update_draft(store: JobStore, job_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Update a draft job. Raises ValueError on errors."""
    row = store.get_job(job_id)
    if not row:
        raise NotFoundError("job not found")
    if row["status"] != JobStatus.DRAFT.value:
        raise ConflictError("job config is locked")
    if not patch:
        return job_to_summary(row, store)
    if not store.update_job_draft(job_id, patch):
        raise ValueError("nothing to update")
    store.touch_job_updated(job_id)
    row2 = store.get_job(job_id)
    if not row2:
        raise RuntimeError("internal invariant: row2 is unexpectedly missing")
    return job_to_summary(row2, store)


def add_item(store: JobStore, job_id: str, file_id: str, sort_order: int | None) -> dict[str, Any]:
    """Add an item to a draft job. Raises ValueError on errors."""
    from app.services.file_management_service import file_store

    row = store.get_job(job_id)
    if not row:
        raise NotFoundError("job not found")
    if row["status"] not in (JobStatus.DRAFT.value,):
        raise ValueError("only draft jobs accept new items")
    if _is_structured_job(row):
        from app.services.structured_store import get_structured_store

        owner_id = str(row.get("owner_id") or "local_user")
        if not get_structured_store().get_dataset(file_id, owner_id=owner_id):
            raise NotFoundError("dataset not found")
        iid = store.add_item(job_id, file_id, sort_order=sort_order)
        store.touch_job_updated(job_id)
        ir = store.get_item(iid)
        if not ir:
            raise RuntimeError("internal invariant: ir is unexpectedly missing")
        return item_to_out(ir, owner_id=owner_id, job_id=job_id)
    validate_file_allowed_for_job_type(
        job_type=row["job_type"],
        file_info=file_store.get(file_id),
        file_id=file_id,
    )
    iid = store.add_item(job_id, file_id, sort_order=sort_order)
    store.touch_job_updated(job_id)
    ir = store.get_item(iid)
    if not ir:
        raise RuntimeError("internal invariant: ir is unexpectedly missing")
    return item_to_out(ir)


def submit_job(store: JobStore, job_id: str) -> dict[str, Any]:
    """Submit a job for processing. Raises ValueError on errors."""
    from app.services.file_management_service import file_store

    row = store.get_job(job_id)
    if not row:
        raise NotFoundError("job not found")
    items = store.list_items(job_id)
    if not items:
        raise ValueError("no items to submit")
    if _is_structured_job(row):
        from app.services.structured_service import get_or_create_policy, profile_dataset
        from app.services.structured_store import get_structured_store

        structured_store = get_structured_store()
        owner_id = str(row.get("owner_id") or "local_user")
        for it in items:
            dataset_id = str(it["file_id"])
            if not structured_store.get_dataset(dataset_id, owner_id=owner_id):
                raise NotFoundError(f"dataset not found: {dataset_id}")
            if not structured_store.get_profile(dataset_id, owner_id=owner_id):
                profile_dataset(dataset_id, owner_id=owner_id, store=structured_store)
            get_or_create_policy(dataset_id, owner_id=owner_id, store=structured_store)
    else:
        for it in items:
            validate_file_allowed_for_job_type(
                job_type=row["job_type"],
                file_info=file_store.get(str(it["file_id"])),
                file_id=str(it["file_id"]),
            )
    try:
        lock_job_config(store, job_id, row)
        store.submit_job(job_id)
    except ValueError:
        raise
    # 将所有 PENDING item 入队
    pending_items = [
        it for it in store.list_items(job_id)
        if it["status"] == JobItemStatus.PENDING.value
    ]
    if _is_structured_job(row):
        for it in pending_items:
            enqueue_task(
                "structured",
                job_id,
                it["id"],
                it["file_id"],
                meta={"priority_class": 0, "estimated_work_units": 1},
            )
    else:
        for it in sorted(pending_items, key=_recognition_queue_sort_key):
            meta = _recognition_queue_meta_for_item(it)
            logger.info(
                "submit_job enqueue recognition item=%s priority=%s work=%s",
                str(it["id"])[:8],
                meta.get("priority_class"),
                meta.get("estimated_work_units"),
            )
            enqueue_task("recognition", job_id, it["id"], it["file_id"], meta=meta)
    row2 = store.get_job(job_id)
    if not row2:
        raise RuntimeError("internal invariant: row2 is unexpectedly missing")
    return job_to_summary(row2, store)


def cancel_job(store: JobStore, job_id: str) -> dict[str, Any]:
    """Cancel a job. Raises ValueError if not found."""
    row = store.get_job(job_id)
    if not row:
        raise NotFoundError("job not found")
    store.cancel_job(job_id)
    row2 = store.get_job(job_id)
    if not row2:
        raise RuntimeError("internal invariant: row2 is unexpectedly missing")
    return job_to_summary(row2, store)


def requeue_failed(store: JobStore, job_id: str) -> dict[str, Any]:
    """Re-queue all failed items. Raises ValueError on errors."""
    row = store.get_job(job_id)
    if not row:
        raise NotFoundError("job not found")
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
        raise ConflictError("没有失败的项可以重新排队")
    if count == 0 and errors:
        raise ConflictError(f"状态转换失败: {'; '.join(errors)}")
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
    pending_items = [
        it for it in store.list_items(job_id)
        if it["status"] == JobItemStatus.PENDING.value
    ]
    if _is_structured_job(row):
        for it in pending_items:
            enqueue_task(
                "structured",
                job_id,
                it["id"],
                it["file_id"],
                meta={"priority_class": 0, "estimated_work_units": 1},
            )
    else:
        for it in sorted(pending_items, key=_recognition_queue_sort_key):
            enqueue_task(
                "recognition",
                job_id,
                it["id"],
                it["file_id"],
                meta=_recognition_queue_meta_for_item(it),
            )
    row2 = store.get_job(job_id)
    if not row2:
        raise RuntimeError("internal invariant: row2 is unexpectedly missing")
    return job_to_summary(row2, store)


async def delete_job(store: JobStore, job_id: str) -> dict[str, Any]:
    """Delete a job and detach its files. Raises ValueError on errors."""
    row = store.get_job(job_id)
    if not row:
        raise NotFoundError("job not found")
    if row["status"] not in DELETABLE_JOB_STATUSES:
        raise ConflictError("active jobs must be cancelled before deletion")

    items = store.list_items(job_id)
    try:
        store.delete_job(job_id)
    except KeyError:
        raise NotFoundError("job not found")
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
    try:
        return _read_review_draft_fast(store, job_id, item_id)
    except sqlite3.OperationalError as exc:
        if not _is_retryable_sqlite_error(exc):
            raise
        logger.warning(
            "review draft read degraded for job %s item %s: %s",
            job_id,
            item_id,
            exc,
        )
        return _empty_review_draft_response(degraded=True)
    except KeyError:
        raise NotFoundError("item not found")


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
    if not ir:
        raise RuntimeError("internal invariant: ir is unexpectedly missing")
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
    if not ir:
        raise RuntimeError("internal invariant: ir is unexpectedly missing")
    store.touch_job_updated(job_id)
    refresh_job_status(store, job_id)
    enqueue_task("recognition", job_id, item_id, ir["file_id"])
    return item_to_out(ir)


async def _seed_file_store_from_draft_payload(file_id: str, draft: dict) -> None:
    """Push a saved review draft into the file store so the async redaction
    worker (which reads recognized regions from the file store) honours the
    reviewer's edits. No-op when the item has no draft (un-opened files keep
    their recognized regions)."""
    from app.services.file_management_service import _file_store_lock, file_store

    entities = draft.get("entities")
    boxes = draft.get("bounding_boxes")
    if not entities and not boxes:
        return
    async with _file_store_lock:
        info = file_store.get(file_id)
        if not isinstance(info, dict):
            return
        if entities is not None:
            info["entities"] = to_jsonable(entities)
        if boxes is not None:
            # The redaction worker accepts a flat list of box dicts directly.
            info["bounding_boxes"] = to_jsonable(boxes)
        file_store.set(file_id, info)


async def commit_all_reviews(
    store: JobStore, job_id: str, reviewer: str = "local"
) -> dict[str, Any]:
    """Batch one-click confirm: approve every awaiting-review item in a job at once.

    Scale path（万级 job）: drafts are fetched in one query, approval is one
    bulk transaction（per-item approve + per-item job-status refresh 在 6000+
    条时是分钟级 O(N²)）, then items are enqueued for async redaction so the
    worker pool honours JOB_CONCURRENCY. Items whose review was edited use
    their draft; un-opened items keep recognized regions.
    """
    job = store.get_job(job_id)
    if not job:
        raise NotFoundError("job not found")

    awaiting = [
        it
        for it in store.list_items(job_id)
        if it["status"] == JobItemStatus.AWAITING_REVIEW.value
    ]
    if not awaiting:
        return {"job_id": job_id, "total_awaiting": 0, "confirmed": 0, "failed": []}

    awaiting_ids = [it["id"] for it in awaiting]
    awaiting_id_set = set(awaiting_ids)

    failed: list[dict[str, Any]] = []
    try:
        drafts = store.list_item_review_drafts(job_id)
    except Exception:
        logger.exception("commit_all_reviews: draft prefetch failed for job %s", job_id[:8])
        drafts = {}
    for item_id, (file_id, draft) in drafts.items():
        if item_id not in awaiting_id_set:
            continue
        try:
            await _seed_file_store_from_draft_payload(file_id, draft)
        except Exception as exc:  # draft seeding must not abort the batch
            logger.warning("commit_all_reviews: draft seed failed for %s: %s", item_id[:8], exc)

    approved = store.approve_items_review_bulk(awaiting_ids, reviewer=reviewer)
    approved_ids = {item_id for item_id, _ in approved}
    for item_id in awaiting_ids:
        if item_id not in approved_ids:
            failed.append({"item_id": item_id, "error": "not approvable (status changed)"})

    for item_id, file_id in approved:
        enqueue_task("redaction", job_id, item_id, file_id)

    store.touch_job_updated(job_id)
    refresh_job_status(store, job_id)
    return {
        "job_id": job_id,
        "total_awaiting": len(awaiting),
        "confirmed": len(approved),
        "failed": failed,
    }


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
        raise ValidationError(f"item not committable: {item['status']}")
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
        raise NotFoundError("file not found")

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
    except Exception as exc:
        import traceback
        logger.error("commit_review Exception for item %s: %s\n%s", item_id, str(exc), traceback.format_exc())
        try:
            store.update_item_status(item_id, JobItemStatus.AWAITING_REVIEW, error_message=str(exc))
        except Exception:
            store.update_item_status(item_id, JobItemStatus.FAILED, error_message=str(exc))
        store.touch_job_updated(job_id)
        refresh_job_status(store, job_id)
        raise

    item_done = store.get_item(item_id)
    if not item_done:
        raise RuntimeError("internal invariant: item_done is unexpectedly missing")
    return item_to_out(item_done)
