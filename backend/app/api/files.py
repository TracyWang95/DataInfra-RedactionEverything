"""
文件管理 API 路由
处理文件上传、下载、解析等操作

Thin routing layer — business logic lives in
app.services.file_management_service.
"""
import json
import logging
import os
import re
import shutil
import time
import uuid

import aiofiles
from pydantic import BaseModel

logger = logging.getLogger(__name__)


from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, Response

import app.services.export_service as _export
import app.services.file_management_service as _fms
import app.services.job_management_service as _jms
from app.api.jobs import get_job_store
from app.core.audit import audit_log
from app.core.auth import require_auth
from app.core.config import settings
from app.core.idempotency import check_idempotency, save_idempotency
from app.core.rate_limit import RateLimiter, make_user_throttle
from app.models.schemas import (
    APIResponse,
    BatchDownloadRequest,
    FileListResponse,
    FileUploadResponse,
    HybridNERRequest,
    NERRequest,
    NERResult,
    ParseResult,
)
from app.services.job_store import JobStore

router = APIRouter()

# R1-3 全局限流：按用户主体计数。上传只挂整文件与 resumable init（chunk 不
# 计数——万级批量的分块流量不受影响）；导出挂批量打包。速率 env 可调。
_upload_throttle = make_user_throttle(
    RateLimiter(max_requests=settings.UPLOAD_RATE_PER_MIN, window_seconds=60),
    "upload",
)
_export_throttle = make_user_throttle(
    RateLimiter(max_requests=settings.EXPORT_RATE_PER_MIN, window_seconds=60),
    "export",
)


def validate_file(file: UploadFile) -> None:
    """验证上传的文件"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，支持的类型: {settings.ALLOWED_EXTENSIONS}"
        )


@router.get("/files", response_model=FileListResponse)
async def list_files(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    source: str | None = Query(
        None,
        description="按来源筛选：playground（单文件流程，兼容旧 API 值）| batch（批量/任务）；不传为全部",
    ),
    embed_job: bool = Query(
        False,
        description="为 true 时对本页含 job_id 的行注入 job_embed（状态、类型、items 摘要），避免前端逐条 getJob",
    ),
    job_id: str | None = Query(None, description="按 job_id 筛选，仅返回属于该任务的文件"),
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
):
    """列出已上传文件（处理历史）；同批次文件相邻排列，支持分页与来源筛选。"""
    src_filter: str | None = None
    if source is not None and str(source).strip():
        s = str(source).strip().lower()
        if s not in ("playground", "batch"):
            raise HTTPException(status_code=400, detail="source 须为 playground 或 batch")
        src_filter = s

    # 如果指定了 job_id，先取该任务的所有 file_id 做白名单
    job_file_ids: set[str] | None = None
    if job_id:
        job = store.get_job(job_id)
        if not job or str(job.get("owner_id") or "local_user") != owner_id:
            raise HTTPException(status_code=404, detail="job not found")
        items = store.list_items(job_id)
        job_file_ids = {it["file_id"] for it in items}

    file_store = _fms.get_file_store()
    filtered_entries: list[tuple[str, dict]] = []
    for fid, info in file_store.items_for_owner(owner_id):
        if not isinstance(info, dict):
            continue
        if _fms.file_owner_id(info) != owner_id:
            continue
        if job_file_ids is not None and fid not in job_file_ids:
            continue
        eff = _fms.effective_upload_source(info)
        if src_filter and eff != src_filter:
            continue
        filtered_entries.append((fid, info))

    # 批量查找 item_status
    all_file_ids = [fid for fid, _ in filtered_entries]
    item_status_map = store.batch_find_item_statuses(all_file_ids)

    raw_items = _fms.build_file_list_items(filtered_entries, item_status_map)
    items = _fms.group_and_sort_items(raw_items)
    stats = {
        "total_files": len(items),
        "redacted_files": sum(1 for it in items if it.has_output),
        "awaiting_review_files": sum(
            1
            for it in items
            if str(it.item_status or "").lower() in {"awaiting_review", "review_approved"}
        ),
        "unredacted_files": sum(1 for it in items if not it.has_output),
        "entity_sum": sum(int(it.entity_count or 0) for it in items),
        "size_bytes": sum(int(it.file_size or 0) for it in items),
    }

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]

    if embed_job and page_items:
        embed_map = _fms.build_job_embed_map(page_items, store)
        if embed_map:
            page_items = [
                it.model_copy(update={"job_embed": embed_map[it.job_id]})
                if it.job_id and it.job_id in embed_map
                else it
                for it in page_items
            ]

    return FileListResponse(
        files=page_items,
        total=total,
        page=page,
        page_size=page_size,
        stats=stats,
    )


def _assert_batch_delivery_ready(
    request: BatchDownloadRequest,
    store: JobStore,
    owner_id: str,
) -> None:
    """redacted + job_id 时校验所选文件属于该 job 且全部 delivery-ready。"""
    if not (request.redacted and request.job_id):
        return
    unique_file_ids = list(dict.fromkeys(request.file_ids))
    job = store.get_job(request.job_id)
    if not job or str(job.get("owner_id") or "local_user") != owner_id:
        raise HTTPException(status_code=404, detail="job not found")
    job_file_ids = {str(item["file_id"]) for item in store.list_items(request.job_id)}
    missing_from_job = [file_id for file_id in unique_file_ids if file_id not in job_file_ids]
    if missing_from_job:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "redacted export file selection does not belong to the job",
                "missing": missing_from_job,
            },
        )
    try:
        report = _jms.build_export_report(
            store,
            request.job_id,
            selected_file_ids=unique_file_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not report.get("summary", {}).get("ready_for_delivery"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "redacted export is not ready for delivery",
                "summary": report.get("summary", {}),
                "redacted_zip": report.get("redacted_zip", {}),
            },
        )


@router.post("/files/batch/download", dependencies=[Depends(_export_throttle)])
async def batch_download_zip(
    request: BatchDownloadRequest,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
):
    """将多个文件打包为 ZIP 下载（小批量同步路径；大批量走异步分卷导出）。"""
    _assert_batch_delivery_ready(request, store, owner_id)
    if len(request.file_ids) > int(settings.EXPORT_SYNC_MAX_FILES):
        raise HTTPException(
            status_code=413,
            detail={
                "message": "文件数超出同步打包上限，请使用异步导出",
                "use_async_export": True,
                "sync_max_files": int(settings.EXPORT_SYNC_MAX_FILES),
            },
        )
    entries, _pre_manifest = _fms.collect_batch_zip_entries(request, owner_id=owner_id)
    if sum(size for _p, _a, size in entries) > int(settings.EXPORT_SYNC_MAX_BYTES):
        raise HTTPException(
            status_code=413,
            detail={
                "message": "总体积超出同步打包上限，请使用异步导出",
                "use_async_export": True,
                "sync_max_bytes": int(settings.EXPORT_SYNC_MAX_BYTES),
            },
        )
    try:
        zip_bytes, filename, manifest = _fms.build_batch_zip(request, owner_id=owner_id)
    except ValueError as exc:
        detail = exc.args[0] if exc.args else str(exc)
        if isinstance(detail, list):
            raise HTTPException(status_code=400, detail={"missing": detail})
        raise HTTPException(status_code=400, detail=detail)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Batch-Zip-Included-Count": str(manifest.get("included_count", 0)),
            "X-Batch-Zip-Skipped-Count": str(manifest.get("skipped_count", 0)),
            "X-Batch-Zip-Requested-Count": str(manifest.get("requested_count", 0)),
            "X-Batch-Zip-Redacted": "true" if manifest.get("redacted") else "false",
            "X-Batch-Zip-Skipped": json.dumps(
                (manifest.get("skipped", []) or [])[:20],
                ensure_ascii=True,
                separators=(",", ":"),
            ),
        },
    )


@router.post("/files/batch/export/estimate")
async def estimate_batch_export(
    request: BatchDownloadRequest,
    owner_id: str = Depends(require_auth),
):
    """秒回：基于 st_size 求和预估导出体积与分卷数（不打包）。"""
    entries, manifest = _fms.collect_batch_zip_entries(request, owner_id=owner_id)
    estimate = _export.estimate_volumes(entries)
    return {
        **estimate,
        "skipped": (manifest.get("skipped") or [])[:50],
        "skipped_count": manifest.get("skipped_count", 0),
    }


@router.post("/files/batch/export", status_code=202)
async def create_batch_export(
    request: BatchDownloadRequest,
    store: JobStore = Depends(get_job_store),
    owner_id: str = Depends(require_auth),
):
    """发起异步分卷导出任务（万级文件）。"""
    _assert_batch_delivery_ready(request, store, owner_id)
    entries, manifest = _fms.collect_batch_zip_entries(request, owner_id=owner_id)
    if not entries:
        raise HTTPException(status_code=400, detail="没有可导出的文件（不存在或未匿名化）")
    estimate = _export.estimate_volumes(entries)
    task = _export.export_task_manager.submit(
        owner_id=owner_id,
        kind="batch_files",
        runner=_export.make_batch_files_runner(entries, manifest),
        title="redacted_batch" if request.redacted else "original_batch",
        total_bytes=estimate["total_bytes"],
        file_count=estimate["file_count"],
    )
    audit_log("export", "batch", task.export_id, detail={"files": len(entries)})
    return {**task.public(), "estimated_volume_count": estimate["estimated_volume_count"]}


@router.get("/files/batch/export/{export_id}")
async def get_batch_export(
    export_id: str,
    owner_id: str = Depends(require_auth),
):
    task = _export.export_task_manager.get(export_id, owner_id)
    if task is None:
        raise HTTPException(status_code=404, detail="export not found")
    return task.public()


@router.get("/files/batch/export/{export_id}/volumes/{name}")
async def download_batch_export_volume(
    export_id: str,
    name: str,
    owner_id: str = Depends(require_auth),
):
    """卷下载：FileResponse 原生支持 Range 断点续传。"""
    path = _export.export_task_manager.volume_path(export_id, owner_id, name)
    if path is None:
        raise HTTPException(status_code=404, detail="volume not found")
    media = "application/zip" if name.endswith(".zip") else "application/octet-stream"
    return FileResponse(path, media_type=media, filename=name)


@router.post(
    "/files/upload",
    response_model=FileUploadResponse,
    dependencies=[Depends(_upload_throttle)],
)
async def upload_file(
    file: UploadFile = File(...),
    batch_group_id: str | None = Form(None),
    job_id: str | None = Form(None),
    upload_source: str | None = Form(None),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
    owner_id: str = Depends(require_auth),
):
    """
    上传文件

    支持的文件类型:
    - Word 文档 (.doc, .docx)
    - PDF 文档 (.pdf)
    - 图片 (.jpg, .jpeg, .png)
    """
    scoped_idempotency_key = f"{owner_id}:{x_idempotency_key}" if x_idempotency_key else None
    cached = check_idempotency(scoped_idempotency_key)
    if cached is not None:
        return cached

    validate_file(file)

    # 生成唯一文件ID
    file_id = str(uuid.uuid4())
    file_ext = os.path.splitext(file.filename)[1].lower()
    stored_filename = f"{file_id}{file_ext}"
    file_path = os.path.realpath(os.path.join(settings.UPLOAD_DIR, stored_filename))

    # 磁盘空间检查
    disk = shutil.disk_usage(os.path.dirname(file_path))
    if disk.free < 500 * 1024 * 1024:
        raise HTTPException(status_code=507, detail="磁盘空间不足，请清理后重试")

    # 保存文件（流式读取，边读边验证大小）
    CHUNK_SIZE = 1024 * 1024  # 1MB
    file_size = 0
    try:
        async with aiofiles.open(file_path, 'wb') as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > settings.MAX_FILE_SIZE:
                    await f.close()
                    os.remove(file_path)
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件过大，最大支持 {settings.MAX_FILE_SIZE // 1024 // 1024}MB",
                    )
                await f.write(chunk)
    except HTTPException:
        raise
    except OSError:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail="文件保存失败，请稍后重试")

    # Delegate to service layer for validation and registration
    try:
        response_and_jid = await _fms.process_upload(
            file_path=file_path,
            file_ext=file_ext,
            filename=file.filename,
            file_size=file_size,
            batch_group_id=batch_group_id,
            job_id=job_id,
            upload_source=upload_source,
            owner_id=owner_id,
        )
        response, jid = response_and_jid
    except ValueError as exc:
        await _fms.rollback_upload(file_id, file_path)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Failed to register uploaded file metadata, rolling back %s", file_id)
        await _fms.rollback_upload(file_id, file_path)
        raise HTTPException(status_code=500, detail="文件注册失败，文件已回滚")

    if jid:
        try:
            _fms.register_file_with_job(jid, response.file_id, owner_id=owner_id)
        except ValueError as exc:
            await _fms.rollback_upload(response.file_id, file_path)
            raise HTTPException(status_code=400, detail=str(exc))
        except HTTPException:
            await _fms.rollback_upload(response.file_id, file_path)
            raise
        except Exception:
            logger.exception("Failed to register file %s with job %s, rolling back", response.file_id, jid)
            await _fms.rollback_upload(response.file_id, file_path)
            raise HTTPException(status_code=500, detail="任务注册失败，文件已回滚")

    audit_log("upload", "file", response.file_id, detail={"filename": file.filename})
    save_idempotency(scoped_idempotency_key, response)
    return response


# ── 断点续传（分块上传）──────────────────────────────────────────────
# 弱网/隧道场景下大文件整包上传一断全丢。分块方案：init 建会话 → 逐块 PUT
# （偏移必须等于已收字节，重放幂等）→ 断线后 GET 查已收字节从断点续 →
# complete 走与 /files/upload 完全相同的校验注册路径（magic bytes/病毒扫描/
# 任务挂接），因此安全语义与整包上传一致。

_RESUMABLE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_RESUMABLE_TTL_SECONDS = 24 * 3600
_RESUMABLE_MAX_CHUNK_BYTES = 8 * 1024 * 1024
_RESUMABLE_CHUNK_SIZE_HINT = 5 * 1024 * 1024


class ResumableUploadInitBody(BaseModel):
    filename: str
    file_size: int
    batch_group_id: str | None = None
    job_id: str | None = None
    upload_source: str | None = None


def _resumable_owner_dir(owner_id: str) -> str:
    safe_owner = re.sub(r"[^A-Za-z0-9_.@-]", "_", str(owner_id or "local_user"))
    return os.path.join(settings.UPLOAD_DIR, "partial", safe_owner)


def _resumable_paths(owner_id: str, upload_id: str) -> tuple[str, str]:
    if not _RESUMABLE_ID_RE.match(upload_id or ""):
        raise HTTPException(status_code=404, detail="上传会话不存在")
    owner_dir = _resumable_owner_dir(owner_id)
    return (
        os.path.join(owner_dir, f"{upload_id}.part"),
        os.path.join(owner_dir, f"{upload_id}.json"),
    )


def _load_resumable_session(owner_id: str, upload_id: str) -> tuple[str, str, dict]:
    part_path, meta_path = _resumable_paths(owner_id, upload_id)
    if not (os.path.exists(part_path) and os.path.exists(meta_path)):
        raise HTTPException(status_code=404, detail="上传会话不存在或已过期")
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=404, detail="上传会话不存在或已过期")
    return part_path, meta_path, meta


def _cleanup_stale_partials(owner_dir: str) -> None:
    """Best-effort: drop partial sessions older than the TTL."""
    try:
        cutoff = time.time() - _RESUMABLE_TTL_SECONDS
        for name in os.listdir(owner_dir):
            path = os.path.join(owner_dir, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                continue
    except OSError:
        pass


@router.post("/files/upload/resumable/init", dependencies=[Depends(_upload_throttle)])
async def resumable_upload_init(
    body: ResumableUploadInitBody,
    owner_id: str = Depends(require_auth),
):
    if not body.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    ext = os.path.splitext(body.filename)[1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，支持的类型: {settings.ALLOWED_EXTENSIONS}",
        )
    if body.file_size <= 0 or body.file_size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小无效，最大支持 {settings.MAX_FILE_SIZE // 1024 // 1024}MB",
        )

    owner_dir = _resumable_owner_dir(owner_id)
    os.makedirs(owner_dir, exist_ok=True)
    _cleanup_stale_partials(owner_dir)

    disk = shutil.disk_usage(owner_dir)
    if disk.free < body.file_size + 500 * 1024 * 1024:
        raise HTTPException(status_code=507, detail="磁盘空间不足，请清理后重试")

    upload_id = uuid.uuid4().hex
    part_path, meta_path = _resumable_paths(owner_id, upload_id)
    with open(part_path, "wb"):
        pass
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "filename": body.filename,
                "file_size": int(body.file_size),
                "batch_group_id": body.batch_group_id,
                "job_id": body.job_id,
                "upload_source": body.upload_source,
                "created_at": time.time(),
            },
            fh,
        )
    return {
        "upload_id": upload_id,
        "received_bytes": 0,
        "chunk_size": _RESUMABLE_CHUNK_SIZE_HINT,
    }


@router.get("/files/upload/resumable/{upload_id}")
async def resumable_upload_status(
    upload_id: str,
    owner_id: str = Depends(require_auth),
):
    part_path, _meta_path, meta = _load_resumable_session(owner_id, upload_id)
    return {
        "upload_id": upload_id,
        "received_bytes": os.path.getsize(part_path),
        "file_size": meta.get("file_size"),
    }


@router.put("/files/upload/resumable/{upload_id}/chunk")
async def resumable_upload_chunk(
    upload_id: str,
    request: Request,
    offset: int = Query(..., ge=0),
    owner_id: str = Depends(require_auth),
):
    part_path, _meta_path, meta = _load_resumable_session(owner_id, upload_id)
    declared_size = int(meta.get("file_size") or 0)
    current = os.path.getsize(part_path)
    if offset < current:
        # 重放（客户端超时但服务端其实已收到）：幂等返回当前进度
        return {"upload_id": upload_id, "received_bytes": current, "replayed": True}
    if offset > current:
        raise HTTPException(
            status_code=409,
            detail={"message": "偏移不连续，请从 received_bytes 续传", "received_bytes": current},
        )

    written = 0
    try:
        async with aiofiles.open(part_path, "ab") as f:
            async for chunk in request.stream():
                if not chunk:
                    continue
                written += len(chunk)
                if written > _RESUMABLE_MAX_CHUNK_BYTES or current + written > declared_size:
                    raise HTTPException(status_code=400, detail="分块超出声明大小")
                await f.write(chunk)
    except HTTPException:
        _truncate_partial(part_path, current)
        raise
    except OSError:
        _truncate_partial(part_path, current)
        raise HTTPException(status_code=500, detail="分块保存失败，请重试")

    return {"upload_id": upload_id, "received_bytes": current + written}


def _truncate_partial(part_path: str, size: int) -> None:
    """Restore the append-only invariant after a failed/oversized chunk."""
    try:
        with open(part_path, "ab") as fh:
            fh.truncate(size)
    except OSError:
        logger.warning("unable to truncate partial upload %s to %d", part_path, size)


@router.post("/files/upload/resumable/{upload_id}/complete")
async def resumable_upload_complete(
    upload_id: str,
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
    owner_id: str = Depends(require_auth),
):
    # 幂等在会话查找之前：complete 响应丢失后的重试，此时 partial 已被消费，
    # 只能靠幂等缓存返回同一个注册结果。
    scoped_idempotency_key = f"{owner_id}:{x_idempotency_key}" if x_idempotency_key else None
    cached = check_idempotency(scoped_idempotency_key)
    if cached is not None:
        return cached

    part_path, meta_path, meta = _load_resumable_session(owner_id, upload_id)
    declared_size = int(meta.get("file_size") or 0)
    received = os.path.getsize(part_path)
    if received != declared_size:
        raise HTTPException(
            status_code=400,
            detail={"message": "文件未传完，请续传", "received_bytes": received},
        )

    filename = str(meta.get("filename") or "")
    file_id = str(uuid.uuid4())
    file_ext = os.path.splitext(filename)[1].lower()
    stored_filename = f"{file_id}{file_ext}"
    file_path = os.path.realpath(os.path.join(settings.UPLOAD_DIR, stored_filename))
    os.replace(part_path, file_path)
    try:
        os.remove(meta_path)
    except OSError:
        pass

    try:
        response, jid = await _fms.process_upload(
            file_path=file_path,
            file_ext=file_ext,
            filename=filename,
            file_size=received,
            batch_group_id=meta.get("batch_group_id"),
            job_id=meta.get("job_id"),
            upload_source=meta.get("upload_source"),
            owner_id=owner_id,
        )
    except ValueError as exc:
        await _fms.rollback_upload(file_id, file_path)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Failed to register resumable upload %s, rolling back", file_id)
        await _fms.rollback_upload(file_id, file_path)
        raise HTTPException(status_code=500, detail="文件注册失败，文件已回滚")

    if jid:
        try:
            _fms.register_file_with_job(jid, response.file_id, owner_id=owner_id)
        except ValueError as exc:
            await _fms.rollback_upload(response.file_id, file_path)
            raise HTTPException(status_code=400, detail=str(exc))
        except HTTPException:
            await _fms.rollback_upload(response.file_id, file_path)
            raise
        except Exception:
            logger.exception(
                "Failed to register resumable file %s with job %s, rolling back",
                response.file_id,
                jid,
            )
            await _fms.rollback_upload(response.file_id, file_path)
            raise HTTPException(status_code=500, detail="任务注册失败，文件已回滚")

    audit_log("upload", "file", response.file_id, detail={"filename": filename, "resumable": True})
    save_idempotency(scoped_idempotency_key, response)
    return response


@router.get("/files/{file_id}/parse", response_model=ParseResult)
async def parse_file(file_id: str, owner_id: str = Depends(require_auth)):
    """
    解析文件内容

    - 对于 Word/PDF: 提取文本内容
    - 对于图片/扫描版 PDF: 标记为需要视觉处理
    """
    try:
        _fms.assert_file_owner(file_id, owner_id)
        result = await _fms.parse_file(file_id)
    except ValueError as exc:
        if "NOT in file_store" in str(exc) or "不存在" in str(exc):
            logger.error("parse_file: %s", exc)
            raise HTTPException(status_code=404, detail="文件不存在")
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/files/{file_id}/ner/hybrid", response_model=NERResult)
async def hybrid_ner_extract(
    file_id: str,
    request: HybridNERRequest = Body(default=HybridNERRequest()),
    owner_id: str = Depends(require_auth),
):
    """
    混合NER识别 - HaS本地模型 + 正则

    工作流程:
    1. Stage 1: HaS 本地模型识别
    2. Stage 2: 正则识别（高置信度模式匹配）
    3. Stage 3: 交叉验证 + 指代消解
    """
    if request.entity_type_ids is not None and len(request.entity_type_ids) > 200:
        raise HTTPException(status_code=400, detail="实体类型数量超过上限（200）")

    try:
        _fms.assert_file_owner(file_id, owner_id)
        logger.info(
            "[hybrid_ner_extract] file_id=%s requested_entity_type_ids=%s",
            file_id,
            request.entity_type_ids,
        )
        ner_result = await _fms.run_hybrid_ner(
            file_id,
            entity_type_ids=request.entity_type_ids,
            owner_id=owner_id,
        )
    except ValueError as exc:
        detail = str(exc)
        if "不存在" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)

    return NERResult(
        file_id=file_id,
        entities=ner_result["entities"],
        entity_count=ner_result["entity_count"],
        entity_summary=ner_result["entity_summary"],
        warnings=ner_result.get("warnings"),
        recognition_failed=ner_result.get("recognition_failed", False),
        error=ner_result.get("error"),
    )


@router.get("/files/{file_id}/ner", response_model=NERResult)
async def extract_entities(file_id: str, owner_id: str = Depends(require_auth)):
    """
    对文件进行命名实体识别 (NER) - 使用默认实体类型
    """
    try:
        _fms.assert_file_owner(file_id, owner_id)
        ner_result = await _fms.run_default_ner(file_id, owner_id=owner_id)
    except ValueError as exc:
        detail = str(exc)
        if "不存在" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)

    return NERResult(
        file_id=file_id,
        entities=ner_result["entities"],
        entity_count=ner_result["entity_count"],
        entity_summary=ner_result["entity_summary"],
        recognition_failed=ner_result.get("recognition_failed", False),
        error=ner_result.get("error"),
    )


@router.post("/files/{file_id}/ner", response_model=NERResult)
async def extract_entities_with_config(
    file_id: str,
    request: NERRequest = Body(default=NERRequest()),
    owner_id: str = Depends(require_auth),
):
    """
    对文件进行命名实体识别 (NER) - 支持自定义实体类型
    """
    # Merge built-in entity_types and custom_entity_type_ids into a single list
    entity_type_ids = (request.entity_types or []) + (request.custom_entity_type_ids or [])
    try:
        _fms.assert_file_owner(file_id, owner_id)
        ner_result = await _fms.run_default_ner(
            file_id,
            entity_type_ids=entity_type_ids if entity_type_ids else None,
            owner_id=owner_id,
        )
    except ValueError as exc:
        detail = str(exc)
        if "不存在" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)

    return NERResult(
        file_id=file_id,
        entities=ner_result["entities"],
        entity_count=ner_result["entity_count"],
        entity_summary=ner_result["entity_summary"],
        recognition_failed=ner_result.get("recognition_failed", False),
        error=ner_result.get("error"),
    )


@router.get("/files/{file_id}")
async def get_file_info(file_id: str, owner_id: str = Depends(require_auth)):
    """获取文件信息"""
    info = await _fms.get_file_info(file_id)
    if not info or _fms.file_owner_id(info) != owner_id:
        raise HTTPException(status_code=404, detail="文件不存在")
    return info


@router.get("/files/{file_id}/download")
async def download_file(file_id: str, redacted: bool = False, owner_id: str = Depends(require_auth)):
    """
    下载文件

    - redacted=False: 下载原始文件
    - redacted=True: 下载匿名化后的文件
    """
    snapshot = await _fms.get_file_snapshot(file_id)
    if not snapshot or _fms.file_owner_id(snapshot) != owner_id:
        raise HTTPException(status_code=404, detail="文件不存在")

    if redacted:
        file_path = snapshot.get("output_path")
        if not file_path:
            raise HTTPException(status_code=400, detail="文件尚未匿名化")
        filename = f"redacted_{snapshot.get('original_filename') or file_id}"
    else:
        file_path = snapshot.get("file_path")
        if not file_path:
            raise HTTPException(status_code=400, detail="missing original file path")
        filename = snapshot.get("original_filename") or file_id

    # 路径遍历保护
    expected_dir = settings.OUTPUT_DIR if redacted else settings.UPLOAD_DIR
    if not _fms.safe_path_in_dir(file_path, expected_dir):
        raise HTTPException(status_code=403, detail="禁止访问该路径")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@router.get("/files/{file_id}/page-image")
async def get_page_image(
    file_id: str,
    page: int = 1,
    redacted: bool = False,
    owner_id: str = Depends(require_auth),
):
    """Render a single page of a PDF as PNG (for history comparison).

    - redacted=False → original upload
    - redacted=True  → the redacted output PDF
    """
    from starlette.responses import Response as RawResponse

    snapshot = await _fms.get_file_snapshot(file_id)
    if not snapshot or _fms.file_owner_id(snapshot) != owner_id:
        raise HTTPException(status_code=404, detail="文件不存在")

    if redacted:
        file_path = snapshot.get("output_path")
        if not file_path:
            raise HTTPException(status_code=400, detail="文件尚未匿名化")
        expected_dir = settings.OUTPUT_DIR
    else:
        file_path = snapshot.get("file_path")
        if not file_path:
            raise HTTPException(status_code=400, detail="missing original file path")
        expected_dir = settings.UPLOAD_DIR

    if not _fms.safe_path_in_dir(file_path, expected_dir):
        raise HTTPException(status_code=403, detail="禁止访问该路径")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    ft = str(snapshot.get("file_type", "")).lower()
    if ft in ("pdf", "pdf_scanned"):
        from app.services.file_parser import FileParser
        parser = FileParser()
        image_bytes = await parser.get_pdf_page_image(file_path, page)
        return RawResponse(content=image_bytes, media_type="image/png")

    if ft in ("image", "jpg", "jpeg", "png"):
        # Re-encode to PNG so browser-unsupported formats (TIFF, BMP) preview in the
        # history comparison instead of showing a broken image.
        from io import BytesIO

        from PIL import Image, ImageOps

        with Image.open(file_path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            buf = BytesIO()
            im.save(buf, format="PNG")
        return RawResponse(content=buf.getvalue(), media_type="image/png")

    raise HTTPException(status_code=400, detail=f"不支持逐页渲染: {ft}")


@router.delete("/files/{file_id}")
async def delete_file(file_id: str, owner_id: str = Depends(require_auth)):
    """删除文件"""
    try:
        _fms.assert_file_owner(file_id, owner_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="file not found")
    snapshot = await _fms.delete_file(file_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="文件不存在")
    audit_log("delete", "file", file_id)
    return APIResponse(message="文件删除成功")
