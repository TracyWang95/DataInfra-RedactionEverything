"""
文件管理业务逻辑服务层 — 从 api/files.py 提取。

管理 file_store (SQLite) 实例、元数据组装、
JSON→SQLite 迁移、文件上传处理、批量下载 ZIP 等。

文件校验（魔术字节、扩展名、类型推断、路径安全）已提取到
:mod:`app.core.file_validation`，此处仅 re-export 保持向后兼容。
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import ntpath
import os
import re
import shutil
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.file_validation import (  # canonical source; re-exported for backward compat
    MAGIC_BYTES,  # noqa: F401
    get_file_type,
    safe_path_in_dir,
    validate_magic_bytes,
)
from app.core.file_validation import (
    TEXT_EXTENSIONS as _TEXT_EXTENSIONS,  # noqa: F401
)
from app.core.persistence import load_json
from app.models.errors import NotFoundError
from app.models.schemas import (
    BatchDownloadRequest,
    FileType,
    FileUploadResponse,
)
from app.services.file_store_db import FileStoreDB

logger = logging.getLogger(__name__)

_BATCH_GROUP_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")
_BACKEND_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PROJECT_ROOT = os.path.realpath(os.path.join(_BACKEND_ROOT, ".."))

# ---------------------------------------------------------------------------
# Primary file store: SQLite-backed (FileStoreDB)
# ---------------------------------------------------------------------------
_file_store_db_path = os.path.join(settings.DATA_DIR, "file_store.sqlite3")
file_store: FileStoreDB = FileStoreDB(_file_store_db_path)

# Async lock — still needed for atomic read-modify-write sequences
_file_store_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Helpers: sanitize / normalize
# ---------------------------------------------------------------------------

def sanitize_job_id(raw: str | None) -> str | None:
    """任务中心 Job UUID，合法则绑定 job_items。"""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    try:
        uuid.UUID(s)
    except (ValueError, TypeError):
        return None
    return s


def sanitize_upload_source(raw: str | None) -> str | None:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip().lower()
    if s in ("playground", "batch"):
        return s
    return None


def effective_upload_source(info: dict) -> str:
    """兼容旧数据：无字段时按 batch_group_id / job_id 推断。"""
    u = info.get("upload_source")
    if u in ("playground", "batch"):
        return u
    if info.get("job_id") or info.get("batch_group_id"):
        return "batch"
    return "playground"


def file_owner_id(info: dict | None) -> str:
    if not isinstance(info, dict):
        return "local_user"
    return str(info.get("owner_id") or "local_user")


def assert_file_owner(file_id: str, owner_id: str | None) -> dict:
    info = file_store.get(file_id)
    if not info or (owner_id and file_owner_id(info) != owner_id):
        raise NotFoundError("file not found")
    return info


def sanitize_batch_group_id(raw: str | None) -> str | None:
    """批量向导会话 ID：UUID 或短标识，非法则忽略（视为单文件）。"""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if len(s) > 80:
        s = s[:80]
    if not _BATCH_GROUP_ID_RE.match(s):
        return None
    return s


# ---------------------------------------------------------------------------
# File type / validation helpers  (re-exported from app.core.file_validation)
# get_file_type, validate_magic_bytes, safe_path_in_dir, MAGIC_BYTES
# are imported at the top of this module for backward compatibility.
# ---------------------------------------------------------------------------

def normalize_file_type(value: Any) -> Any:
    """Normalize file_type string to FileType enum (used during JSON→SQLite migration)."""
    try:
        return FileType(value) if isinstance(value, str) else value
    except (ValueError, KeyError):
        return value


# ---------------------------------------------------------------------------
# Entity / recognition counting helpers
# ---------------------------------------------------------------------------

def bounding_box_total(info: dict) -> int:
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


def _stored_item_selected(item: Any) -> bool:
    if isinstance(item, dict):
        return item.get("selected") is not False
    return getattr(item, "selected", True) is not False


def _selected_bounding_box_total(info: dict) -> int:
    raw = info.get("bounding_boxes")
    if raw is None:
        return 0
    if isinstance(raw, list):
        return sum(1 for box in raw if _stored_item_selected(box))
    if isinstance(raw, dict):
        n = 0
        for boxes in raw.values():
            if isinstance(boxes, list):
                n += sum(1 for box in boxes if _stored_item_selected(box))
        return n
    return 0


def recognition_count_from_stored_fields(info: dict) -> int:
    """仅从 file_store 已有字段推断条数（不含 redacted_count）。"""
    ents = info.get("entities")
    has_entities = isinstance(ents, list)
    has_boxes = "bounding_boxes" in info
    n_text = sum(1 for ent in ents if _stored_item_selected(ent)) if has_entities else 0
    n_boxes = _selected_bounding_box_total(info) if has_boxes else 0
    if has_entities or has_boxes:
        return n_text + n_boxes
    em = info.get("entity_map")
    if isinstance(em, dict) and len(em) > 0:
        return len(em)
    return 0


def entity_count(info: dict) -> int:
    """
    处理历史、任务项、导出报表里的「识别项」数量。

    这个数表示当前审阅后仍选中的实体/区域数量，不表示文本替换发生次数；
    只有旧记录缺少 entities / bounding_boxes 时才回退到 entity_map。
    """
    return recognition_count_from_stored_fields(info)


# ---------------------------------------------------------------------------
# Path normalization helpers
# ---------------------------------------------------------------------------

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


def _path_leaf_name(path: str) -> str:
    """Return a filename for POSIX, Windows, or accidentally mixed legacy paths."""
    candidates = [
        os.path.basename(path),
        ntpath.basename(path),
        os.path.basename(path.replace("\\", "/")),
    ]
    candidates = [c for c in candidates if c and c not in {".", os.sep}]
    if not candidates:
        return ""
    return min(candidates, key=len)


def _windows_drive_path_to_posix(path: str) -> str | None:
    """Map a Windows drive path to the matching WSL mount path when possible."""
    drive, tail = ntpath.splitdrive(path)
    if not drive or len(drive) < 2 or drive[1] != ":":
        return None
    letter = drive[0].lower()
    tail = tail.replace("\\", "/").lstrip("/")
    return os.path.realpath(os.path.join("/mnt", letter, tail))


def _normalize_store_path(raw: object, preferred_dir: str) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = raw.strip()
    if os.path.isabs(path) and os.path.exists(path):
        return os.path.realpath(path)

    windows_posix = _windows_drive_path_to_posix(path)
    if windows_posix and os.path.exists(windows_posix):
        return windows_posix

    basename = _path_leaf_name(path)
    if basename:
        for directory in _candidate_storage_dirs(preferred_dir):
            candidate = os.path.realpath(os.path.join(directory, basename))
            if os.path.exists(candidate):
                return candidate

    if os.path.isabs(path):
        return os.path.realpath(path)
    return os.path.realpath(os.path.join(preferred_dir, basename or path))


def repair_file_store_paths() -> int:
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


_OUTPUT_ARTIFACT_FIELDS = (
    "output_path",
    "output_file_id",
    "entity_map",
    "redacted_count",
)


def clear_file_output(file_id: str, *, delete_disk: bool = True) -> bool:
    """Remove stale redacted-output signals for a file.

    Returns True when file_store metadata changed. Disk deletion is best-effort
    and limited to OUTPUT_DIR so a bad legacy path cannot remove unrelated data.
    """
    info = file_store.get(file_id)
    if not isinstance(info, dict):
        return False

    next_info = dict(info)
    output_path = next_info.get("output_path")
    changed = False
    for key in _OUTPUT_ARTIFACT_FIELDS:
        if key in next_info:
            next_info.pop(key, None)
            changed = True

    if changed:
        file_store.set(file_id, next_info)

    if delete_disk and isinstance(output_path, str) and output_path.strip():
        try:
            if safe_path_in_dir(output_path, settings.OUTPUT_DIR) and os.path.isfile(output_path):
                os.remove(output_path)
        except OSError:
            logger.warning("Failed to delete stale redacted output for %s: %s", file_id, output_path, exc_info=True)

    return changed


def repair_file_store_output_records() -> int:
    """Drop unsafe output metadata while preserving historical completion state."""
    repaired = 0
    for file_id, info in file_store.items():
        if not isinstance(info, dict):
            continue
        output_path = info.get("output_path")
        if not output_path:
            continue
        if not isinstance(output_path, str):
            if clear_file_output(file_id, delete_disk=False):
                repaired += 1
            continue
        if not safe_path_in_dir(output_path, settings.OUTPUT_DIR):
            if clear_file_output(file_id, delete_disk=False):
                repaired += 1
    return repaired


def restore_file_store_output_from_history() -> int:
    """Restore output metadata that was cleared even though processing history exists."""
    restored = 0
    for file_id, info in file_store.items():
        if not isinstance(info, dict) or info.get("output_path"):
            continue
        history = info.get("redaction_history")
        if not isinstance(history, list):
            continue

        latest_output = next(
            (
                item
                for item in reversed(history)
                if isinstance(item, dict) and isinstance(item.get("output_path"), str) and item["output_path"].strip()
            ),
            None,
        )
        if not latest_output:
            continue

        normalized_output_path = _normalize_store_path(latest_output.get("output_path"), settings.OUTPUT_DIR)
        if not normalized_output_path or not safe_path_in_dir(normalized_output_path, settings.OUTPUT_DIR):
            continue

        next_info = dict(info)
        next_info["output_path"] = normalized_output_path
        for key in ("output_file_id", "entity_map", "redacted_count"):
            if key in latest_output and latest_output[key] is not None:
                next_info[key] = latest_output[key]
        if not isinstance(next_info.get("redacted_count"), int):
            inferred_count = recognition_count_from_stored_fields(next_info)
            if inferred_count > 0:
                next_info["redacted_count"] = inferred_count

        file_store.set(file_id, next_info)
        restored += 1

    return restored


# ---------------------------------------------------------------------------
# JSON → SQLite migration
# ---------------------------------------------------------------------------

def migrate_json_to_sqlite() -> None:
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
            resolved = os.path.realpath(file_path)
            if not os.path.exists(resolved):
                logger.debug("Migration skip: file not found at %s (resolved: %s)", file_path, resolved)
                continue
            info["file_path"] = resolved
        info["file_type"] = normalize_file_type(info.get("file_type"))
        # Backfill redacted_count for old records
        if info.get("output_path") and not isinstance(info.get("redacted_count"), int):
            n = recognition_count_from_stored_fields(info)
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


def run_startup_migrations() -> None:
    """Run JSON→SQLite migration and path normalization.

    Previously executed at module import time; now called explicitly from
    the FastAPI lifespan handler so that imports remain side-effect-free.
    """
    migrate_json_to_sqlite()
    repaired = repair_file_store_paths()
    if repaired:
        logger.info("Normalized %d file_store path records", repaired)
    restored = restore_file_store_output_from_history()
    if restored:
        logger.info("Restored %d file_store output records from history", restored)
    output_repaired = repair_file_store_output_records()
    if output_repaired:
        logger.info("Cleared %d unsafe file_store output records", output_repaired)


# ---------------------------------------------------------------------------
# File list building  (re-exported from app.services.file_list_service)
# ---------------------------------------------------------------------------
from app.services.file_list_service import (  # noqa: E402, F401
    build_file_list_items,
    build_job_embed_map,
    group_and_sort_items,
)

# ---------------------------------------------------------------------------
# File upload processing
# ---------------------------------------------------------------------------

async def process_upload(
    file_path: str,
    file_ext: str,
    filename: str,
    file_size: int,
    batch_group_id: str | None,
    job_id: str | None,
    upload_source: str | None,
    owner_id: str = "local_user",
) -> tuple:
    """
    Core upload processing after the file has been saved to disk.
    Validates magic bytes, runs virus scan, registers in file_store.
    Returns (FileUploadResponse, Optional[str] job_id). Raises ValueError/RuntimeError on failure.
    """
    # 验证文件 magic bytes 与扩展名匹配
    if not validate_magic_bytes(file_path, file_ext):
        os.remove(file_path)
        raise ValueError(f"文件内容与扩展名 {file_ext} 不匹配，可能是伪造文件")

    # 病毒扫描
    from app.core.virus_scan import scan_file as _virus_scan
    scan_result = _virus_scan(file_path)
    if not scan_result.clean:
        os.remove(file_path)
        raise ValueError(f"文件包含恶意内容: {scan_result.virus_name}")
    if scan_result.error:
        logger.warning("Virus scan degraded for %s: %s", file_path, scan_result.error)

    ft = get_file_type(filename)
    if ft is None:
        ext = os.path.splitext(filename)[1].lower()
        os.remove(file_path)
        raise ValueError(f"不支持的文件类型: {ext}")

    # Prometheus: 记录上传
    from app.core.metrics import FILE_UPLOAD_TOTAL
    FILE_UPLOAD_TOTAL.labels(file_type=ft.value if hasattr(ft, 'value') else str(ft)).inc()

    file_id = os.path.splitext(os.path.basename(file_path))[0]
    created_at = datetime.now(UTC)
    jid = sanitize_job_id(job_id)
    bg = sanitize_batch_group_id(batch_group_id)
    if jid:
        bg = jid

    us = sanitize_upload_source(upload_source)
    if jid:
        eff_source = "batch"
    elif bg:
        eff_source = "batch"
    else:
        if us == "batch":
            raise ValueError("upload_source=batch 时必须提供 batch_group_id 或 job_id")
        eff_source = us or "playground"

    # Sanitize original filename
    safe_original = os.path.basename(filename or "unnamed") if filename else "unnamed"
    safe_original = re.sub(r'[\x00-\x1f\x7f]', '', safe_original)
    if not safe_original or safe_original.startswith('.'):
        safe_original = f"upload{file_ext}"

    rec: dict = {
        "id": file_id,
        "original_filename": safe_original,
        "stored_filename": os.path.basename(file_path),
        "file_path": file_path,
        "file_type": ft,
        "file_size": file_size,
        "created_at": created_at.isoformat(),
        "upload_source": eff_source,
        "owner_id": owner_id or "local_user",
    }
    if bg:
        rec["batch_group_id"] = bg
    if jid:
        rec["job_id"] = jid

    async with _file_store_lock:
        file_store.set(file_id, rec)

    return FileUploadResponse(
        file_id=file_id,
        filename=filename,
        file_type=ft,
        file_size=file_size,
        created_at=created_at,
    ), jid


def register_file_with_job(job_id: str, file_id: str, owner_id: str | None = None) -> str:
    """Register uploaded file with a batch job (add as job item)."""
    from app.services.batch_mode_validation import validate_file_allowed_for_job_type
    from app.services.job_store import JobStatus

    store = _get_job_store()
    row = store.get_job(job_id)
    if not row or row["status"] != JobStatus.DRAFT.value:
        raise ValueError("任务不存在或已不是草稿，无法追加文件")
    if owner_id and str(row.get("owner_id") or "local_user") != owner_id:
        raise ValueError("job not found")
    file_info = assert_file_owner(file_id, owner_id) if owner_id else file_store.get(file_id)
    validate_file_allowed_for_job_type(
        job_type=row["job_type"],
        file_info=file_info,
        file_id=file_id,
    )
    n = len(store.list_items(job_id))
    item_id = store.add_item(job_id, file_id, sort_order=n)
    try:
        store.touch_job_updated(job_id)
    except Exception:
        store.delete_item(item_id)
        raise
    return item_id


async def rollback_upload(file_id: str, file_path: str) -> None:
    """Rollback a file upload by removing from store and disk."""
    async with _file_store_lock:
        try:
            file_store.pop(file_id, None)
        except Exception:
            logger.warning("Failed to remove rolled-back upload %s from file store", file_id, exc_info=True)
    if os.path.exists(file_path):
        os.remove(file_path)


def _get_job_store():
    """Deferred import to avoid circular dependency."""
    from app.services.job_store import get_job_store
    return get_job_store()


# ---------------------------------------------------------------------------
# Batch download ZIP
# ---------------------------------------------------------------------------

def collect_batch_zip_entries(
    request: BatchDownloadRequest,
    owner_id: str | None = None,
) -> tuple[list[tuple[str, str, int]], dict[str, Any]]:
    """筛选可导出的文件并附 st_size，供同步 zip 与异步分卷导出共用。

    Returns ([(path, arcname, size_bytes)], manifest)。不打包、不读文件内容，
    对 1 万文件也只是 1 万次 stat —— 这就是"1 万个文件导出多大"的秒回预估来源。
    """
    seen: set[str] = set()
    unique_ids: list[str] = []
    for fid in request.file_ids:
        if fid not in seen:
            seen.add(fid)
            unique_ids.append(fid)

    skipped: list[dict[str, str]] = []
    included: list[dict[str, Any]] = []
    pairs: list[tuple[str, str, int]] = []
    used_names: dict[str, int] = {}
    item_status_map: dict[str, dict[str, str]] = {}
    if request.redacted:
        try:
            item_status_map = _get_job_store().batch_find_item_statuses(unique_ids)
        except Exception:
            logger.warning("Unable to read job item statuses for redacted ZIP", exc_info=True)

    for fid in unique_ids:
        info = file_store.get(fid)
        if info is None:
            skipped.append({"file_id": fid, "reason": "file_not_found"})
            continue
        if owner_id and file_owner_id(info) != owner_id:
            skipped.append({"file_id": fid, "reason": "file_not_found"})
            continue
        original_filename = os.path.basename(info.get("original_filename", "file")) or "file"
        if request.redacted:
            item_status = (item_status_map.get(fid) or {}).get("status")
            if item_status and item_status != "completed":
                skipped.append({"file_id": fid, "reason": "job_item_not_delivery_ready"})
                continue
            path = info.get("output_path")
            if not path:
                skipped.append({"file_id": fid, "reason": "missing_redacted_output"})
                continue
            if not safe_path_in_dir(path, settings.OUTPUT_DIR):
                skipped.append({"file_id": fid, "reason": "unsafe_path"})
                continue
            if not os.path.isfile(path):
                skipped.append({"file_id": fid, "reason": "missing_redacted_output"})
                continue
            base = f"redacted_{original_filename}"
        else:
            path = info.get("file_path")
            if not path:
                skipped.append({"file_id": fid, "reason": "missing_original_file"})
                continue
            if not safe_path_in_dir(path, settings.UPLOAD_DIR):
                skipped.append({"file_id": fid, "reason": "unsafe_path"})
                continue
            if not os.path.isfile(path):
                skipped.append({"file_id": fid, "reason": "missing_original_file"})
                continue
            base = original_filename

        safe = os.path.basename(base) or "file"
        n = used_names.get(safe, 0)
        used_names[safe] = n + 1
        arcname = safe if n == 0 else f"{n}_{safe}"
        try:
            size = os.path.getsize(path)
        except OSError:
            skipped.append({"file_id": fid, "reason": "missing_redacted_output" if request.redacted else "missing_original_file"})
            used_names[safe] = n  # 回滚占名
            continue
        pairs.append((path, arcname, size))
        included.append({
            "file_id": fid,
            "filename": original_filename,
            "archive_name": arcname,
            "size_bytes": size,
        })

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "redacted": bool(request.redacted),
        "requested_count": len(unique_ids),
        "included_count": len(included),
        "skipped_count": len(skipped),
        "included": included,
        "skipped": skipped,
    }
    return pairs, manifest


def build_batch_zip(request: BatchDownloadRequest, owner_id: str | None = None) -> tuple[bytes, str, dict[str, Any]]:
    """
    Build a ZIP file containing requested files (small batches, in-memory).
    Returns (zip_bytes, filename, manifest). Raises ValueError on errors.
    大批量走异步分卷导出（export_service）；API 层按 EXPORT_SYNC_MAX_* 分流。
    """
    pairs, manifest = collect_batch_zip_entries(request, owner_id)
    if not pairs:
        raise ValueError("没有可下载的文件（不存在或未匿名化）")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, arcname, _size in pairs:
            zf.write(path, arcname)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    buf.seek(0)
    zip_filename = "redacted_batch.zip" if request.redacted else "original_batch.zip"
    return buf.getvalue(), zip_filename, manifest


# ---------------------------------------------------------------------------
# File info / download / delete helpers
# ---------------------------------------------------------------------------

async def get_file_info(file_id: str) -> dict[str, Any] | None:
    """Get file info dict under lock, or None."""
    async with _file_store_lock:
        info = file_store.get(file_id)
        if not info:
            return None
        return dict(info)


async def get_file_snapshot(file_id: str) -> dict[str, Any] | None:
    """Get a snapshot (copy) of file info under lock."""
    async with _file_store_lock:
        info = file_store.get(file_id)
        if not info:
            return None
        return dict(info)


# ---------------------------------------------------------------------------
# 内网落地目录导入（第五段方案一）：inbox/<用户>/ 内文件一键登记进平台。
# 登记链全量复用 process_upload（magic bytes/病毒扫描/file_store/job 挂接）。
# ---------------------------------------------------------------------------

def _safe_owner_segment(owner_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(owner_id or "user")).strip("._")
    return cleaned[:64] or "user"


def import_inbox_dir(owner_id: str) -> str:
    base = settings.IMPORT_INBOX_DIR or os.path.join(settings.DATA_DIR, "import_inbox")
    path = os.path.join(base, _safe_owner_segment(owner_id))
    os.makedirs(path, exist_ok=True)
    return path


def list_import_inbox(owner_id: str) -> dict[str, Any]:
    """列出本人 inbox 内受支持扩展名的文件（上限 20000）。"""
    inbox = import_inbox_dir(owner_id)
    items: list[dict[str, Any]] = []
    try:
        with os.scandir(inbox) as entries:
            for entry in entries:
                if len(items) >= 20000:
                    break
                if not entry.is_file():
                    continue
                ext = os.path.splitext(entry.name)[1].lower()
                if ext not in settings.ALLOWED_EXTENSIONS:
                    continue
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                })
    except OSError:
        logger.exception("import inbox scan failed: %s", inbox)
    items.sort(key=lambda x: x["name"])
    return {"path": inbox, "items": items}


async def import_inbox_files(
    owner_id: str,
    filenames: list[str],
    *,
    job_id: str | None = None,
    batch_group_id: str | None = None,
) -> dict[str, Any]:
    """把 inbox 内选中文件 move 进平台并登记。部分成功语义：单文件失败
    移回 inbox 并继续，返回 imported/failed 明细。"""
    inbox = os.path.realpath(import_inbox_dir(owner_id))
    imported: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for name in filenames[:2000]:
        src = os.path.realpath(os.path.join(inbox, name))
        # 路径穿越防护：必须落在本人 inbox 内
        if os.path.dirname(src) != inbox or not os.path.isfile(src):
            failed.append({"name": name, "reason": "文件不存在"})
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            failed.append({"name": name, "reason": f"不支持的类型 {ext}"})
            continue
        size = os.path.getsize(src)
        if size > settings.MAX_FILE_SIZE:
            failed.append({"name": name, "reason": "文件过大"})
            continue
        # magic bytes 预检在 move 之前做：process_upload 对伪造文件的语义是
        # 直接删除（上传场景合理），inbox 场景必须让原件留在原地给运维核查。
        if not validate_magic_bytes(src, ext):
            failed.append({"name": name, "reason": f"文件内容与扩展名 {ext} 不匹配"})
            continue
        file_id = str(uuid.uuid4())
        dest = os.path.realpath(os.path.join(settings.UPLOAD_DIR, f"{file_id}{ext}"))
        try:
            shutil.move(src, dest)  # 同盘瞬时；跨设备自动 copy+unlink
        except OSError as exc:
            failed.append({"name": name, "reason": f"移动失败: {exc}"})
            continue
        try:
            response, _jid = await process_upload(
                file_path=dest,
                file_ext=ext,
                filename=name,
                file_size=size,
                batch_group_id=batch_group_id,
                job_id=job_id,
                upload_source="batch" if job_id or batch_group_id else None,
                owner_id=owner_id,
            )
            imported.append({"name": name, "file_id": response.file_id})
        except Exception as exc:  # noqa: BLE001 — 单文件失败移回 inbox 继续
            logger.warning("inbox import failed for %s: %s", name, exc)
            try:
                if os.path.exists(dest):
                    shutil.move(dest, src)
            except OSError:
                pass
            reason = str(exc)
            failed.append({"name": name, "reason": reason[:200] or "登记失败"})
    return {"imported": imported, "failed": failed}


async def soft_delete_file(file_id: str) -> dict[str, Any] | None:
    """软删除（R1-4 回收站）：只打 deleted_at 标记，磁盘文件保留。

    过期由 retention 扫描调用 delete_file 真删（TRASH_RETENTION_DAYS）。
    返回快照；文件不存在或已在回收站返回 None。
    """
    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info or file_info.get("deleted_at"):
            return None
        info = dict(file_info)
        info["deleted_at"] = datetime.now(UTC).isoformat()
        file_store.set(file_id, info)
        return info


async def restore_file(file_id: str) -> dict[str, Any] | None:
    """从回收站还原：去掉 deleted_at 标记。"""
    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info or not file_info.get("deleted_at"):
            return None
        info = dict(file_info)
        info.pop("deleted_at", None)
        file_store.set(file_id, info)
        return info


async def list_trashed_files(owner_id: str | None = None) -> list[dict[str, Any]]:
    """回收站清单（带 deleted_at 的记录），按删除时间倒序。"""
    async with _file_store_lock:
        rows = [
            {"file_id": fid, **dict(info)}
            for fid, info in file_store.items()
            if isinstance(info, dict) and info.get("deleted_at")
        ]
    if owner_id is not None:
        rows = [r for r in rows if r.get("owner_id") == owner_id]
    rows.sort(key=lambda r: str(r.get("deleted_at") or ""), reverse=True)
    return rows


async def delete_file(file_id: str) -> dict[str, Any] | None:
    """
    Delete file from store and disk. Returns the snapshot of deleted info,
    or None if file not found.
    """
    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info:
            return None
        snapshot = dict(file_info)
        del file_store[file_id]

    # 删除原始文件
    fp = snapshot.get("file_path", "")
    if fp and os.path.exists(fp) and safe_path_in_dir(fp, settings.UPLOAD_DIR):
        os.remove(fp)

    # 删除匿名化后的文件
    op = snapshot.get("output_path", "")
    if op and os.path.exists(op) and safe_path_in_dir(op, settings.OUTPUT_DIR):
        os.remove(op)

    try:
        _get_job_store().delete_items_for_file(file_id)
    except Exception:
        logger.warning("Failed to delete job item references for file %s", file_id, exc_info=True)

    return snapshot


# ---------------------------------------------------------------------------
# Parse / NER helpers  (re-exported from app.services.file_processing_service)
# ---------------------------------------------------------------------------
from app.services.file_processing_service import (  # noqa: E402, F401
    parse_file,
    run_default_ner,
    run_hybrid_ner,
)

# ---------------------------------------------------------------------------
# Public accessor functions — use these instead of importing module-level
# singletons directly, so that other layers don't couple to internal names.
# ---------------------------------------------------------------------------

def get_file_store() -> FileStoreDB:
    """Return the singleton file-store (SQLite-backed) instance."""
    return file_store


def get_file_store_lock() -> asyncio.Lock:
    """Return the async lock guarding read-modify-write on file_store."""
    return _file_store_lock
