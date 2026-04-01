"""
文件管理 API 路由
处理文件上传、下载、解析等操作
"""
import asyncio
import io
import json
import logging
import os
import re
import shutil
import uuid

logger = logging.getLogger(__name__)
import zipfile
from collections import defaultdict
import aiofiles
from datetime import datetime, timezone
from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, BackgroundTasks, Body, Query, Depends
from fastapi.responses import FileResponse, Response
from typing import Optional, List

from app.core.idempotency import check_idempotency, save_idempotency
from pydantic import BaseModel, ConfigDict, Field

from app.core.audit import audit_log
from app.core.config import settings
from app.core.persistence import load_json
from app.api.jobs import get_job_store
from app.models.schemas import (
    FileUploadResponse,
    FileListResponse,
    FileListItem,
    JobEmbedSummary,
    JobItemMini,
    ParseResult,
    NERResult,
    NERRequest,
    FileType,
    APIResponse,
)
from app.services.hybrid_ner_service import perform_hybrid_ner
from app.services.job_store import JobStatus, JobStore
from app.services.wizard_furthest import coerce_wizard_furthest_step, infer_batch_step1_configured

router = APIRouter()

_BATCH_GROUP_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")
_BACKEND_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PROJECT_ROOT = os.path.realpath(os.path.join(_BACKEND_ROOT, ".."))


def _sanitize_job_id(raw: Optional[str]) -> Optional[str]:
    """任务中心 Job UUID，合法则绑定 job_items。"""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    try:
        uuid.UUID(s)
    except (ValueError, TypeError):
        return None
    return s


def _sanitize_upload_source(raw: Optional[str]) -> Optional[str]:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip().lower()
    if s in ("playground", "batch"):
        return s
    return None


def _effective_upload_source(info: dict) -> str:
    """兼容旧数据：无字段时按 batch_group_id / job_id 推断。"""
    u = info.get("upload_source")
    if u in ("playground", "batch"):
        return u
    if info.get("job_id") or info.get("batch_group_id"):
        return "batch"
    return "playground"


def _sanitize_batch_group_id(raw: Optional[str]) -> Optional[str]:
    """批量向导会话 ID：UUID 或短标识，非法则忽略（视为单文件）。"""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if len(s) > 80:
        s = s[:80]
    if not _BATCH_GROUP_ID_RE.match(s):
        return None
    return s


# 文件存储（SQLite 持久化）
def _normalize_file_type(value):
    """Normalize file_type string to FileType enum (used during JSON→SQLite migration)."""
    try:
        return FileType(value) if isinstance(value, str) else value
    except (ValueError, KeyError):
        return value


def _candidate_storage_dirs(preferred_dir: str) -> list[str]:
    """Allow migrating legacy records from either repo root or backend-local storage."""
    out: list[str] = []
    for raw in (
        preferred_dir,
        os.path.join(_BACKEND_ROOT, os.path.basename(preferred_dir)),
        os.path.join(_PROJECT_ROOT, os.path.basename(preferred_dir)),
    ):
        real = os.path.realpath(raw)
        if real not in out:
            out.append(real)
    return out


def _normalize_store_path(raw: object, preferred_dir: str) -> Optional[str]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = raw.strip()
    if os.path.isabs(path) and os.path.exists(path):
        return os.path.realpath(path)

    basename = os.path.basename(path)
    if basename:
        for directory in _candidate_storage_dirs(preferred_dir):
            candidate = os.path.realpath(os.path.join(directory, basename))
            if os.path.exists(candidate):
                return candidate

    if os.path.isabs(path):
        return os.path.realpath(path)
    return os.path.realpath(os.path.join(preferred_dir, basename or path))


def _repair_file_store_paths() -> int:
    """Normalize legacy relative paths so jobs/history survive restarts from any working directory."""
    repaired = 0
    for file_id, info in file_store.items():
        if not isinstance(info, dict):
            continue
        next_info = dict(info)
        changed = False

        normalized_file_path = _normalize_store_path(info.get("file_path"), settings.UPLOAD_DIR)
        if normalized_file_path and normalized_file_path != info.get("file_path"):
            next_info["file_path"] = normalized_file_path
            changed = True

        normalized_output_path = _normalize_store_path(info.get("output_path"), settings.OUTPUT_DIR)
        if normalized_output_path and normalized_output_path != info.get("output_path"):
            next_info["output_path"] = normalized_output_path
            changed = True

        if changed:
            file_store.set(file_id, next_info)
            repaired += 1

    return repaired


def _bounding_box_total(info: dict) -> int:
    """图像/视觉链：bounding_boxes 为 {page: [BoundingBox, ...]} 或列表。"""
    raw = info.get("bounding_boxes")
    if not raw:
        return 0
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, dict):
        n = 0
        for v in raw.values():
            if isinstance(v, list):
                n += len(v)
        return n
    return 0


def _recognition_count_from_stored_fields(info: dict) -> int:
    """仅从 file_store 已有字段推断条数（不含 redacted_count）。"""
    ents = info.get("entities")
    n_text = len(ents) if isinstance(ents, list) else 0
    n_boxes = _bounding_box_total(info)
    n = n_text + n_boxes
    if n > 0:
        return n
    em = info.get("entity_map")
    if isinstance(em, dict) and len(em) > 0:
        return len(em)
    return 0


def _entity_count(info: dict) -> int:
    """
    处理历史「识别项」数量：
    - 已生成脱敏文件时优先使用 redacted_count（执行接口落库）；
    - 否则根据 entities / bounding_boxes / entity_map 推断。
    """
    if bool(info.get("output_path")) and isinstance(info.get("redacted_count"), int):
        return int(info["redacted_count"])
    return _recognition_count_from_stored_fields(info)


# ---------------------------------------------------------------------------
# Primary file store: SQLite-backed (FileStoreDB)
# ---------------------------------------------------------------------------
from app.services.file_store_db import FileStoreDB

_file_store_db_path = os.path.join(settings.DATA_DIR, "file_store.sqlite3")
file_store: FileStoreDB = FileStoreDB(_file_store_db_path)

# Async lock — still needed for atomic read-modify-write sequences
_file_store_lock = asyncio.Lock()

# --- One-time JSON → SQLite migration (backward compat) ---
def _migrate_json_to_sqlite() -> None:
    """Merge any JSON file_store entries into SQLite (idempotent)."""
    json_path = settings.FILE_STORE_PATH
    if not os.path.exists(json_path):
        return
    raw = load_json(json_path, default={}) or {}
    if not isinstance(raw, dict) or not raw:
        return
    count = 0
    for file_id, info in raw.items():
        if not isinstance(info, dict):
            continue
        file_path = info.get("file_path")
        if file_path:
            # 规范化路径：相对路径可能在不同工作目录下失效
            resolved = os.path.realpath(file_path)
            if not os.path.exists(resolved):
                logger.debug("Migration skip: file not found at %s (resolved: %s)", file_path, resolved)
                continue
            info["file_path"] = resolved
        info["file_type"] = _normalize_file_type(info.get("file_type"))
        # Backfill redacted_count for old records
        if info.get("output_path") and not isinstance(info.get("redacted_count"), int):
            n = _recognition_count_from_stored_fields(info)
            if n > 0:
                info["redacted_count"] = n
        file_store.set(file_id, info)
        count += 1
    if count:
        logger.info("Migrated %d files from JSON to SQLite file_store", count)
    # Backup old JSON file
    backup = json_path + ".migrated"
    try:
        os.rename(json_path, backup)
        logger.info("Old JSON file_store backed up to %s", backup)
    except OSError:
        pass

_migrate_json_to_sqlite()
_repaired_paths = _repair_file_store_paths()
if _repaired_paths:
    logger.info("Normalized %d file_store path records", _repaired_paths)


class HybridNERRequest(BaseModel):
    """混合识别请求（HaS 固定为 NER）"""
    model_config = ConfigDict(extra="ignore")

    entity_type_ids: List[str] = Field(default_factory=list, description="要识别的实体类型ID列表")


class BatchDownloadRequest(BaseModel):
    """批量打包下载"""
    file_ids: List[str] = Field(..., min_length=1, description="要打包的文件 ID 列表")
    redacted: bool = Field(default=False, description="为 True 时打包脱敏后的文件（需已脱敏）")


@router.get("/files", response_model=FileListResponse)
async def list_files(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    source: Optional[str] = Query(
        None,
        description="按来源筛选：playground（仅 Playground）| batch（批量/任务）；不传为全部",
    ),
    embed_job: bool = Query(
        False,
        description="为 true 时对本页含 job_id 的行注入 job_embed（状态、类型、items 摘要），避免前端逐条 getJob",
    ),
    job_id: Optional[str] = Query(None, description="按 job_id 筛选，仅返回属于该任务的文件"),
    store: JobStore = Depends(get_job_store),
):
    """列出已上传文件（处理历史）；同批次文件相邻排列，支持分页与来源筛选。"""
    src_filter: Optional[str] = None
    if source is not None and str(source).strip():
        s = str(source).strip().lower()
        if s not in ("playground", "batch"):
            raise HTTPException(status_code=400, detail="source 须为 playground 或 batch")
        src_filter = s

    # 如果指定了 job_id，先取该任务的所有 file_id 做白名单
    job_file_ids: set[str] | None = None
    if job_id:
        items = store.list_items(job_id)
        job_file_ids = {it["file_id"] for it in items}

    filtered_entries: list[tuple[str, dict]] = []
    for fid, info in file_store.items():
        if not isinstance(info, dict):
            continue
        if job_file_ids is not None and fid not in job_file_ids:
            continue
        eff = _effective_upload_source(info)
        if src_filter and eff != src_filter:
            continue
        filtered_entries.append((fid, info))

    batch_counts: dict[str, int] = defaultdict(int)
    for _fid, info in filtered_entries:
        bg = info.get("batch_group_id")
        if isinstance(bg, str) and bg.strip():
            batch_counts[bg.strip()] += 1

    # 批量查找 item_status 用于三态脱敏显示
    all_file_ids = [fid for fid, _ in filtered_entries]
    item_status_map = store.batch_find_item_statuses(all_file_ids)

    raw_items: list[FileListItem] = []
    for fid, info in filtered_entries:
        ft = info.get("file_type")
        if ft is not None and not isinstance(ft, FileType):
            try:
                ft = FileType(ft) if isinstance(ft, str) else ft
            except (ValueError, KeyError):
                ft = FileType.DOCX
        bg_raw = info.get("batch_group_id")
        bg_key: Optional[str] = None
        if isinstance(bg_raw, str) and bg_raw.strip():
            bg_key = bg_raw.strip()
        cnt = batch_counts.get(bg_key) if bg_key else None
        eff = _effective_upload_source(info)
        jid = info.get("job_id")
        job_key = jid.strip() if isinstance(jid, str) and jid.strip() else None
        raw_items.append(
            FileListItem(
                file_id=fid,
                original_filename=info.get("original_filename", ""),
                file_size=int(info.get("file_size", 0)),
                file_type=ft if isinstance(ft, FileType) else FileType.DOCX,
                created_at=info.get("created_at"),
                has_output=bool(info.get("output_path")),
                entity_count=_entity_count(info),
                upload_source=eff,
                job_id=job_key,
                batch_group_id=bg_key,
                batch_group_count=cnt,
                item_status=(item_status_map.get(fid) or {}).get("status"),
                item_id=(item_status_map.get(fid) or {}).get("item_id"),
            )
        )

    groups: dict[str, list[FileListItem]] = defaultdict(list)
    for it in raw_items:
        gk = it.batch_group_id if it.batch_group_id else f"single:{it.file_id}"
        groups[gk].append(it)

    for gk in groups:
        groups[gk].sort(key=lambda x: x.created_at or "")

    def _group_max_ts(k: str) -> str:
        xs = groups[k]
        return max((x.created_at or "" for x in xs), default="")

    ordered_keys = sorted(groups.keys(), key=_group_max_ts, reverse=True)
    items: list[FileListItem] = []
    for k in ordered_keys:
        items.extend(groups[k])

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]

    if embed_job and page_items:
        jids = {it.job_id for it in page_items if it.job_id}
        embed_map: dict[str, JobEmbedSummary] = {}
        for jid in jids:
            row = store.get_job(jid)
            if not row:
                continue
            jt = row.get("job_type")
            if jt not in ("text_batch", "image_batch", "smart_batch"):
                continue
            raw_items = store.list_items(jid)
            mini = [JobItemMini(id=str(x["id"]), status=str(x["status"])) for x in raw_items]
            first_awaiting_embed: str | None = None
            for x in raw_items:
                if str(x.get("status")) == "awaiting_review":
                    first_awaiting_embed = str(x["id"])
                    break
            progress = {
                "total_items": len(raw_items),
                "pending": sum(1 for x in raw_items if str(x.get("status")) == "pending"),
                "queued": sum(1 for x in raw_items if str(x.get("status")) == "queued"),
                "parsing": sum(1 for x in raw_items if str(x.get("status")) == "parsing"),
                "ner": sum(1 for x in raw_items if str(x.get("status")) == "ner"),
                "vision": sum(1 for x in raw_items if str(x.get("status")) == "vision"),
                "awaiting_review": sum(1 for x in raw_items if str(x.get("status")) == "awaiting_review"),
                "review_approved": sum(1 for x in raw_items if str(x.get("status")) == "review_approved"),
                "redacting": sum(1 for x in raw_items if str(x.get("status")) == "redacting"),
                "completed": sum(1 for x in raw_items if str(x.get("status")) == "completed"),
                "failed": sum(1 for x in raw_items if str(x.get("status")) == "failed"),
                "cancelled": sum(1 for x in raw_items if str(x.get("status")) == "cancelled"),
            }
            try:
                cfg_row = json.loads(row.get("config_json") or "{}")
            except json.JSONDecodeError:
                cfg_row = {}
            wf_embed = coerce_wizard_furthest_step(cfg_row.get("wizard_furthest_step"))
            step1_ok = infer_batch_step1_configured(cfg_row, jt)
            embed_map[jid] = JobEmbedSummary(
                status=str(row["status"]),
                job_type=jt,
                items=mini,
                progress=progress,
                wizard_furthest_step=wf_embed,
                first_awaiting_review_item_id=first_awaiting_embed,
                batch_step1_configured=step1_ok,
            )
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
    )


@router.post("/files/batch/download")
async def batch_download_zip(request: BatchDownloadRequest):
    """将多个文件打包为 ZIP 下载。"""
    seen: set[str] = set()
    unique_ids: list[str] = []
    for fid in request.file_ids:
        if fid not in seen:
            seen.add(fid)
            unique_ids.append(fid)

    missing: list[str] = []
    pairs: list[tuple[str, str]] = []
    used_names: dict[str, int] = {}

    for fid in unique_ids:
        if fid not in file_store:
            missing.append(fid)
            continue
        info = file_store[fid]
        if request.redacted:
            path = info.get("output_path")
            if not path or not os.path.isfile(path):
                missing.append(fid)
                continue
            base = f"redacted_{os.path.basename(info.get('original_filename', 'file'))}"
        else:
            path = info.get("file_path")
            if not path or not os.path.isfile(path):
                missing.append(fid)
                continue
            base = os.path.basename(info.get("original_filename", "file"))

        safe = os.path.basename(base) or "file"
        n = used_names.get(safe, 0)
        used_names[safe] = n + 1
        arcname = safe if n == 0 else f"{n}_{safe}"
        pairs.append((path, arcname))

    if missing:
        raise HTTPException(status_code=400, detail={"missing": missing})
    if not pairs:
        raise HTTPException(status_code=400, detail="没有可下载的文件（不存在或未脱敏）")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, arcname in pairs:
            zf.write(path, arcname)
    buf.seek(0)
    filename = "redacted_batch.zip" if request.redacted else "original_batch.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def get_file_type(filename: str) -> FileType:
    """根据文件扩展名判断文件类型"""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".doc":
        return FileType.DOC
    elif ext == ".docx":
        return FileType.DOCX
    elif ext in (".txt", ".md", ".rtf", ".html", ".htm"):
        return FileType.TXT
    elif ext == ".pdf":
        return FileType.PDF
    elif ext in (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"):
        return FileType.IMAGE
    else:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")


MAGIC_BYTES = {
    b'%PDF': {'.pdf'},
    b'PK\x03\x04': {'.docx', '.doc'},  # ZIP-based (docx is zip)
    b'\xff\xd8\xff': {'.jpg', '.jpeg'},
    b'\x89PNG': {'.png'},
    b'GIF8': {'.gif'},
    b'BM': {'.bmp'},
    b'RIFF': {'.webp'},
    b'\xd0\xcf\x11\xe0': {'.doc', '.rtf'},  # OLE2 compound
    b'II\x2a\x00': {'.tif', '.tiff'},  # TIFF little-endian
    b'MM\x00\x2a': {'.tif', '.tiff'},  # TIFF big-endian
    b'{\\rtf': {'.rtf'},  # RTF header
}


_TEXT_EXTENSIONS = frozenset({'.txt', '.md', '.rtf', '.html', '.htm'})


def validate_magic_bytes(file_path: str, ext: str) -> bool:
    """Validate file magic bytes match extension. Reject unknown binary signatures."""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(8)
        for magic, exts in MAGIC_BYTES.items():
            if header.startswith(magic):
                return ext in exts
        # 未知签名：仅允许纯文本类扩展名通过（文本文件无固定魔术字节）
        if ext in _TEXT_EXTENSIONS:
            return True
        # 非文本扩展名且无匹配签名 → 拒绝（防止伪造文件）
        return False
    except OSError:
        return False


def validate_file(file: UploadFile) -> None:
    """验证上传的文件"""
    # 检查文件扩展名
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, 
            detail=f"不支持的文件类型: {ext}，支持的类型: {settings.ALLOWED_EXTENSIONS}"
        )


def _register_file_with_job(job_id: str, file_id: str) -> None:
    store = get_job_store()
    row = store.get_job(job_id)
    if not row or row["status"] != JobStatus.DRAFT.value:
        raise HTTPException(status_code=400, detail="任务不存在或已不是草稿，无法追加文件")
    n = len(store.list_items(job_id))
    store.add_item(job_id, file_id, sort_order=n)
    store.touch_job_updated(job_id)


@router.post("/files/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    batch_group_id: Optional[str] = Form(None),
    job_id: Optional[str] = Form(None),
    upload_source: Optional[str] = Form(None),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    上传文件

    支持的文件类型:
    - Word 文档 (.doc, .docx)
    - PDF 文档 (.pdf)
    - 图片 (.jpg, .jpeg, .png)
    """
    cached = check_idempotency(x_idempotency_key)
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
    except (OSError, IOError):
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail="文件保存失败，请稍后重试")

    # 验证文件 magic bytes 与扩展名匹配
    if not validate_magic_bytes(file_path, file_ext):
        os.remove(file_path)
        raise HTTPException(
            status_code=400,
            detail=f"文件内容与扩展名 {file_ext} 不匹配，可能是伪造文件",
        )

    # 病毒扫描（ClamAV 不可用时降级放行并告警）
    from app.core.virus_scan import scan_file as _virus_scan
    scan_result = _virus_scan(file_path)
    if not scan_result.clean:
        os.remove(file_path)
        raise HTTPException(
            status_code=400,
            detail=f"文件包含恶意内容: {scan_result.virus_name}",
        )
    if scan_result.error:
        logger.warning("Virus scan degraded for %s: %s", file_path, scan_result.error)

    file_type = get_file_type(file.filename)
    # Prometheus: 记录上传
    from app.core.metrics import FILE_UPLOAD_TOTAL
    FILE_UPLOAD_TOTAL.labels(file_type=file_type.value if hasattr(file_type, 'value') else str(file_type)).inc()

    created_at = datetime.now(timezone.utc)
    jid = _sanitize_job_id(job_id)
    bg = _sanitize_batch_group_id(batch_group_id)
    if jid:
        bg = jid

    us = _sanitize_upload_source(upload_source)
    if jid:
        eff_source = "batch"
    elif bg:
        eff_source = "batch"
    else:
        if us == "batch":
            raise HTTPException(
                status_code=400,
                detail="upload_source=batch 时必须提供 batch_group_id 或 job_id",
            )
        eff_source = us or "playground"

    # 存储文件元信息 — sanitize original filename to prevent injection
    safe_original = os.path.basename(file.filename or "unnamed") if file.filename else "unnamed"
    # Strip control characters and null bytes
    safe_original = re.sub(r'[\x00-\x1f\x7f]', '', safe_original)
    if not safe_original or safe_original.startswith('.'):
        safe_original = f"upload{file_ext}"
    rec: dict = {
        "id": file_id,
        "original_filename": safe_original,
        "stored_filename": stored_filename,
        "file_path": file_path,
        "file_type": file_type,
        "file_size": file_size,
        "created_at": created_at.isoformat(),
        "upload_source": eff_source,
    }
    if bg:
        rec["batch_group_id"] = bg
    if jid:
        rec["job_id"] = jid
    async with _file_store_lock:
        file_store.set(file_id, rec)
    if jid:
        try:
            _register_file_with_job(jid, file_id)
        except HTTPException:
            raise  # 400 等客户端错误直接抛出
        except Exception:
            # Rollback: remove file from store and disk
            logger.exception("Failed to register file %s with job %s, rolling back", file_id, jid)
            async with _file_store_lock:
                file_store.pop(file_id, None)
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(status_code=500, detail="任务注册失败，文件已回滚")
    audit_log("upload", "file", file_id, detail={"filename": file.filename})

    response = FileUploadResponse(
        file_id=file_id,
        filename=file.filename,
        file_type=file_type,
        file_size=file_size,
        created_at=created_at,
    )
    save_idempotency(x_idempotency_key, response)
    return response


@router.get("/files/{file_id}/parse", response_model=ParseResult)
async def parse_file(file_id: str):
    """
    解析文件内容
    
    - 对于 Word/PDF: 提取文本内容
    - 对于图片/扫描版 PDF: 标记为需要视觉处理
    """
    from app.services.file_parser import FileParser

    # Read snapshot under lock
    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info:
            logger.error("parse_file: file_id=%s NOT in file_store (keys=%d, path=%s)", file_id, len(file_store), file_store._path)
            raise HTTPException(status_code=404, detail="文件不存在")
        snapshot = dict(file_info)

    file_path = snapshot["file_path"]
    file_type = snapshot["file_type"]

    # Long-running parse outside lock
    parser = FileParser()
    result = await parser.parse(file_path, file_type)

    # Write back under lock
    async with _file_store_lock:
        if file_id in file_store:
            file_store.update_fields(file_id, {
                "content": result.content,
                "pages": result.pages,
                "page_count": result.page_count,
                "is_scanned": result.is_scanned,
            })

    result.file_id = file_id
    return result


@router.post("/files/{file_id}/ner/hybrid", response_model=NERResult)
async def hybrid_ner_extract(
    file_id: str,
    request: HybridNERRequest = Body(default=HybridNERRequest()),
):
    """
    混合NER识别 - HaS本地模型 + 正则
    
    工作流程:
    1. Stage 1: HaS 本地模型识别
    2. Stage 2: 正则识别（高置信度模式匹配）
    3. Stage 3: 交叉验证 + 指代消解
    """
    if hasattr(request, 'entity_type_ids') and request.entity_type_ids and len(request.entity_type_ids) > 200:
        raise HTTPException(status_code=400, detail="实体类型数量超过上限（200）")

    # Read snapshot under lock
    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info:
            raise HTTPException(status_code=404, detail="文件不存在")
        snapshot = dict(file_info)

    # 检查是否已解析
    if "content" not in snapshot:
        raise HTTPException(status_code=400, detail="请先解析文件内容")

    # 如果是扫描件，返回空结果（需要视觉处理）
    if snapshot.get("is_scanned", False):
        return NERResult(
            file_id=file_id,
            entities=[],
            entity_count=0,
            entity_summary={},
        )

    content = snapshot["content"]

    # 获取实体类型配置
    from app.api.entity_types import get_enabled_types, entity_types_db

    # 确定要识别的类型
    if request.entity_type_ids:
        entity_types = [entity_types_db[tid] for tid in request.entity_type_ids if tid in entity_types_db]
    else:
        entity_types = get_enabled_types()

    warnings: list[str] = []
    # Check for text truncation before NER
    from app.services.hybrid_ner_service import HybridNERService
    if len(content) > HybridNERService.MAX_TEXT_LENGTH:
        warnings.append(
            f"文本过长（{len(content)} 字符），已截断至 {HybridNERService.MAX_TEXT_LENGTH} 字符，"
            "超出部分未进行识别。"
        )

    try:
        # 执行混合识别（HaS + 正则）— long-running, outside lock
        entities = await perform_hybrid_ner(content, entity_types)

        logger.info("混合识别完成，共 %d 个实体", len(entities))

    except Exception as e:  # broad catch: hybrid NER involves multiple backends (HaS, regex, etc.)
        logger.exception("混合识别失败: %s", e)
        entities = []

    # 统计各类型实体数量
    entity_summary = {}
    for entity in entities:
        entity_type = entity.type
        entity_summary[entity_type] = entity_summary.get(entity_type, 0) + 1

    # Write back under lock
    async with _file_store_lock:
        if file_id in file_store:
            file_store.update_fields(file_id, {"entities": entities})

    return NERResult(
        file_id=file_id,
        entities=entities,
        entity_count=len(entities),
        entity_summary=entity_summary,
        warnings=warnings,
    )


@router.get("/files/{file_id}/ner", response_model=NERResult)
async def extract_entities(file_id: str):
    """
    对文件进行命名实体识别 (NER) - 使用默认实体类型
    
    识别文档中的敏感信息:
    - 人名、机构名
    - 身份证号、电话号码
    - 地址、银行卡号
    - 案件编号等
    """
    # Read snapshot under lock
    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info:
            raise HTTPException(status_code=404, detail="文件不存在")
        snapshot = dict(file_info)

    # 检查是否已解析
    if "content" not in snapshot:
        raise HTTPException(status_code=400, detail="请先解析文件内容")

    # 如果是扫描件，返回空结果（需要视觉处理）
    if snapshot.get("is_scanned", False):
        return NERResult(
            file_id=file_id,
            entities=[],
            entity_count=0,
            entity_summary={},
        )

    from app.api.entity_types import get_enabled_types
    entity_types = get_enabled_types()
    entities = await perform_hybrid_ner(snapshot["content"], entity_types)

    # 统计各类型实体数量
    entity_summary = {}
    for entity in entities:
        entity_type = entity.type
        entity_summary[entity_type] = entity_summary.get(entity_type, 0) + 1

    # 存储识别结果
    async with _file_store_lock:
        if file_id in file_store:
            file_store.update_fields(file_id, {"entities": entities})

    return NERResult(
        file_id=file_id,
        entities=entities,
        entity_count=len(entities),
        entity_summary=entity_summary,
    )


@router.post("/files/{file_id}/ner", response_model=NERResult)
async def extract_entities_with_config(
    file_id: str,
    request: NERRequest = Body(default=NERRequest()),
):
    """
    对文件进行命名实体识别 (NER) - 支持自定义实体类型
    
    可以指定:
    - entity_types: 要识别的内置实体类型列表
    - custom_entity_type_ids: 要识别的自定义实体类型ID列表
    """
    # Read snapshot under lock
    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info:
            raise HTTPException(status_code=404, detail="文件不存在")
        snapshot = dict(file_info)

    # 检查是否已解析
    if "content" not in snapshot:
        raise HTTPException(status_code=400, detail="请先解析文件内容")

    # 如果是扫描件，返回空结果（需要视觉处理）
    if snapshot.get("is_scanned", False):
        return NERResult(
            file_id=file_id,
            entities=[],
            entity_count=0,
            entity_summary={},
        )

    from app.api.entity_types import get_enabled_types
    entity_types = get_enabled_types()
    entities = await perform_hybrid_ner(snapshot["content"], entity_types)

    # 统计各类型实体数量
    entity_summary = {}
    for entity in entities:
        entity_type = entity.type
        entity_summary[entity_type] = entity_summary.get(entity_type, 0) + 1

    # 存储识别结果
    async with _file_store_lock:
        if file_id in file_store:
            file_store.update_fields(file_id, {"entities": entities})

    return NERResult(
        file_id=file_id,
        entities=entities,
        entity_count=len(entities),
        entity_summary=entity_summary,
    )


@router.get("/files/{file_id}")
async def get_file_info(file_id: str):
    """获取文件信息"""
    async with _file_store_lock:
        info = file_store.get(file_id)
        if not info:
            raise HTTPException(status_code=404, detail="文件不存在")
        return dict(info)


@router.get("/files/{file_id}/download")
async def download_file(file_id: str, redacted: bool = False):
    """
    下载文件
    
    - redacted=False: 下载原始文件
    - redacted=True: 下载脱敏后的文件
    """
    # Read snapshot under lock
    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info:
            raise HTTPException(status_code=404, detail="文件不存在")
        snapshot = dict(file_info)

    if redacted:
        if "output_path" not in snapshot:
            raise HTTPException(status_code=400, detail="文件尚未脱敏")
        file_path = snapshot["output_path"]
        filename = f"redacted_{snapshot['original_filename']}"
    else:
        file_path = snapshot["file_path"]
        filename = snapshot["original_filename"]

    # 路径遍历保护（先检查路径再判断文件是否存在，避免 TOCTOU）
    expected_dir = settings.OUTPUT_DIR if redacted else settings.UPLOAD_DIR
    if not _safe_path_in_dir(file_path, expected_dir):
        raise HTTPException(status_code=403, detail="禁止访问该路径")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


def _safe_path_in_dir(file_path: str, allowed_dir: str) -> bool:
    real_file = os.path.realpath(file_path)
    real_dir = os.path.realpath(allowed_dir)
    return real_file == real_dir or real_file.startswith(real_dir + os.sep)


@router.delete("/files/{file_id}")
async def delete_file(file_id: str):
    """删除文件"""
    # Read and remove under lock
    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info:
            raise HTTPException(status_code=404, detail="文件不存在")
        snapshot = dict(file_info)
        del file_store[file_id]

    # 删除原始文件（验证路径在 UPLOAD_DIR 内，防止路径遍历）
    fp = snapshot.get("file_path", "")
    if fp and os.path.exists(fp) and _safe_path_in_dir(fp, settings.UPLOAD_DIR):
        os.remove(fp)

    # 删除脱敏后的文件（验证路径在 OUTPUT_DIR 内）
    op = snapshot.get("output_path", "")
    if op and os.path.exists(op) and _safe_path_in_dir(op, settings.OUTPUT_DIR):
        os.remove(op)
    audit_log("delete", "file", file_id)

    return APIResponse(message="文件删除成功")
