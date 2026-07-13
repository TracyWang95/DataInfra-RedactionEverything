"""断点续传（分块上传）—— 从 files.py 拆出的独立子路由。

弱网/隧道场景下大文件整包上传一断全丢。分块方案：init 建会话 → 逐块 PUT
（偏移必须等于已收字节，重放幂等）→ 断线后 GET 查已收字节从断点续 →
complete 走与 /files/upload 完全相同的校验注册路径（magic bytes/病毒扫描/
任务挂接），因此安全语义与整包上传一致。

路由挂在自己的 APIRouter 上，由 files.py 末尾 `router.include_router()` 并入
主文件路由（保持对外路径不变）。共享的 `_upload_throttle` 从 files.py 导入。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import uuid

import aiofiles
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

import app.services.file_management_service as _fms
from app.api.files import _upload_throttle  # shared per-user upload rate limiter
from app.core.audit import audit_log
from app.core.auth import require_auth
from app.core.config import settings
from app.core.idempotency import check_idempotency, save_idempotency

logger = logging.getLogger(__name__)

router = APIRouter()

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


def _truncate_partial(part_path: str, size: int) -> None:
    """Restore the append-only invariant after a failed/oversized chunk."""
    try:
        with open(part_path, "ab") as fh:
            fh.truncate(size)
    except OSError:
        logger.warning("unable to truncate partial upload %s to %d", part_path, size)


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
