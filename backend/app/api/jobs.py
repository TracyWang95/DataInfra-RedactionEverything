"""
Batch job API: draft creation, queue submission, review draft persistence, and review commit.

Thin routing layer — business logic lives in
app.services.job_management_service.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

import app.services.job_management_service as _jms
from app.core.audit import audit_log
from app.core.auth import require_auth, require_bulk_confirm
from app.models.errors import ConflictError, NotFoundError, ValidationError
from app.models.schemas import (
    BatchDetailsBody,
    BatchDetailsResponse,
    JobCreateBody,
    JobDeleteResponse,
    JobDetailResponse,
    JobExportReportResponse,
    JobItemResponse,
    JobListResponse,
    JobResponse,
    JobUpdateBody,
    ReviewCommitBody,
    ReviewDraftBody,
    ReviewDraftResponse,
)
from app.services.job_store import JobItemStatus, JobStatus, JobStore, get_job_store

router = APIRouter(prefix="/jobs", tags=["batch jobs"])


def _sorted_recognition_pages(performance: dict[str, Any]) -> list[dict[str, Any]]:
    recognition = performance.get("recognition")
    if not isinstance(recognition, dict):
        return []
    pages = recognition.get("pages")
    if isinstance(pages, list):
        return [p for p in pages if isinstance(p, dict)]
    if not isinstance(pages, dict):
        return []

    def page_key(item: tuple[str, Any]) -> int:
        value = item[1]
        raw_page = value.get("page", item[0]) if isinstance(value, dict) else item[0]
        try:
            return int(raw_page)
        except (TypeError, ValueError):
            return 0

    sorted_pages: list[dict[str, Any]] = []
    for key, value in sorted(pages.items(), key=page_key):
        if not isinstance(value, dict):
            continue
        page = dict(value)
        page.setdefault("page", page_key((key, value)))
        sorted_pages.append(page)
    return sorted_pages


def _sum_page_durations_ms(pages: list[dict[str, Any]]) -> int:
    total = 0
    for page in pages:
        if not isinstance(page, dict):
            continue
        try:
            total += int(page.get("duration_ms") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _duration_aliases(performance: dict[str, Any]) -> dict[str, Any]:
    recognition = performance.get("recognition") if isinstance(performance.get("recognition"), dict) else {}
    redaction = performance.get("redaction") if isinstance(performance.get("redaction"), dict) else {}
    queue = performance.get("queue") if isinstance(performance.get("queue"), dict) else {}
    queue_wait = recognition.get("queue_wait_ms") if isinstance(recognition, dict) else None
    if queue_wait is None and isinstance(queue, dict):
        queue_wait = queue.get("last_wait_ms")
    recognition_pages = _sorted_recognition_pages(performance)
    page_duration_sum_ms = _sum_page_durations_ms(recognition_pages)
    recognition_duration_ms = recognition.get("duration_ms") if isinstance(recognition, dict) else None
    recognition_wall_ms = recognition.get("vision_ms") if isinstance(recognition, dict) else None
    if not isinstance(recognition_wall_ms, (int, float)) or recognition_wall_ms <= 0:
        recognition_wall_ms = recognition_duration_ms
    parallelism_ratio = None
    if (
        isinstance(recognition_wall_ms, (int, float))
        and recognition_wall_ms > 0
        and page_duration_sum_ms > 0
    ):
        parallelism_ratio = round(page_duration_sum_ms / recognition_wall_ms, 2)
    return {
        "queue_wait_ms": queue_wait,
        "recognition_duration_ms": recognition_duration_ms,
        "redaction_duration_ms": redaction.get("duration_ms") if isinstance(redaction, dict) else None,
        "recognition_pages": recognition_pages,
        "recognition_page_concurrency": recognition.get("page_concurrency") if isinstance(recognition, dict) else None,
        "recognition_page_concurrency_configured": (
            recognition.get("page_concurrency_configured") if isinstance(recognition, dict) else None
        ),
        "recognition_page_duration_sum_ms": page_duration_sum_ms or None,
        "recognition_parallelism_ratio": parallelism_ratio,
    }


def _enrich_job_detail_with_performance(detail: dict[str, Any], store: JobStore) -> dict[str, Any]:
    job_id = str(detail.get("id") or "")
    if not job_id:
        return detail
    try:
        performance_by_item = store.get_item_performance_map(job_id)
    except Exception:
        logger.debug("unable to load job performance diagnostics for job %s", job_id, exc_info=True)
        return detail
    for item in detail.get("items") or []:
        if not isinstance(item, dict):
            continue
        performance = performance_by_item.get(str(item.get("id"))) or {}
        item["performance"] = performance
        item.update(_duration_aliases(performance))
    return detail


@router.post("", response_model=JobResponse)
async def create_job(
    body: JobCreateBody,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    try:
        result = _jms.create_job(
            store=store,
            job_type_str=body.job_type,
            title=body.title,
            config=body.config,
            skip_item_review=body.skip_item_review,
            priority=0,
            owner_id=owner_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit_log("create", "job", result["id"])
    return result


@router.get("", response_model=JobListResponse)
async def list_jobs(
    job_type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    try:
        return _jms.list_jobs(store, job_type, page, page_size, status, owner_id=owner_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/batch-details", response_model=BatchDetailsResponse)
async def batch_job_details(
    body: BatchDetailsBody,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    """Return full details for multiple jobs in a single request.

    Unknown IDs are silently skipped (no 404). Duplicates are deduplicated.
    """
    unique_ids = list(dict.fromkeys(body.ids))  # deduplicate, preserve order
    results: list[dict[str, Any]] = []
    for jid in unique_ids:
        try:
            detail = _jms.get_job_detail(store, jid, owner_id=owner_id)
            results.append(_enrich_job_detail_with_performance(detail, store))
        except ValueError:
            # Job not found — skip silently
            continue
    return {"jobs": results}


@router.put("/{job_id}", response_model=JobResponse)
async def update_job_draft(
    job_id: str,
    body: JobUpdateBody,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    patch = body.model_dump(exclude_unset=True)
    try:
        _jms.assert_job_owner(store.get_job(job_id), owner_id)
        return _jms.update_draft(store, job_id, patch)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job_detail(
    job_id: str,
    performance: bool = Query(
        True,
        description="false=轻量模式（不带每文件性能数据）。万级任务全量载荷可达 38MB，"
        "向导恢复/轮询只需 items 的状态字段。",
    ),
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    try:
        detail = _jms.get_job_detail(store, job_id, owner_id=owner_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not performance:
        for item in detail.get("items") or []:
            if isinstance(item, dict):
                item.pop("performance", None)
        return detail
    return _enrich_job_detail_with_performance(detail, store)


@router.get("/{job_id}/export-report", response_model=JobExportReportResponse)
async def get_job_export_report(
    job_id: str,
    file_ids: list[str] | None = Query(
        None,
        description=(
            "Optional repeated file id filter. When omitted, the report selects every file in the job. "
            "The response still includes all job files; use files[].selected_for_export and files[].delivery_status "
            "to distinguish selected, actionable, and not_selected files."
        ),
    ),
    summary_only: bool = Query(
        False,
        description="True 时只返回聚合汇总（files 为空数组）——十万级 item 的 job 请用它 + 明细 CSV 导出。",
    ),
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    _jms.assert_job_owner(store.get_job(job_id), owner_id)
    if file_ids is not None:
        unique_file_ids = list(dict.fromkeys(file_ids))
        if not store.get_job(job_id):
            raise HTTPException(status_code=404, detail="job not found")
        job_file_ids = {str(item["file_id"]) for item in store.list_items(job_id)}
        missing_from_job = [file_id for file_id in unique_file_ids if file_id not in job_file_ids]
        if missing_from_job:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "export report file selection does not belong to the job",
                    "missing": missing_from_job,
                },
            )
        file_ids = unique_file_ids
    try:
        return _jms.build_export_report(
            store, job_id, selected_file_ids=file_ids, include_files=not summary_only
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{job_id}/export-data", status_code=202)
async def export_job_data(
    job_id: str,
    file_ids: list[str] | None = Body(None, embed=True),
    include_entities: bool = Body(True, embed=True),
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    """异步导出批量结果明细：summary.json + files-partNN.csv (+ entities-partNN.csv)。

    进度与下载复用 /files/batch/export/{export_id}(/volumes/{name}) 端点。
    """
    row = store.get_job(job_id)
    _jms.assert_job_owner(row, owner_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    import app.services.export_service as _export

    task = _export.export_task_manager.submit(
        owner_id=owner_id,
        kind="job_data",
        runner=_export.make_job_data_runner(store, job_id, file_ids, include_entities),
        title=f"job_data_{job_id[:8]}",
    )
    audit_log("export", "job_data", task.export_id, detail={"job_id": job_id})
    return task.public()


@router.post("/{job_id}/submit", response_model=JobResponse)
async def submit_job(
    job_id: str,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    try:
        _jms.assert_job_owner(store.get_job(job_id), owner_id)
        return _jms.submit_job(store, job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: str,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    try:
        _jms.assert_job_owner(store.get_job(job_id), owner_id)
        return _jms.cancel_job(store, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{job_id}/requeue-failed", response_model=JobResponse)
async def requeue_failed_items(
    job_id: str,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    """将该 Job 下所有 FAILED 的 item 重新设为 QUEUED，由 Worker 重新处理。"""
    try:
        _jms.assert_job_owner(store.get_job(job_id), owner_id)
        result = _jms.requeue_failed(store, job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit_log("requeue_failed", "job", job_id)
    return result


@router.delete("/{job_id}", response_model=JobDeleteResponse)
async def delete_job(
    job_id: str,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    try:
        _jms.assert_job_owner(store.get_job(job_id), owner_id)
        result = await _jms.delete_job(store, job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit_log("delete", "job", job_id)
    return result


@router.delete("/{job_id}/items/{item_id}")
async def delete_job_item(
    job_id: str,
    item_id: str,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    """Remove an item from a draft batch job and delete its underlying file."""
    job = store.get_job(job_id)
    if not job or str(job.get("owner_id") or "local_user") != owner_id:
        raise HTTPException(status_code=404, detail="job not found")
    if job.get("status") != JobStatus.DRAFT.value:
        raise HTTPException(status_code=409, detail="only draft jobs allow item deletion")
    item = store.get_item(item_id)
    if not item or item.get("job_id") != job_id:
        raise HTTPException(status_code=404, detail="item not found")
    deleted = store.delete_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="item not found")
    file_id = deleted.get("file_id")
    if file_id:
        from app.services.file_management_service import delete_file as _delete_file
        try:
            await _delete_file(file_id)
        except Exception as exc:  # best-effort cleanup; item row is already gone
            logger.warning("job item %s: file %s cleanup failed: %s", item_id, file_id, exc)
    audit_log("delete", "job_item", item_id, detail={"job_id": job_id, "file_id": file_id})
    return {"deleted": True, "item_id": item_id, "file_id": file_id}


@router.get("/{job_id}/items/{item_id}/review-draft", response_model=ReviewDraftResponse)
async def get_item_review_draft(
    job_id: str,
    item_id: str,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    try:
        _jms.assert_job_owner(store.get_job(job_id), owner_id)
        return _jms.get_review_draft(store, job_id, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/{job_id}/items/{item_id}/review-draft", response_model=ReviewDraftResponse)
async def put_item_review_draft(
    job_id: str,
    item_id: str,
    body: ReviewDraftBody,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
) -> dict[str, Any]:
    try:
        _jms.assert_job_owner(store.get_job(job_id), owner_id)
        payload = body.model_dump(mode="json")
        return _jms.save_review_draft(store, job_id, item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{job_id}/items/{item_id}/review/approve", response_model=JobItemResponse)
async def approve_item_review(
    job_id: str,
    item_id: str,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
    reviewer: str = "local",
) -> dict[str, Any]:
    try:
        _jms.assert_job_owner(store.get_job(job_id), owner_id)
        return _jms.approve_review(store, job_id, item_id, reviewer=owner_id or reviewer)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{job_id}/items/{item_id}/review/reject", response_model=JobItemResponse)
async def reject_item_review(
    job_id: str,
    item_id: str,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
    reviewer: str = "local",
) -> dict[str, Any]:
    try:
        _jms.assert_job_owner(store.get_job(job_id), owner_id)
        return _jms.reject_review(store, job_id, item_id, reviewer=owner_id or reviewer)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{job_id}/items/{item_id}/review/commit", response_model=JobItemResponse)
async def commit_item_review(
    job_id: str,
    item_id: str,
    body: ReviewCommitBody,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
    reviewer: str = "local",
) -> dict[str, Any]:
    payload = body.model_dump(mode="json")
    try:
        _jms.assert_job_owner(store.get_job(job_id), owner_id)
        return await _jms.commit_review(
            store=store,
            job_id=job_id,
            item_id=item_id,
            entities=body.entities,
            bounding_boxes=body.bounding_boxes,
            payload=payload,
            reviewer=owner_id or reviewer,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{job_id}/review/commit-all", response_model=dict)
async def commit_all_item_reviews(
    job_id: str,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_bulk_confirm),
) -> dict[str, Any]:
    """Batch one-click confirm: approve every awaiting-review item in the job.

    Gated by the per-user ``bulk_confirm`` permission (super admins always pass).
    万级 job 在后台执行（批量事务 + 逐条入队仍要几十秒），立即返回
    total_awaiting；前端靠既有轮询看着 已确认 计数爬升。重复调用幂等
    （bulk approve 带 status 守卫）。
    """
    try:
        _jms.assert_job_owner(store.get_job(job_id), owner_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    awaiting_count = sum(
        1
        for it in store.list_items(job_id)
        if it["status"] == JobItemStatus.AWAITING_REVIEW.value
    )
    if awaiting_count == 0:
        return {
            "job_id": job_id,
            "total_awaiting": 0,
            "confirmed": 0,
            "failed": [],
            "started": False,
        }

    async def _run_commit_all() -> None:
        try:
            result = await _jms.commit_all_reviews(store, job_id, reviewer=owner_id)
            audit_log(
                "commit_all",
                "job",
                job_id,
                detail={
                    "confirmed": result.get("confirmed"),
                    "failed": len(result.get("failed") or []),
                },
            )
        except Exception:
            logger.exception("commit-all background task failed for job %s", job_id[:8])

    asyncio.create_task(_run_commit_all())
    return {
        "job_id": job_id,
        "total_awaiting": awaiting_count,
        "confirmed": 0,
        "failed": [],
        "started": True,
    }


@router.get("/{job_id}/stream")
async def stream_job_progress(
    job_id: str,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
):
    """SSE stream for real-time job progress updates."""
    job = store.get_job(job_id)
    _jms.assert_job_owner(job, owner_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        last_data = None
        last_sent = time.monotonic()
        while True:
            job = store.get_job(job_id)
            if not job:
                yield f"data: {json.dumps({'error': 'job_not_found'})}\n\n"
                break

            items = store.list_items(job_id)
            progress = _jms.progress_from_items(items)
            progress["status"] = job["status"]

            current_data = json.dumps(progress, ensure_ascii=False)
            if current_data != last_data:
                yield f"data: {current_data}\n\n"
                last_data = current_data
                last_sent = time.monotonic()
            elif time.monotonic() - last_sent >= 15.0:
                # Periodic SSE comment so a dropped client surfaces as
                # CancelledError instead of leaking this coroutine forever.
                yield ": keep-alive\n\n"
                last_sent = time.monotonic()

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
