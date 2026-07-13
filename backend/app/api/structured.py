"""Structured table de-identification API."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.responses import FileResponse

import app.services.job_management_service as job_service
from app.core.audit import audit_log
from app.core.auth import require_auth
from app.models.schemas import (
    StructuredConnectionCreate,
    StructuredConnectionOut,
    StructuredConnectionTestRequest,
    StructuredConnectionTestResponse,
    StructuredDatasetsResponse,
    StructuredJobCreate,
    StructuredJobResponse,
    StructuredPolicyBody,
    StructuredPolicyResponse,
    StructuredPreviewResponse,
    StructuredProfileResponse,
    StructuredSourcesResponse,
)
from app.services import structured_service
from app.services.job_store import JobStore, get_job_store
from app.services.structured_store import StructuredStore, get_structured_store

router = APIRouter(prefix="/structured", tags=["structured redaction"])


class StructuredDatasetSelection(BaseModel):
    schema_name: str | None = None
    table_name: str | None = None
    name: str | None = None


class StructuredDatasetRegisterBody(BaseModel):
    datasets: list[StructuredDatasetSelection] = Field(default_factory=list)


def _error(exc: Exception, *, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


def _value_error_status(exc: ValueError) -> int:
    return 404 if "not found" in str(exc).lower() else 400


@router.post("/files")
async def upload_structured_file(
    file: UploadFile = File(...),
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    try:
        # 早校验扩展名，避免为不支持的类型读入整个文件体
        structured_service.extension_kind(file.filename)
        # 流式落盘 + STRUCTURED_MAX_FILE_SIZE 上限（此前整读进内存且无大小校验）
        path, kind = structured_service.save_structured_upload_stream(
            owner_id=owner_id,
            filename=file.filename,
            fileobj=file.file,
        )
        result = structured_service.register_file_source(
            owner_id=owner_id,
            filename=file.filename or os.path.basename(path),
            file_path=path,
            kind=kind,
            store=store,
        )
    except ValueError as exc:
        raise _error(exc)
    audit_log("create", "structured_source", result["source"]["id"])
    return result


@router.get("/sources", response_model=StructuredSourcesResponse)
async def list_sources(
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    return {"sources": store.list_sources(owner_id=owner_id)}


@router.get("/sources/{source_id}/datasets", response_model=StructuredDatasetsResponse)
async def list_source_datasets(
    source_id: str,
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    if not store.get_source(source_id, owner_id=owner_id):
        raise HTTPException(status_code=404, detail="source not found")
    return {"datasets": store.list_datasets(owner_id=owner_id, source_id=source_id)}


@router.get("/datasets", response_model=StructuredDatasetsResponse)
async def list_datasets(
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    return {"datasets": store.list_datasets(owner_id=owner_id)}


@router.post("/connections/test", response_model=StructuredConnectionTestResponse)
async def test_connection(body: StructuredConnectionTestRequest) -> dict[str, Any]:
    try:
        return structured_service.test_connection(body.model_dump())
    except Exception as exc:
        return {
            "ok": False,
            "message": str(exc),
            "engine": body.engine,
            "dataset_count": 0,
        }


@router.post("/connections", response_model=StructuredConnectionOut)
async def create_connection(
    body: StructuredConnectionCreate,
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    try:
        connection = structured_service.create_connection(
            owner_id=owner_id,
            payload=body.model_dump(),
            store=store,
        )
    except ValueError as exc:
        raise _error(exc)
    audit_log("create", "structured_connection", connection["id"])
    return connection


@router.get("/connections", response_model=list[StructuredConnectionOut])
async def list_connections(
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> list[dict[str, Any]]:
    return store.list_connections(owner_id=owner_id)


@router.delete("/connections/{connection_id}")
async def delete_connection(
    connection_id: str,
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    if not store.delete_connection(connection_id, owner_id=owner_id):
        raise HTTPException(status_code=404, detail="connection not found")
    audit_log("delete", "structured_connection", connection_id)
    return {"id": connection_id, "deleted": True}


# 回收站三件套（trash/restore/软删 DELETE 默认）为 R4 刻意能力：deleteStructuredDataset 默认软删进此处，
# 到期自动清；前端暂无 trash/restore UI（文件侧 trash-dialog.tsx 有完整对照，待接同款）。
# 勿删端点：删除将使软删数据集在保留期内不可恢复（唯一恢复通道）。
@router.get("/datasets/trash")
async def list_trashed_datasets(
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    """数据集回收站。注册在 /datasets/{dataset_id} 之前，避免被路径参数吞掉。"""
    from app.core.config import settings

    return {
        "items": store.list_trashed_datasets(owner_id=owner_id),
        "retention_days": int(settings.TRASH_RETENTION_DAYS),
    }


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(
    dataset_id: str,
    purge: bool = False,
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    """删除数据集：默认进回收站（软删）；purge=true 彻底删除（级联策略/画像）。
    共享源文件保留给同源兄弟数据集。"""
    if purge:
        if not store.delete_dataset(dataset_id, owner_id=owner_id):
            raise HTTPException(status_code=404, detail="dataset not found")
        audit_log("purge", "structured_dataset", dataset_id, user=owner_id)
        return {"id": dataset_id, "deleted": True}
    if not store.soft_delete_dataset(dataset_id, owner_id=owner_id):
        raise HTTPException(status_code=404, detail="dataset not found or already trashed")
    audit_log("soft_delete", "structured_dataset", dataset_id, user=owner_id)
    return {"id": dataset_id, "deleted": True, "trashed": True}


@router.post("/datasets/{dataset_id}/restore")
async def restore_dataset(
    dataset_id: str,
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    if not store.restore_dataset(dataset_id, owner_id=owner_id):
        raise HTTPException(status_code=404, detail="dataset not in trash")
    audit_log("restore", "structured_dataset", dataset_id, user=owner_id)
    return {"id": dataset_id, "restored": True}


@router.get("/connections/{connection_id}/datasets", response_model=StructuredDatasetsResponse)
async def discover_connection_datasets(
    connection_id: str,
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    try:
        datasets = structured_service.discover_connection_datasets(
            connection_id,
            owner_id=owner_id,
            store=store,
        )
    except ValueError as exc:
        raise _error(exc, status_code=404)
    return {"datasets": datasets}


@router.post("/connections/{connection_id}/datasets", response_model=StructuredDatasetsResponse)
async def register_connection_datasets(
    connection_id: str,
    body: StructuredDatasetRegisterBody,
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    try:
        datasets = structured_service.register_connection_datasets(
            connection_id,
            owner_id=owner_id,
            selections=[item.model_dump() for item in body.datasets],
            store=store,
        )
    except ValueError as exc:
        raise _error(exc, status_code=404)
    return {"datasets": datasets}


@router.post("/datasets/{dataset_id}/profile", response_model=StructuredProfileResponse)
async def profile_dataset(
    dataset_id: str,
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    try:
        return structured_service.profile_dataset(dataset_id, owner_id=owner_id, store=store)
    except ValueError as exc:
        raise _error(exc, status_code=404)


@router.get("/datasets/{dataset_id}/profile", response_model=StructuredProfileResponse)
async def get_profile(
    dataset_id: str,
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    profile = store.get_profile(dataset_id, owner_id=owner_id)
    if not profile:
        try:
            profile = structured_service.profile_dataset(dataset_id, owner_id=owner_id, store=store)
        except ValueError as exc:
            raise _error(exc, status_code=404)
    return profile


@router.put("/datasets/{dataset_id}/policy", response_model=StructuredPolicyResponse)
async def update_policy(
    dataset_id: str,
    body: StructuredPolicyBody,
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    try:
        return structured_service.save_policy(
            dataset_id,
            owner_id=owner_id,
            columns=[item.model_dump() for item in body.columns],
            store=store,
        )
    except ValueError as exc:
        raise _error(exc, status_code=_value_error_status(exc))


@router.get("/datasets/{dataset_id}/policy", response_model=StructuredPolicyResponse)
async def get_policy(
    dataset_id: str,
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    try:
        return structured_service.get_or_create_policy(dataset_id, owner_id=owner_id, store=store)
    except ValueError as exc:
        raise _error(exc, status_code=404)


@router.get("/datasets/{dataset_id}/preview", response_model=StructuredPreviewResponse)
async def preview_dataset(
    dataset_id: str,
    owner_id: str = Depends(require_auth),
    store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    try:
        return structured_service.preview_dataset(dataset_id, owner_id=owner_id, store=store)
    except ValueError as exc:
        raise _error(exc, status_code=404)


@router.post("/jobs", response_model=StructuredJobResponse)
async def create_structured_job(
    body: StructuredJobCreate,
    owner_id: str = Depends(require_auth),
    job_store: JobStore = Depends(get_job_store),
    structured_store: StructuredStore = Depends(get_structured_store),
) -> dict[str, Any]:
    datasets = []
    for dataset_id in body.dataset_ids:
        dataset = structured_store.get_dataset(dataset_id, owner_id=owner_id)
        if not dataset:
            raise HTTPException(status_code=404, detail=f"dataset not found: {dataset_id}")
        datasets.append(dataset)
    duplicate_ids = sorted({dataset_id for dataset_id in body.dataset_ids if body.dataset_ids.count(dataset_id) > 1})
    if duplicate_ids:
        dataset_by_id = {str(dataset["id"]): dataset for dataset in datasets}
        labels = [str(dataset_by_id.get(dataset_id, {}).get("name") or dataset_id) for dataset_id in duplicate_ids[:5]]
        raise HTTPException(
            status_code=400,
            detail=f"数据集不能重复选择：{', '.join(labels)}",
        )
    unreviewed = [dataset for dataset in datasets if not dataset.get("policy_reviewed_at")]
    if unreviewed:
        names = ", ".join(str(dataset.get("name") or dataset.get("id")) for dataset in unreviewed[:5])
        more = f" 等 {len(unreviewed)} 个数据集" if len(unreviewed) > 5 else ""
        raise HTTPException(status_code=400, detail=f"请先保存字段策略后再交付：{names}{more}")
    try:
        job = job_service.create_job(
            store=job_store,
            job_type_str="structured_batch",
            title=body.title or "Structured data redaction",
            config={
                "dataset_ids": body.dataset_ids,
                "export_format": body.export_format,
                "wizard_furthest_step": 3,
            },
            skip_item_review=body.skip_review,
            priority=0,
            owner_id=owner_id,
        )
        for index, dataset_id in enumerate(body.dataset_ids):
            job_service.add_item(job_store, job["id"], dataset_id, index)
        if body.auto_submit:
            job = job_service.submit_job(job_store, job["id"])
        else:
            job = job_service.get_job_detail(job_store, job["id"], owner_id=owner_id)
    except ValueError as exc:
        raise _error(exc)
    audit_log("create", "structured_job", job["id"])
    return {"job": job, "datasets": datasets}


@router.get("/jobs/{job_id}/export")
async def download_structured_job_export(
    job_id: str,
    owner_id: str = Depends(require_auth),
    job_store: JobStore = Depends(get_job_store),
    structured_store: StructuredStore = Depends(get_structured_store),
) -> FileResponse:
    job_service.assert_job_owner(job_store.get_job(job_id), owner_id)
    try:
        zip_path = structured_service.build_job_export_zip(
            owner_id=owner_id,
            job_id=job_id,
            store=structured_store,
        )
    except ValueError as exc:
        raise _error(exc, status_code=404)
    return FileResponse(zip_path, filename=os.path.basename(zip_path), media_type="application/zip")
