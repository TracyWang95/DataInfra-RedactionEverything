# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
Batch job API: draft creation, queue submission, review draft persistence, and review commit.

Thin routing layer — business logic lives in
app.services.job_management_service.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from app.core.audit import audit_log
from app.models.schemas import (
    JobResponse, JobItemResponse, JobListResponse, JobDetailResponse,
    JobDeleteResponse, JobProgressResponse, ReviewDraftResponse,
    JobCreateBody, JobItemAddBody, JobUpdateBody, ReviewDraftBody, ReviewCommitBody,
)
from app.services.job_store import JobStore, get_job_store

import app.services.job_management_service as _jms

router = APIRouter(prefix="/jobs", tags=["batch jobs"])


@router.post("", response_model=JobResponse)
async def create_job(body: JobCreateBody, store: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    try:
        result = _jms.create_job(
            store=store,
            job_type_str=body.job_type,
            title=body.title,
            config=body.config,
            skip_item_review=body.skip_item_review,
            priority=body.priority,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit_log("create", "job", result["id"])
    return result


@router.get("", response_model=JobListResponse)
async def list_jobs(
    job_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    store: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    try:
        return _jms.list_jobs(store, job_type, page, page_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{job_id}", response_model=JobResponse)
async def update_job_draft(
    job_id: str,
    body: JobUpdateBody,
    store: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    patch = body.model_dump(exclude_unset=True)
    try:
        return _jms.update_draft(store, job_id, patch)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job_detail(job_id: str, store: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    try:
        return _jms.get_job_detail(store, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{job_id}/items", response_model=JobItemResponse)
async def add_job_item(
    job_id: str,
    body: JobItemAddBody,
    store: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    try:
        return _jms.add_item(store, job_id, body.file_id, sort_order=body.sort_order)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.post("/{job_id}/submit", response_model=JobResponse)
async def submit_job(job_id: str, store: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    try:
        return _jms.submit_job(store, job_id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: str, store: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    try:
        return _jms.cancel_job(store, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{job_id}/requeue-failed", response_model=JobResponse)
async def requeue_failed_items(job_id: str, store: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    """将该 Job 下所有 FAILED 的 item 重新设为 QUEUED，由 Worker 重新处理。"""
    try:
        result = _jms.requeue_failed(store, job_id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        if "没有失败" in detail or "状态转换" in detail:
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    audit_log("requeue_failed", "job", job_id)
    return result


@router.delete("/{job_id}", response_model=JobDeleteResponse)
async def delete_job(job_id: str, store: JobStore = Depends(get_job_store)) -> dict[str, Any]:
    try:
        result = await _jms.delete_job(store, job_id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        if "must be cancelled" in detail:
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    audit_log("delete", "job", job_id)
    return result


@router.get("/{job_id}/items/{item_id}/review-draft", response_model=ReviewDraftResponse)
async def get_item_review_draft(
    job_id: str,
    item_id: str,
    store: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    try:
        return _jms.get_review_draft(store, job_id, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/{job_id}/items/{item_id}/review-draft", response_model=ReviewDraftResponse)
async def put_item_review_draft(
    job_id: str,
    item_id: str,
    body: ReviewDraftBody,
    store: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    try:
        payload = body.model_dump(mode="json")
        return _jms.save_review_draft(store, job_id, item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{job_id}/items/{item_id}/review/approve", response_model=JobItemResponse)
async def approve_item_review(
    job_id: str,
    item_id: str,
    store: JobStore = Depends(get_job_store),
    reviewer: str = "local",
) -> dict[str, Any]:
    try:
        return _jms.approve_review(store, job_id, item_id, reviewer=reviewer)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.post("/{job_id}/items/{item_id}/review/reject", response_model=JobItemResponse)
async def reject_item_review(
    job_id: str,
    item_id: str,
    store: JobStore = Depends(get_job_store),
    reviewer: str = "local",
) -> dict[str, Any]:
    try:
        return _jms.reject_review(store, job_id, item_id, reviewer=reviewer)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.post("/{job_id}/items/{item_id}/review/commit", response_model=JobItemResponse)
async def commit_item_review(
    job_id: str,
    item_id: str,
    body: ReviewCommitBody,
    store: JobStore = Depends(get_job_store),
    reviewer: str = "local",
) -> dict[str, Any]:
    payload = body.model_dump(mode="json")
    try:
        return await _jms.commit_review(
            store=store,
            job_id=job_id,
            item_id=item_id,
            entities=body.entities,
            bounding_boxes=body.bounding_boxes,
            payload=payload,
            reviewer=reviewer,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        if "not committable" in detail:
            raise HTTPException(status_code=400, detail=detail)
        raise HTTPException(status_code=500, detail=detail)


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
            progress = _jms.progress_from_items(items)
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
