"""
Batch job API: draft creation, queue submission, review draft persistence, and review commit.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from functools import lru_cache
from typing import Any, Literal, Optional

log = logging.getLogger("legal_redaction.jobs")

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from app.core.audit import audit_log
from app.core.config import settings
from app.core.persistence import to_jsonable
from app.models.schemas import (
    BoundingBox, Entity, RedactionConfig,
    JobResponse, JobItemResponse, JobListResponse, JobDetailResponse,
    JobDeleteResponse, JobProgressResponse, ReviewDraftResponse,
)
from app.services.job_store import JobItemStatus, JobStatus, JobStore, JobType
def _refresh_job_status(store: JobStore, job_id: str) -> None:
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
from app.services.wizard_furthest import coerce_wizard_furthest_step, infer_batch_step1_configured

router = APIRouter(prefix="/jobs", tags=["batch jobs"])

DELETABLE_JOB_STATUSES = frozenset(
    {
        JobStatus.DRAFT.value,
        JobStatus.AWAITING_REVIEW.value,
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }
)


@lru_cache
def _singleton_store() -> JobStore:
    return JobStore(settings.JOB_DB_PATH)


def get_job_store() -> JobStore:
    return _singleton_store()


def _enqueue_task(task_type: str, job_id: str, item_id: str, file_id: str) -> None:
    """投递任务到进程内队列（替代 Celery）。"""
    try:
        from app.services.task_queue import get_task_queue, TaskItem
        queue = get_task_queue()
        queue.enqueue(TaskItem(
            job_id=job_id,
            item_id=item_id,
            file_id=file_id,
            task_type=task_type,
        ))
    except Exception:
        log.exception("_enqueue_task: 投递 %s 失败（item=%s）", task_type, item_id[:8])


class JobCreateBody(BaseModel):
    job_type: Literal["text_batch", "image_batch", "smart_batch"]
    title: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    skip_item_review: bool = False
    priority: int = 0


class JobItemAddBody(BaseModel):
    file_id: str = Field(..., min_length=1)
    sort_order: int = 0


class JobUpdateBody(BaseModel):
    title: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    skip_item_review: Optional[bool] = None
    priority: Optional[int] = None


class ReviewDraftBody(BaseModel):
    entities: list[Entity] = Field(default_factory=list)
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    updated_at: Optional[str] = None


class ReviewCommitBody(ReviewDraftBody):
    pass


def _job_type_from_str(s: str) -> JobType:
    try:
        return JobType(s)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid job_type: {s}") from exc


def _job_config_dict(job_row: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(job_row.get("config_json") or "{}")
    except json.JSONDecodeError:
        return {}


def _progress_from_items(items: list[dict[str, Any]]) -> dict[str, int]:
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



def _file_meta_for_item(file_id: str) -> dict[str, Any]:
    from app.api.files import _entity_count, file_store

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
        "entity_count": _entity_count(info),
    }


def _item_to_out(row: dict[str, Any]) -> dict[str, Any]:
    file_meta = _file_meta_for_item(str(row["file_id"]))
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


async def _detach_job_from_files(job_id: str, items: list[dict[str, Any]]) -> int:
    from app.api.files import _file_store_lock, file_store

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


def _job_to_summary(row: dict[str, Any], store: JobStore) -> dict[str, Any]:
    items = store.list_items(row["id"])
    from app.api.files import file_store
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
    cfg = _job_config_dict(row)
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
        "progress": _progress_from_items(items),
        "nav_hints": nav_hints,
    }


def _get_job_and_item(store: JobStore, job_id: str, item_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    item = store.get_item(item_id)
    if not item or item["job_id"] != job_id:
        raise HTTPException(status_code=404, detail="item not found")
    return job, item


def _review_draft_response(store: JobStore, item_id: str) -> dict[str, Any]:
    item = store.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="item not found")
    draft = store.get_item_review_draft(item_id)
    if draft is None:
        return {"exists": False, "entities": [], "bounding_boxes": [], "updated_at": None}
    return {
        "exists": True,
        "entities": draft.get("entities") or [],
        "bounding_boxes": draft.get("bounding_boxes") or [],
        "updated_at": draft.get("updated_at"),
    }


def _build_redaction_config(job_row: dict[str, Any]) -> RedactionConfig:
    cfg = _job_config_dict(job_row)
    return RedactionConfig(
        replacement_mode=cfg.get("replacement_mode", "structured"),
        entity_types=cfg.get("entity_type_ids") or [],
        custom_replacements=cfg.get("custom_replacements") or {},
        image_redaction_method=cfg.get("image_redaction_method"),
        image_redaction_strength=cfg.get("image_redaction_strength") or 25,
        image_fill_color=cfg.get("image_fill_color") or "#000000",
    )


def _group_boxes_by_page(boxes: list[BoundingBox]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for box in boxes:
        page = int(getattr(box, "page", 1) or 1)
        grouped.setdefault(page, []).append(to_jsonable(box))
    return grouped


def _resolve_committed_output_path(
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


@router.post("", response_model=JobResponse)
async def create_job(body: JobCreateBody, store: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    jt = _job_type_from_str(body.job_type)
    jid = store.create_job(
        job_type=jt,
        title=body.title,
        config=body.config,
        skip_item_review=body.skip_item_review,
        priority=body.priority,
    )
    row = store.get_job(jid)
    assert row
    audit_log("create", "job", jid)
    return _job_to_summary(row, store)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    job_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    store: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    jt_filter: Optional[JobType] = _job_type_from_str(job_type) if job_type else None
    rows, total = store.list_jobs(job_type=jt_filter, page=page, page_size=page_size)
    jobs = [_job_to_summary(r, store) for r in rows]
    return {"jobs": jobs, "total": total, "page": page, "page_size": page_size}


UPDATABLE_JOB_STATUSES = frozenset(
    {
        JobStatus.DRAFT.value,
        JobStatus.QUEUED.value,
        JobStatus.RUNNING.value,
        JobStatus.AWAITING_REVIEW.value,
    }
)


@router.put("/{job_id}", response_model=JobResponse)
async def update_job_draft(
    job_id: str,
    body: JobUpdateBody,
    store: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    row = store.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    if row["status"] not in UPDATABLE_JOB_STATUSES:
        raise HTTPException(status_code=400, detail="terminal jobs cannot be updated")
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        return _job_to_summary(row, store)
    if not store.update_job_draft(job_id, patch):
        raise HTTPException(status_code=400, detail="nothing to update")
    store.touch_job_updated(job_id)
    row2 = store.get_job(job_id)
    assert row2
    return _job_to_summary(row2, store)


@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job_detail(job_id: str, store: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    row = store.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    items = store.list_items(job_id)
    base = _job_to_summary(row, store)
    base["items"] = [_item_to_out(i) for i in items]
    return base


@router.post("/{job_id}/items", response_model=JobItemResponse)
async def add_job_item(
    job_id: str,
    body: JobItemAddBody,
    store: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    row = store.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    if row["status"] not in (JobStatus.DRAFT.value,):
        raise HTTPException(status_code=400, detail="only draft jobs accept new items")
    iid = store.add_item(job_id, body.file_id, sort_order=body.sort_order)
    store.touch_job_updated(job_id)
    ir = store.get_item(iid)
    assert ir
    return _item_to_out(ir)


@router.post("/{job_id}/submit", response_model=JobResponse)
async def submit_job(job_id: str, store: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    row = store.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    items = store.list_items(job_id)
    if not items:
        raise HTTPException(status_code=400, detail="no items to submit")
    try:
        store.submit_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 将所有 PENDING item 入队
    for it in store.list_items(job_id):
        if it["status"] == JobItemStatus.PENDING.value:
            _enqueue_task("recognition", job_id, it["id"], it["file_id"])
    row2 = store.get_job(job_id)
    assert row2
    return _job_to_summary(row2, store)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: str, store: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    row = store.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    store.cancel_job(job_id)
    row2 = store.get_job(job_id)
    assert row2
    return _job_to_summary(row2, store)


@router.post("/{job_id}/requeue-failed", response_model=JobResponse)
async def requeue_failed_items(job_id: str, store: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    """将该 Job 下所有 FAILED 的 item 重新设为 QUEUED，由 Worker 重新处理。"""
    from app.services.job_store import InvalidStatusTransition

    row = store.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
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
        raise HTTPException(status_code=409, detail="没有失败的项可以重新排队")
    if count == 0 and errors:
        raise HTTPException(status_code=409, detail=f"状态转换失败: {'; '.join(errors)}")
    # 把 job 拉回可运行状态让 worker 继续
    try:
        job_status = row["status"]
        if job_status in (JobStatus.FAILED.value, JobStatus.COMPLETED.value):
            store.update_job_status(job_id, JobStatus.QUEUED)
        elif job_status == JobStatus.CANCELLED.value:
            pass  # 已取消的 job 不动
        # RUNNING / QUEUED / AWAITING_REVIEW 等状态无需变更，worker 会自动拾取 QUEUED 的 item
    except InvalidStatusTransition:
        pass  # job 状态不允许转换时忽略，item 已经 requeue 了
    audit_log("requeue_failed", "job", job_id, detail={"requeued_count": count})
    # 重新入队
    for it in store.list_items(job_id):
        if it["status"] == JobItemStatus.PENDING.value:
            _enqueue_task("recognition", job_id, it["id"], it["file_id"])
    row2 = store.get_job(job_id)
    assert row2
    return _job_to_summary(row2, store)


@router.delete("/{job_id}", response_model=JobDeleteResponse)
async def delete_job(job_id: str, store: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    row = store.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    if row["status"] not in DELETABLE_JOB_STATUSES:
        raise HTTPException(status_code=409, detail="active jobs must be cancelled before deletion")

    items = store.list_items(job_id)
    try:
        store.delete_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    detached_file_count = await _detach_job_from_files(job_id, items)
    audit_log("delete", "job", job_id)
    return {
        "id": job_id,
        "deleted": True,
        "deleted_item_count": len(items),
        "detached_file_count": detached_file_count,
    }


@router.get("/{job_id}/items/{item_id}/review-draft", response_model=ReviewDraftResponse)
async def get_item_review_draft(
    job_id: str,
    item_id: str,
    store: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    _get_job_and_item(store, job_id, item_id)
    return _review_draft_response(store, item_id)


@router.put("/{job_id}/items/{item_id}/review-draft", response_model=ReviewDraftResponse)
async def put_item_review_draft(
    job_id: str,
    item_id: str,
    body: ReviewDraftBody,
    store: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    _get_job_and_item(store, job_id, item_id)
    payload = body.model_dump(mode="json")
    store.save_item_review_draft(item_id, payload)
    store.touch_job_updated(job_id)
    return _review_draft_response(store, item_id)


@router.post("/{job_id}/items/{item_id}/review/approve", response_model=JobItemResponse)
async def approve_item_review(
    job_id: str,
    item_id: str,
    store: JobStore = Depends(get_job_store),
    reviewer: str = "local",
) -> dict[str, Any]:
    _get_job_and_item(store, job_id, item_id)
    try:
        store.approve_item_review(item_id, reviewer=reviewer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ir = store.get_item(item_id)
    assert ir
    store.touch_job_updated(job_id)
    _refresh_job_status(store, job_id)
    # 触发脱敏任务
    _enqueue_task("redaction", job_id, item_id, ir["file_id"])
    return _item_to_out(ir)


@router.post("/{job_id}/items/{item_id}/review/reject", response_model=JobItemResponse)
async def reject_item_review(
    job_id: str,
    item_id: str,
    store: JobStore = Depends(get_job_store),
    reviewer: str = "local",
) -> dict[str, Any]:
    _get_job_and_item(store, job_id, item_id)
    try:
        store.reject_item_review(item_id, reviewer=reviewer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ir = store.get_item(item_id)
    assert ir
    store.touch_job_updated(job_id)
    _refresh_job_status(store, job_id)
    # 打回重跑：重新识别
    _enqueue_task("recognition", job_id, item_id, ir["file_id"])
    return _item_to_out(ir)


@router.post("/{job_id}/items/{item_id}/review/commit", response_model=JobItemResponse)
async def commit_item_review(
    job_id: str,
    item_id: str,
    body: ReviewCommitBody,
    store: JobStore = Depends(get_job_store),
    reviewer: str = "local",
) -> dict[str, Any]:
    job, item = _get_job_and_item(store, job_id, item_id)
    if item["status"] in (JobItemStatus.CANCELLED.value, JobItemStatus.FAILED.value):
        raise HTTPException(status_code=400, detail=f"item not committable: {item['status']}")
    if item["status"] == JobItemStatus.COMPLETED.value:
        return _item_to_out(item)

    payload = body.model_dump(mode="json")
    store.save_item_review_draft(item_id, payload)
    # 本地识别模式下 item 可能仍为 pending，需先推到 awaiting_review 再转 redacting
    if item["status"] == JobItemStatus.PENDING.value:
        store.update_item_status(item_id, JobItemStatus.AWAITING_REVIEW)
    store.mark_item_redacting(item_id)
    store.touch_job_updated(job_id)
    _refresh_job_status(store, job_id)

    import app.api.redaction as redaction_mod
    from app.api.files import _file_store_lock, file_store

    async with _file_store_lock:
        file_info = file_store.get(item["file_id"])
    if not file_info:
        store.update_item_status(item_id, JobItemStatus.AWAITING_REVIEW, error_message="file not found")
        _refresh_job_status(store, job_id)
        raise HTTPException(status_code=404, detail="file not found")

    config = _build_redaction_config(job)

    from app.models.schemas import RedactionRequest

    try:
        result = await redaction_mod.execute_redaction(
            RedactionRequest(
                file_id=item["file_id"],
                entities=body.entities,
                bounding_boxes=body.bounding_boxes,
                config=config,
            )
        )
        async with _file_store_lock:
            # Re-read from file_store — execute_redaction already wrote output_path, entity_map, etc.
            info = file_store.get(item["file_id"])
            if info is None:
                info = dict(file_info)
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "commit_item_review: stored_info.output_path=%r, result.output_path=%r, result.output_file_id=%r, file_info.file_path=%r",
                info.get("output_path"), getattr(result, "output_path", "N/A"), getattr(result, "output_file_id", "N/A"), file_info.get("file_path"),
            )
            output_path = _resolve_committed_output_path(file_info, result, info)
            if not output_path:
                raise RuntimeError(f"redacted output missing after review commit: stored_output={info.get('output_path')!r}, result_attrs={[a for a in dir(result) if not a.startswith('_')]}")
            info["output_path"] = output_path
            if not info.get("entity_map"):
                info["entity_map"] = getattr(result, "entity_map", {}) or {}
            if not info.get("redacted_count"):
                info["redacted_count"] = int(getattr(result, "redacted_count", 0) or 0)
            info["entities"] = to_jsonable(body.entities)
            info["bounding_boxes"] = _group_boxes_by_page(body.bounding_boxes)
            file_store.set(item["file_id"], info)

        store.complete_item_review(item_id, reviewer=reviewer)
        store.touch_job_updated(job_id)
        _refresh_job_status(store, job_id)
    except HTTPException as exc:
        import traceback, logging
        logging.getLogger(__name__).error("commit_item_review HTTPException for item %s: %s\n%s", item_id, exc.detail, traceback.format_exc())
        try:
            store.update_item_status(item_id, JobItemStatus.AWAITING_REVIEW, error_message="review commit failed")
        except Exception:
            store.update_item_status(item_id, JobItemStatus.FAILED, error_message=f"review commit failed: {exc.detail}")
        store.touch_job_updated(job_id)
        _refresh_job_status(store, job_id)
        raise
    except Exception as exc:
        import traceback, logging
        logging.getLogger(__name__).error("commit_item_review Exception for item %s: %s\n%s", item_id, str(exc), traceback.format_exc())
        try:
            store.update_item_status(item_id, JobItemStatus.AWAITING_REVIEW, error_message=str(exc))
        except Exception:
            store.update_item_status(item_id, JobItemStatus.FAILED, error_message=str(exc))
        store.touch_job_updated(job_id)
        _refresh_job_status(store, job_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    item_done = store.get_item(item_id)
    assert item_done
    return _item_to_out(item_done)


@router.get("/{job_id}/stream")
async def stream_job_progress(job_id: str, store: JobStore = Depends(get_job_store)):
    """SSE stream for real-time job progress updates."""
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        last_data = None
        while True:
            job = store.get_job(job_id)
            if not job:
                yield f"data: {json.dumps({'error': 'job_not_found'})}\n\n"
                break

            items = store.list_items(job_id)
            progress = _progress_from_items(items)
            progress["status"] = job["status"]

            current_data = json.dumps(progress, ensure_ascii=False)
            if current_data != last_data:
                yield f"data: {current_data}\n\n"
                last_data = current_data

            # Terminal states - send final and close
            if job["status"] in ("completed", "failed", "cancelled"):
                break

            await asyncio.sleep(1.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
