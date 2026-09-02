"""DICOM ingestion, review, de-identification, and export API."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import aiofiles
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    Query,
    Response,
    UploadFile,
)
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse

from app.core.audit import audit_log
from app.core.auth import get_user, require_auth
from app.core.config import settings
from app.core.errors import AppError
from app.models.dicom_api_schemas import (
    DicomAnonymizeRequest,
    DicomBatchAnonymizeRequest,
    DicomPolicyOptions,
    DicomPreflightRequest,
    DicomProfile,
    DicomReviewRequest,
)
from app.services.dicom_jobs import (
    DicomJobService,
    DicomWorkflowError,
    dicom_pixel_ocr_enabled,
    get_dicom_job_service,
)

router = APIRouter(prefix="/dicom", tags=["DICOM"])

_CHUNK_SIZE = 1024 * 1024
_MAX_UPLOAD_BYTES = max(1, int(os.environ.get("DICOM_MAX_UPLOAD_BYTES", settings.MAX_FILE_SIZE)))
_MAX_ARCHIVE_EXPANDED_BYTES = max(
    _MAX_UPLOAD_BYTES,
    int(os.environ.get("DICOM_MAX_ARCHIVE_EXPANDED_BYTES", 500 * 1024**2)),
)
_MAX_ARCHIVE_ENTRIES = max(1, int(os.environ.get("DICOM_MAX_ARCHIVE_ENTRIES", "20000")))
_MAX_COMPRESSION_RATIO = 100
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:/")


@dataclass(frozen=True)
class _PreparedEntry:
    path: str
    relative_name: str
    size: int
    sha256: str


def _workflow_error(exc: DicomWorkflowError) -> AppError:
    return AppError(exc.status_code, exc.error_code, exc.message, exc.detail)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _multipart_relative_name(filename: str | None, index: int) -> str:
    raw = (filename or f"instance-{index + 1}.dcm").replace("\\", "/")
    # Browsers and older HTTP clients sometimes send C:\fakepath\name.dcm.
    # It is not a folder upload and must never become a server-side drive path.
    if _WINDOWS_DRIVE_RE.match(raw) or raw.startswith("/"):
        raw = PurePosixPath(raw).name
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise DicomWorkflowError(400, "DICOM_UNSAFE_PATH", "上传文件名包含不安全路径")
    cleaned: list[str] = []
    for part in parts:
        safe = re.sub(r"[<>:\"|?*\x00-\x1f]", "_", part).strip()
        if not safe or safe in {".", ".."}:
            raise DicomWorkflowError(400, "DICOM_UNSAFE_PATH", "上传文件名无效")
        cleaned.append(safe[:180])
    relative = "/".join(cleaned)
    if len(relative) > 1000:
        raise DicomWorkflowError(400, "DICOM_PATH_TOO_LONG", "上传文件路径过长")
    return relative


def _archive_relative_name(name: str) -> str:
    raw = name.replace("\\", "/")
    if raw.startswith("/") or _WINDOWS_DRIVE_RE.match(raw):
        raise DicomWorkflowError(400, "DICOM_ZIP_PATH_TRAVERSAL", "ZIP包含绝对路径")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise DicomWorkflowError(400, "DICOM_ZIP_PATH_TRAVERSAL", "ZIP包含越界路径")
    if any(re.search(r"[<>:\"|?*\x00-\x1f]", part) for part in parts):
        raise DicomWorkflowError(400, "DICOM_ZIP_UNSAFE_NAME", "ZIP包含不支持的文件名")
    relative = "/".join(parts)
    if len(relative) > 1000:
        raise DicomWorkflowError(400, "DICOM_PATH_TOO_LONG", "ZIP文件路径过长")
    return relative


async def _save_upload(upload: UploadFile, destination: str, remaining: int) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    try:
        async with aiofiles.open(destination, "wb") as stream:
            while True:
                chunk = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > remaining:
                    raise DicomWorkflowError(
                        413,
                        "DICOM_UPLOAD_TOO_LARGE",
                        "DICOM上传内容超过大小限制",
                        {"max_bytes": _MAX_UPLOAD_BYTES},
                    )
                digest.update(chunk)
                await stream.write(chunk)
    except Exception:
        try:
            os.remove(destination)
        except OSError:
            pass
        raise
    if size == 0:
        try:
            os.remove(destination)
        except OSError:
            pass
        raise DicomWorkflowError(400, "DICOM_EMPTY_FILE", "DICOM上传文件不能为空")
    return size, digest.hexdigest()


async def _prepare_files(uploads: list[UploadFile], staging: str) -> list[_PreparedEntry]:
    if not uploads:
        raise DicomWorkflowError(400, "DICOM_EMPTY_UPLOAD", "至少上传一个DICOM文件")
    if len(uploads) > _MAX_ARCHIVE_ENTRIES:
        raise DicomWorkflowError(
            413,
            "DICOM_TOO_MANY_FILES",
            "DICOM文件数量超过限制",
            {"max_entries": _MAX_ARCHIVE_ENTRIES},
        )
    prepared: list[_PreparedEntry] = []
    total = 0
    seen: set[str] = set()
    for index, upload in enumerate(uploads):
        relative = _multipart_relative_name(upload.filename, index)
        key = relative.casefold()
        if key in seen:
            raise DicomWorkflowError(
                400,
                "DICOM_DUPLICATE_PATH",
                "上传内容包含重复路径",
                {"path": relative},
            )
        seen.add(key)
        destination = os.path.join(staging, f"upload-{index:08d}.bin")
        size, digest = await _save_upload(upload, destination, _MAX_UPLOAD_BYTES - total)
        total += size
        prepared.append(_PreparedEntry(destination, relative, size, digest))
    return prepared


async def _prepare_archive(upload: UploadFile, staging: str) -> tuple[list[_PreparedEntry], str]:
    archive_path = os.path.join(staging, "source.zip")
    archive_size, archive_digest = await _save_upload(upload, archive_path, _MAX_UPLOAD_BYTES)
    del archive_size
    if not zipfile.is_zipfile(archive_path):
        raise DicomWorkflowError(400, "DICOM_ARCHIVE_INVALID", "仅支持有效的ZIP归档")

    extract_root = os.path.realpath(os.path.join(staging, "extracted"))
    os.makedirs(extract_root, exist_ok=False)
    entries: list[_PreparedEntry] = []
    total_expanded = 0
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = [item for item in archive.infolist() if not item.is_dir()]
            if len(infos) > _MAX_ARCHIVE_ENTRIES:
                raise DicomWorkflowError(
                    413,
                    "DICOM_ARCHIVE_TOO_MANY_ENTRIES",
                    "ZIP文件数量超过限制",
                    {"max_entries": _MAX_ARCHIVE_ENTRIES},
                )
            for info in infos:
                if info.flag_bits & 0x1:
                    raise DicomWorkflowError(400, "DICOM_ARCHIVE_ENCRYPTED", "不支持加密ZIP")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    raise DicomWorkflowError(400, "DICOM_ARCHIVE_SYMLINK", "ZIP不能包含符号链接")
                relative = _archive_relative_name(info.filename)
                key = relative.casefold()
                if key in seen:
                    raise DicomWorkflowError(
                        400,
                        "DICOM_DUPLICATE_PATH",
                        "ZIP包含重复路径",
                        {"path": relative},
                    )
                seen.add(key)
                if (
                    info.file_size > 1024 * 1024
                    and info.file_size > max(1, info.compress_size) * _MAX_COMPRESSION_RATIO
                ):
                    raise DicomWorkflowError(413, "DICOM_ZIP_BOMB", "ZIP压缩比异常")
                total_expanded += int(info.file_size)
                if total_expanded > _MAX_ARCHIVE_EXPANDED_BYTES:
                    raise DicomWorkflowError(
                        413,
                        "DICOM_ARCHIVE_TOO_LARGE",
                        "ZIP解压后超过大小限制",
                        {"max_expanded_bytes": _MAX_ARCHIVE_EXPANDED_BYTES},
                    )
                destination = os.path.realpath(os.path.join(extract_root, *relative.split("/")))
                if os.path.commonpath((destination, extract_root)) != extract_root:
                    raise DicomWorkflowError(400, "DICOM_ZIP_PATH_TRAVERSAL", "ZIP包含越界路径")
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                digest = hashlib.sha256()
                actual = 0
                with archive.open(info, "r") as source, open(destination, "wb") as target:
                    while True:
                        chunk = source.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        actual += len(chunk)
                        if actual > info.file_size or actual > _MAX_ARCHIVE_EXPANDED_BYTES:
                            raise DicomWorkflowError(413, "DICOM_ZIP_BOMB", "ZIP解压大小异常")
                        digest.update(chunk)
                        target.write(chunk)
                if actual == 0:
                    os.remove(destination)
                    continue
                entries.append(_PreparedEntry(destination, relative, actual, digest.hexdigest()))
    except zipfile.BadZipFile as exc:
        raise DicomWorkflowError(400, "DICOM_ARCHIVE_INVALID", "ZIP归档已损坏") from exc
    if not entries:
        raise DicomWorkflowError(400, "DICOM_EMPTY_UPLOAD", "ZIP中没有可处理的文件")
    return entries, archive_digest


def _parse_form_options(value: str | None) -> DicomPolicyOptions:
    if not value:
        return DicomPolicyOptions()
    try:
        payload = json.loads(value)
    except ValueError as exc:
        raise DicomWorkflowError(400, "DICOM_OPTIONS_INVALID", "options必须是JSON对象") from exc
    if not isinstance(payload, dict):
        raise DicomWorkflowError(400, "DICOM_OPTIONS_INVALID", "options必须是JSON对象")
    try:
        return DicomPolicyOptions.model_validate(payload)
    except Exception as exc:
        raise DicomWorkflowError(
            400,
            "DICOM_OPTIONS_INVALID",
            "DICOM策略选项无效",
            {"reason": str(exc)[:500]},
        ) from exc


def _require_review_role(owner_id: str) -> None:
    if not settings.AUTH_ENABLED:
        return
    user = get_user(owner_id)
    role = str((user or {}).get("role") or "")
    if role in {"operator", "viewer"}:
        raise AppError(403, "DICOM_REVIEW_FORBIDDEN", "当前角色无权提交DICOM复核结论")


@router.get("/capabilities")
async def capabilities(owner_id: str = Depends(require_auth)) -> dict[str, Any]:
    del owner_id
    return {
        "ingest": ["single_file", "multi_file", "folder", "zip", "dicomdir"],
        "profiles": [item.value for item in DicomProfile],
        "hierarchy": ["study", "series", "instance"],
        "preview": {"format": "image/png", "multi_frame": True, "windowing": True},
        "pixel_redaction": {
            "enabled": dicom_pixel_ocr_enabled(),
            "automatic": True,
            "detector": "PaddleOCR+HaS+DICOM-fail-safe",
            "fail_closed": True,
            "clean_pixel_data_code": "113101",
        },
        "batch_anonymize": True,
        "dicomweb": {"qido_rs": False, "wado_rs": False, "stow_rs": False},
        "limits": {
            "upload_bytes": _MAX_UPLOAD_BYTES,
            "archive_expanded_bytes": _MAX_ARCHIVE_EXPANDED_BYTES,
            "archive_entries": _MAX_ARCHIVE_ENTRIES,
        },
    }


@router.post("/ingest", status_code=201)
async def ingest(
    profile: DicomProfile = Form(DicomProfile.BASIC),
    options: str | None = Form(None),
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    archive: UploadFile | None = File(None),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> dict[str, Any]:
    uploads = ([file] if file is not None else []) + list(files or [])
    if bool(archive) == bool(uploads):
        raise AppError(
            400,
            "DICOM_INGEST_SOURCE_INVALID",
            "file/files与archive必须且只能提供一种",
        )
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".dicom-staging-", dir=settings.UPLOAD_DIR)
    endpoint = "dicom:ingest"
    claimed = False
    try:
        policy_options = _parse_form_options(options)
        if archive is not None:
            prepared, archive_digest = await _prepare_archive(archive, staging)
            source_kind = "zip"
            request_files: Any = {"archive_sha256": archive_digest}
        else:
            prepared = await _prepare_files(uploads, staging)
            source_kind = "single_file" if len(prepared) == 1 else "multi_file"
            request_files = sorted(
                [
                    {"name": item.relative_name, "size": item.size, "sha256": item.sha256}
                    for item in prepared
                ],
                key=lambda item: item["name"].casefold(),
            )
        request_hash = _canonical_hash(
            {
                "profile": profile.value,
                "options": policy_options.core_options(),
                "source": request_files,
            }
        )
        cached = service.claim_idempotency(
            owner_id=owner_id,
            endpoint=endpoint,
            key=x_idempotency_key,
            request_hash=request_hash,
        )
        if cached is not None:
            return cached
        claimed = bool(x_idempotency_key)
        result = service.ingest_paths(
            owner_id=owner_id,
            entries=[(item.path, item.relative_name) for item in prepared],
            profile=profile.value,
            options=policy_options.core_options(),
            source_kind=source_kind,
        )
        service.complete_idempotency(
            owner_id=owner_id,
            endpoint=endpoint,
            key=x_idempotency_key,
            response=result,
        )
        audit_log(
            "ingest",
            "dicom_ingest",
            result["ingest_id"],
            user=owner_id,
            detail={
                "source_kind": source_kind,
                "study_count": result["study_count"],
                "instance_count": result["instance_count"],
                "profile": profile.value,
            },
        )
        return result
    except DicomWorkflowError as exc:
        if claimed:
            service.release_idempotency(owner_id=owner_id, endpoint=endpoint, key=x_idempotency_key)
        raise _workflow_error(exc) from exc
    except Exception:
        if claimed:
            service.release_idempotency(owner_id=owner_id, endpoint=endpoint, key=x_idempotency_key)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


@router.get("/studies")
async def list_studies(
    status: str | None = Query(None, max_length=64),
    modality: str | None = Query(None, min_length=1, max_length=16),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(None, max_length=32),
    limit: int = Query(50, ge=1, le=200),
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> dict[str, Any]:
    if cursor:
        try:
            offset = int(cursor)
        except ValueError as exc:
            raise AppError(400, "DICOM_CURSOR_INVALID", "分页游标无效") from exc
        if offset < 0:
            raise AppError(400, "DICOM_CURSOR_INVALID", "分页游标无效")
    result = service.list_studies(
        owner_id=owner_id, status=status, modality=modality, offset=offset, limit=limit
    )
    result["studies"] = result["items"]
    result["next_cursor"] = str(result["next_offset"]) if result["next_offset"] is not None else None
    return result


@router.get("/studies/{study_id}")
async def get_study(
    study_id: str,
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> dict[str, Any]:
    try:
        return service.get_study(study_id, owner_id)
    except DicomWorkflowError as exc:
        raise _workflow_error(exc) from exc


@router.get("/studies/{study_id}/metadata")
async def get_metadata(
    study_id: str,
    series_id: str | None = Query(None),
    instance_id: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> dict[str, Any]:
    try:
        result = service.metadata(
            study_id,
            owner_id,
            series_id=series_id,
            instance_id=instance_id,
            offset=offset,
            limit=limit,
        )
    except DicomWorkflowError as exc:
        raise _workflow_error(exc) from exc
    audit_log("read_metadata", "dicom_study", study_id, user=owner_id)
    return result


@router.get("/studies/{study_id}/risks")
async def get_risks(
    study_id: str,
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> dict[str, Any]:
    try:
        return service.risks(study_id, owner_id)
    except DicomWorkflowError as exc:
        raise _workflow_error(exc) from exc


@router.get("/studies/{study_id}/instances/{instance_id}/preview")
async def preview_instance(
    study_id: str,
    instance_id: str,
    frame: int = Query(0, ge=0),
    window_center: float | None = Query(None),
    window_width: float | None = Query(None, gt=0),
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> Response:
    try:
        content = service.preview(
            study_id=study_id,
            instance_id=instance_id,
            owner_id=owner_id,
            frame_index=frame,
            window_center=window_center,
            window_width=window_width,
        )
    except DicomWorkflowError as exc:
        raise _workflow_error(exc) from exc
    audit_log(
        "preview",
        "dicom_instance",
        instance_id,
        user=owner_id,
        detail={"study_id": study_id, "frame": frame},
    )
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/studies/{study_id}/preflight")
async def preflight(
    study_id: str,
    body: DicomPreflightRequest,
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> dict[str, Any]:
    try:
        # Pixel OCR invokes GPU-backed synchronous HTTP clients underneath an
        # async HaS orchestration layer.  Keep the complete synchronous DICOM
        # core outside the ASGI event loop.
        result = await run_in_threadpool(
            service.preflight,
            study_id=study_id,
            owner_id=owner_id,
            profile=body.profile.value,
            options=body.options.core_options(),
        )
    except DicomWorkflowError as exc:
        raise _workflow_error(exc) from exc
    audit_log(
        "preflight",
        "dicom_study",
        study_id,
        user=owner_id,
        detail={"profile": body.profile.value, "preflight_version": result["preflight_version"]},
    )
    return result


@router.post("/studies/{study_id}/review")
@router.post("/studies/{study_id}/review/commit", include_in_schema=False)
async def review(
    study_id: str,
    body: DicomReviewRequest,
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> dict[str, Any]:
    _require_review_role(owner_id)
    try:
        result = service.review(
            study_id=study_id,
            owner_id=owner_id,
            decisions=[item.model_dump() for item in body.decisions],
        )
    except DicomWorkflowError as exc:
        raise _workflow_error(exc) from exc
    audit_log(
        "review",
        "dicom_study",
        study_id,
        user=owner_id,
        detail={"decision_count": len(body.decisions), "remaining_open": result["summary"]["open"]},
    )
    return result


def _create_job_request_hash(study_id: str, body: DicomAnonymizeRequest) -> str:
    return _canonical_hash({"study_id": study_id, **body.model_dump(mode="json")})


@router.post("/studies/{study_id}/anonymize", status_code=202)
async def anonymize_study(
    study_id: str,
    body: DicomAnonymizeRequest,
    background_tasks: BackgroundTasks,
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> dict[str, Any]:
    endpoint = f"dicom:anonymize:{study_id}"
    request_hash = _create_job_request_hash(study_id, body)
    claimed = False
    try:
        cached = service.claim_idempotency(
            owner_id=owner_id,
            endpoint=endpoint,
            key=x_idempotency_key,
            request_hash=request_hash,
        )
        if cached is not None:
            return cached
        claimed = bool(x_idempotency_key)
        job = service.create_job(
            study_id=study_id,
            owner_id=owner_id,
            profile=body.profile.value,
            options=body.options.core_options(),
            expected_preflight_version=body.expected_preflight_version,
        )
        result = {"job_id": job["id"], "study_id": study_id, "status": job["status"]}
        service.complete_idempotency(
            owner_id=owner_id,
            endpoint=endpoint,
            key=x_idempotency_key,
            response=result,
        )
        background_tasks.add_task(service.run_job, job["id"], owner_id)
    except DicomWorkflowError as exc:
        if claimed:
            service.release_idempotency(owner_id=owner_id, endpoint=endpoint, key=x_idempotency_key)
        raise _workflow_error(exc) from exc
    audit_log(
        "anonymize",
        "dicom_job",
        result["job_id"],
        user=owner_id,
        detail={"study_id": study_id, "profile": body.profile.value},
    )
    return result


@router.post("/anonymize", status_code=202)
async def anonymize_batch(
    body: DicomBatchAnonymizeRequest,
    background_tasks: BackgroundTasks,
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> dict[str, Any]:
    endpoint = "dicom:anonymize-batch"
    request_hash = _canonical_hash(body.model_dump(mode="json"))
    claimed = False
    try:
        cached = service.claim_idempotency(
            owner_id=owner_id,
            endpoint=endpoint,
            key=x_idempotency_key,
            request_hash=request_hash,
        )
        if cached is not None:
            return cached
        claimed = bool(x_idempotency_key)
        result = service.create_batch_jobs(
            study_ids=body.study_ids,
            owner_id=owner_id,
            profile=body.profile.value,
            options=body.options.core_options(),
            expected_versions=body.expected_preflight_versions,
        )
        service.complete_idempotency(
            owner_id=owner_id,
            endpoint=endpoint,
            key=x_idempotency_key,
            response=result,
        )
        for job in result["jobs"]:
            background_tasks.add_task(service.run_job, job["id"], owner_id)
    except DicomWorkflowError as exc:
        if claimed:
            service.release_idempotency(owner_id=owner_id, endpoint=endpoint, key=x_idempotency_key)
        raise _workflow_error(exc) from exc
    audit_log(
        "anonymize_batch",
        "dicom_batch",
        result["batch_id"],
        user=owner_id,
        detail={"job_count": result["job_count"], "profile": body.profile.value},
    )
    return result


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> dict[str, Any]:
    try:
        return service.get_job(job_id, owner_id)
    except DicomWorkflowError as exc:
        raise _workflow_error(exc) from exc


@router.get("/jobs/{job_id}/report")
async def get_job_report(
    job_id: str,
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> dict[str, Any]:
    try:
        return service.get_report(job_id, owner_id)
    except DicomWorkflowError as exc:
        raise _workflow_error(exc) from exc


@router.get("/jobs/{job_id}/export")
async def export_job(
    job_id: str,
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> FileResponse:
    try:
        path = service.export_path(job_id, owner_id)
    except DicomWorkflowError as exc:
        raise _workflow_error(exc) from exc
    audit_log("export", "dicom_job", job_id, user=owner_id)
    return FileResponse(
        path,
        filename=f"dicom-{job_id}.zip",
        media_type="application/zip",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/batches/{batch_id}")
async def get_batch(
    batch_id: str,
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> dict[str, Any]:
    try:
        return service.get_batch(batch_id, owner_id)
    except DicomWorkflowError as exc:
        raise _workflow_error(exc) from exc


@router.get("/batches/{batch_id}/export")
async def export_batch(
    batch_id: str,
    owner_id: str = Depends(require_auth),
    service: DicomJobService = Depends(get_dicom_job_service),
) -> FileResponse:
    try:
        path = service.batch_export_path(batch_id, owner_id)
    except DicomWorkflowError as exc:
        raise _workflow_error(exc) from exc
    audit_log("export", "dicom_batch", batch_id, user=owner_id)
    return FileResponse(
        path,
        filename=f"dicom-batch-{batch_id}.zip",
        media_type="application/zip",
        headers={"Cache-Control": "private, no-store"},
    )
