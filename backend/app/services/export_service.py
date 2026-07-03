"""异步批量导出服务：分卷 zip 落盘 + 任务注册表 + 大小预估。

与 GPU 任务队列（task_queue.SimpleTaskQueue）刻意分离：导出是纯磁盘 IO，
不应占用识别/脱敏的并发槽，也不该被 GPU watchdog 误判。结构对齐
SimpleTaskQueue 的单例+asyncio.Queue 形态，但只有一个 IO worker。

磁盘布局： {OUTPUT_DIR}/exports/{owner}/{export_id}/part001.zip … + manifest.json
           + export-status.json（进程重启后据此标记未完成任务）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from app.core.config import settings

logger = logging.getLogger(__name__)

# 已压缩格式：zip 里 STORED 免重压缩（省 CPU，体积几乎不变）
_STORED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".docx", ".xlsx", ".pptx", ".zip", ".7z", ".gz"}
_VOLUME_NAME_RE = re.compile(r"^part\d{3}\.zip$|^manifest\.json$|^summary\.json$|^[\w.-]+\.csv$|^[\w.-]+\.xlsx$")
# 每 zip entry 的归档结构开销（local header + central directory，粗略上界）
_ZIP_ENTRY_OVERHEAD_BYTES = 256


def _volume_limits(max_files_per_volume: int | None, max_bytes_per_volume: int | None) -> tuple[int, int]:
    files_cap = max_files_per_volume or int(getattr(settings, "EXPORT_VOLUME_MAX_FILES", 1000))
    bytes_cap = max_bytes_per_volume or int(getattr(settings, "EXPORT_VOLUME_MAX_BYTES", 2 * 1024**3))
    return max(1, files_cap), max(1, bytes_cap)


def estimate_volumes(
    entries: list[tuple[str, str, int]],
    max_files_per_volume: int | None = None,
    max_bytes_per_volume: int | None = None,
) -> dict[str, Any]:
    """基于 st_size 的秒回预估：成品多为已压缩格式，zip 大小 ≈ Σsize。"""
    files_cap, bytes_cap = _volume_limits(max_files_per_volume, max_bytes_per_volume)
    total = sum(size for _p, _a, size in entries)
    volumes = 0
    vol_files = 0
    vol_bytes = 0
    for _path, _arc, size in entries:
        if vol_files == 0:
            volumes += 1
        elif vol_files >= files_cap or vol_bytes + size > bytes_cap:
            volumes += 1
            vol_files = 0
            vol_bytes = 0
        vol_files += 1
        vol_bytes += size
    return {
        "total_bytes": total,
        "file_count": len(entries),
        "estimated_volume_count": max(volumes, 1 if entries else 0),
    }


def write_export_volumes(
    entries: list[tuple[str, str, int]],
    out_dir: str,
    manifest: dict[str, Any],
    progress_cb: Callable[..., None],
    max_files_per_volume: int | None = None,
    max_bytes_per_volume: int | None = None,
) -> list[dict[str, Any]]:
    """分卷写盘（同步函数，调用方用 asyncio.to_thread 包）。内存 O(1)：
    zipfile 对磁盘文件对象流式读写，不在内存攒包。"""
    files_cap, bytes_cap = _volume_limits(max_files_per_volume, max_bytes_per_volume)
    volumes: list[dict[str, Any]] = []
    zf: zipfile.ZipFile | None = None
    vol_files = 0
    vol_bytes = 0

    def _close_current() -> None:
        nonlocal zf
        if zf is None:
            return
        zf.close()
        name = volumes[-1]["name"]
        volumes[-1]["size_bytes"] = os.path.getsize(os.path.join(out_dir, name))
        zf = None

    def _open_next() -> None:
        nonlocal zf, vol_files, vol_bytes
        _close_current()
        name = f"part{len(volumes) + 1:03d}.zip"
        volumes.append({"name": name, "size_bytes": 0, "file_count": 0})
        zf = zipfile.ZipFile(os.path.join(out_dir, name), "w", zipfile.ZIP_DEFLATED)
        vol_files = 0
        vol_bytes = 0

    try:
        _open_next()
        for index, (path, arcname, size) in enumerate(entries):
            if vol_files > 0 and (vol_files >= files_cap or vol_bytes + size > bytes_cap):
                _open_next()
            ext = os.path.splitext(arcname)[1].lower()
            compress = zipfile.ZIP_STORED if ext in _STORED_EXTS else zipfile.ZIP_DEFLATED
            assert zf is not None
            zf.write(path, arcname, compress_type=compress)
            vol_files += 1
            vol_bytes += size
            volumes[-1]["file_count"] = vol_files
            if index % 50 == 0:
                progress_cb(current=index + 1, total=len(entries))
        manifest_payload = {**manifest, "volumes_planned": len(volumes)}
        assert zf is not None
        zf.writestr("manifest.json", json.dumps(manifest_payload, ensure_ascii=False, indent=2))
        _close_current()
    except Exception:
        _close_current()
        raise
    progress_cb(current=len(entries), total=len(entries))

    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({**manifest, "volumes": volumes}, f, ensure_ascii=False, indent=2)
    return volumes


# ---------------------------------------------------------------------------
# 任务管理器
# ---------------------------------------------------------------------------

Runner = Callable[["ExportTask", Callable[..., None]], Awaitable[list[dict[str, Any]]]]


@dataclass
class ExportTask:
    export_id: str
    owner_id: str
    kind: str
    out_dir: str
    title: str = ""
    status: str = "queued"  # queued | running | completed | failed
    error: str | None = None
    progress: dict[str, Any] = field(default_factory=lambda: {"stage": "queued", "current": 0, "total": 0})
    volumes: list[dict[str, Any]] = field(default_factory=list)
    total_bytes: int = 0
    file_count: int = 0
    created_at: str = ""
    finished_at: str | None = None
    runner: Runner | None = None

    def public(self) -> dict[str, Any]:
        return {
            "export_id": self.export_id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "error": self.error,
            "progress": dict(self.progress),
            "volumes": list(self.volumes),
            "total_bytes": self.total_bytes,
            "file_count": self.file_count,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


def exports_root() -> str:
    return os.path.join(settings.OUTPUT_DIR, "exports")


def _safe_filename(name: str) -> str:
    # 与 structured_service.safe_filename 同款语义（目录名安全化）
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "data")).strip("._")
    return stem[:120] or "data"


def _safe_owner_dir(owner_id: str) -> str:
    return os.path.join(exports_root(), _safe_filename(owner_id or "anonymous"))


class ExportTaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, ExportTask] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- lifecycle ----------------------------------------------------------
    def _ensure_worker(self) -> None:
        loop = asyncio.get_running_loop()
        if self._worker is None or self._loop is not loop or self._worker.done():
            self._loop = loop
            self._queue = asyncio.Queue()
            for task in self._tasks.values():
                if task.status == "queued":
                    self._queue.put_nowait(task.export_id)
            self._worker = loop.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        while True:
            export_id = await self._queue.get()
            task = self._tasks.get(export_id)
            if task is None or task.runner is None:
                continue
            task.status = "running"
            task.progress["stage"] = "running"
            self._persist(task)

            def _progress(current: int = 0, total: int = 0, stage: str = "running") -> None:
                task.progress.update({"stage": stage, "current": current, "total": total})

            try:
                task.volumes = await task.runner(task, _progress)
                task.status = "completed"
                task.progress["stage"] = "completed"
            except Exception as exc:  # 导出失败：目录清掉半成品，保留状态文件
                logger.exception("export %s failed", export_id)
                task.status = "failed"
                task.error = str(exc)
                task.progress["stage"] = "failed"
                self._cleanup_partial(task)
            task.finished_at = datetime.now(UTC).isoformat()
            self._persist(task)

    def _cleanup_partial(self, task: ExportTask) -> None:
        try:
            for name in os.listdir(task.out_dir):
                if name.endswith(".zip") or name.endswith(".csv") or name.endswith(".xlsx"):
                    os.remove(os.path.join(task.out_dir, name))
        except OSError:
            logger.warning("unable to clean partial export %s", task.export_id, exc_info=True)

    def _persist(self, task: ExportTask) -> None:
        try:
            with open(os.path.join(task.out_dir, "export-status.json"), "w", encoding="utf-8") as f:
                json.dump(task.public(), f, ensure_ascii=False, indent=2)
        except OSError:
            logger.warning("unable to persist export status %s", task.export_id, exc_info=True)

    # -- API ----------------------------------------------------------------
    def submit(
        self,
        owner_id: str,
        kind: str,
        runner: Runner,
        title: str = "",
        total_bytes: int = 0,
        file_count: int = 0,
    ) -> ExportTask:
        self.cleanup_expired()
        export_id = uuid.uuid4().hex[:16]
        out_dir = os.path.join(_safe_owner_dir(owner_id), export_id)
        os.makedirs(out_dir, exist_ok=True)
        task = ExportTask(
            export_id=export_id,
            owner_id=owner_id,
            kind=kind,
            out_dir=out_dir,
            title=title,
            total_bytes=total_bytes,
            file_count=file_count,
            created_at=datetime.now(UTC).isoformat(),
            runner=runner,
        )
        self._tasks[export_id] = task
        self._persist(task)
        self._ensure_worker()
        self._queue.put_nowait(export_id)
        return task

    def get(self, export_id: str, owner_id: str) -> ExportTask | None:
        task = self._tasks.get(export_id)
        if task is None or task.owner_id != owner_id:
            return None
        return task

    def volume_path(self, export_id: str, owner_id: str, name: str) -> str | None:
        """租户校验 + 文件名白名单 + 目录穿越双保险。"""
        task = self.get(export_id, owner_id)
        if task is None:
            return None
        if not _VOLUME_NAME_RE.match(name or ""):
            return None
        from app.core.file_validation import safe_path_in_dir

        path = os.path.join(task.out_dir, name)
        if not safe_path_in_dir(path, task.out_dir) or not os.path.isfile(path):
            return None
        return path

    def cleanup_expired(self) -> None:
        """惰性 TTL 清理（每次 submit 触发，代价一次目录扫描）。"""
        ttl_sec = float(getattr(settings, "EXPORT_TTL_HOURS", 72)) * 3600
        root = exports_root()
        if not os.path.isdir(root):
            return
        now = time.time()
        for owner in os.listdir(root):
            owner_dir = os.path.join(root, owner)
            if not os.path.isdir(owner_dir):
                continue
            for export_id in os.listdir(owner_dir):
                path = os.path.join(owner_dir, export_id)
                try:
                    if os.path.isdir(path) and now - os.path.getmtime(path) > ttl_sec:
                        shutil.rmtree(path, ignore_errors=True)
                        self._tasks.pop(export_id, None)
                except OSError:
                    continue


export_task_manager = ExportTaskManager()


def write_csv_parts(
    rows,
    out_dir: str,
    base_name: str,
    headers: list[str],
    rows_per_part: int | None = None,
    progress_cb: Callable[..., None] | None = None,
) -> list[dict[str, Any]]:
    """流式写 CSV 并按行数分卷（utf-8-sig，Excel 直开）。内存 O(1)。"""
    import csv

    cap = rows_per_part or int(getattr(settings, "EXPORT_TABLE_ROWS_PER_FILE", 50_000))
    cap = max(1, cap)
    parts: list[dict[str, Any]] = []
    handle = None
    writer = None
    part_rows = 0
    total_rows = 0

    def _open_next() -> None:
        nonlocal handle, writer, part_rows
        _close_current()
        name = f"{base_name}-part{len(parts) + 1:03d}.csv"
        parts.append({"name": name, "size_bytes": 0, "file_count": 0})
        handle = open(os.path.join(out_dir, name), "w", encoding="utf-8-sig", newline="")
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        part_rows = 0

    def _close_current() -> None:
        nonlocal handle
        if handle is None:
            return
        handle.close()
        name = parts[-1]["name"]
        parts[-1]["size_bytes"] = os.path.getsize(os.path.join(out_dir, name))
        parts[-1]["file_count"] = part_rows
        handle = None

    try:
        _open_next()
        for row in rows:
            if part_rows >= cap:
                _open_next()
            assert writer is not None
            writer.writerow(row)
            part_rows += 1
            total_rows += 1
            if progress_cb is not None and total_rows % 500 == 0:
                progress_cb(current=total_rows, total=0)
    finally:
        _close_current()
    return parts


def make_job_data_runner(
    store: Any,
    job_id: str,
    selected_file_ids: list[str] | None,
    include_entities: bool = True,
) -> Runner:
    """批量结果明细导出：files-partNN.csv + entities-partNN.csv + summary.json。"""

    async def runner(task: ExportTask, progress: Callable[..., None]) -> list[dict[str, Any]]:
        import app.services.job_management_service as _jms

        def _write_all() -> list[dict[str, Any]]:
            volumes: list[dict[str, Any]] = []
            summary = _jms.build_export_report(
                store, job_id, selected_file_ids=selected_file_ids, include_files=False
            )
            summary_path = os.path.join(task.out_dir, "summary.json")
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            volumes.append({
                "name": "summary.json",
                "size_bytes": os.path.getsize(summary_path),
                "file_count": 1,
            })
            volumes.extend(write_csv_parts(
                _jms.iter_report_file_rows(store, job_id, selected_file_ids),
                task.out_dir,
                "files",
                _jms.REPORT_FILE_CSV_HEADERS,
                progress_cb=lambda **kw: progress(stage="files.csv", **kw),
            ))
            if include_entities:
                volumes.extend(write_csv_parts(
                    _jms.iter_entity_rows(store, job_id, selected_file_ids),
                    task.out_dir,
                    "entities",
                    _jms.ENTITY_CSV_HEADERS,
                    progress_cb=lambda **kw: progress(stage="entities.csv", **kw),
                ))
            return volumes

        return await asyncio.to_thread(_write_all)

    return runner


def make_batch_files_runner(entries: list[tuple[str, str, int]], manifest: dict[str, Any]) -> Runner:
    async def runner(task: ExportTask, progress: Callable[..., None]) -> list[dict[str, Any]]:
        free = shutil.disk_usage(task.out_dir).free
        need = int(task.total_bytes * 1.05) + 1024**3
        if free < need:
            raise OSError(f"磁盘空间不足：需要约 {need / 1e9:.1f}GB，可用 {free / 1e9:.1f}GB")
        return await asyncio.to_thread(
            write_export_volumes, entries, task.out_dir, manifest, progress
        )

    return runner
