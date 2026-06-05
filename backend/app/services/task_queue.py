"""
杩涚▼鍐呭紓姝ヤ换鍔￠槦鍒椼€?

鍗?GPU 涓茶澶勭悊锛屾棤璺ㄨ繘绋嬮棶棰樸€?
闃熷垪杩愯鍦?FastAPI 涓昏繘绋嬬殑浜嬩欢寰幆涓紝submit 鍚庣珛鍗冲叆闃燂紝鍚庡彴閫愪釜娑堣垂銆?
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.job_store import JobStore

logger = logging.getLogger(__name__)
_MIN_JOB_CONCURRENCY = 1
_MAX_JOB_CONCURRENCY = 16


def _clamp_job_concurrency(value: Any) -> int:
    return max(_MIN_JOB_CONCURRENCY, min(_MAX_JOB_CONCURRENCY, _safe_int(value, default=3)))


def _runtime_settings_path() -> str:
    from app.core.config import settings

    return os.path.join(settings.DATA_DIR, "runtime_settings.json")


def load_persisted_job_concurrency(default: int) -> int:
    try:
        from app.core.persistence import load_json

        data = load_json(_runtime_settings_path(), default={}) or {}
        if isinstance(data, dict) and "job_concurrency" in data:
            return _clamp_job_concurrency(data.get("job_concurrency"))
    except Exception:
        logger.warning("Unable to load persisted job concurrency", exc_info=True)
    return _clamp_job_concurrency(default)


def save_persisted_job_concurrency(value: int) -> int:
    next_value = _clamp_job_concurrency(value)
    try:
        from app.core.persistence import load_json, save_json

        path = _runtime_settings_path()
        data = load_json(path, default={}) or {}
        if not isinstance(data, dict):
            data = {}
        data["job_concurrency"] = next_value
        save_json(path, data)
    except Exception:
        logger.warning("Unable to persist job concurrency", exc_info=True)
    return next_value


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((time.perf_counter() - started) * 1000)))


def _safe_int(value: Any, *, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _file_type_value(value: Any) -> str:
    value = getattr(value, "value", value)
    return str(value or "").strip().lower()


def _pdf_page_count_from_path(file_info: dict[str, Any]) -> int:
    file_path = file_info.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        return 0
    try:
        import fitz

        doc = fitz.open(file_path)
        try:
            return max(0, int(len(doc)))
        finally:
            doc.close()
    except Exception:
        logger.debug("unable to inspect PDF page count for queue priority", exc_info=True)
        return 0


def _estimate_recognition_task_cost(file_info: dict[str, Any]) -> tuple[int, int]:
    """Return coarse (priority class, work units) for shortest-visible-result scheduling."""
    ft = _file_type_value(file_info.get("file_type"))
    pages = _safe_int(file_info.get("page_count"), default=0)
    if pages <= 0 and ft in {"pdf", "pdf_scanned"}:
        pages = _pdf_page_count_from_path(file_info)
    pages = max(1, pages)

    if ft in {"txt", "doc", "docx"}:
        return (0, max(1, _safe_int(file_info.get("file_size"), default=1) // 16_384))
    if ft == "image":
        return (1, 1)
    if ft in {"pdf", "pdf_scanned"}:
        priority_class = 1 if pages == 1 and not bool(file_info.get("is_scanned")) else 2
        return (priority_class, pages)
    return (3, pages)


def _gpu_memory_ratio(gpu_memory: dict[str, Any] | None) -> float | None:
    if not isinstance(gpu_memory, dict):
        return None
    total_mb = _safe_int(gpu_memory.get("total_mb"), default=0)
    if total_mb <= 0:
        return None
    used_mb = max(0, _safe_int(gpu_memory.get("used_mb"), default=0))
    return max(0.0, min(1.0, used_mb / total_mb))


def _effective_vision_page_concurrency(
    file_info: dict[str, Any],
    pages: int,
    configured: int,
    *,
    gpu_memory: dict[str, Any] | None = None,
) -> int:
    """Return per-file page concurrency for vision recognition.

    Keep the runtime value explicit. Multi-page scanned PDFs are mostly gated
    by the process-wide HaS Text NER slot, so silently increasing concurrency
    can make page latency worse on laptop GPUs. Operators can still raise the
    configured value after measuring their own hardware.
    """
    pages = max(1, int(pages))
    configured = max(1, int(configured))
    gpu_ratio = _gpu_memory_ratio(gpu_memory)
    if gpu_ratio is not None and gpu_ratio >= 0.90:
        return 1
    return min(configured, pages)


def _vision_page_concurrency_reason(
    pages: int,
    configured: int,
    effective: int,
    gpu_memory: dict[str, Any] | None,
) -> str:
    gpu_ratio = _gpu_memory_ratio(gpu_memory)
    if effective == 1 and gpu_ratio is not None and gpu_ratio >= 0.90:
        return "gpu_memory_high"
    if effective < max(1, int(configured)):
        return "page_count"
    return "configured"


def _gpu_memory_metadata(gpu_memory: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(gpu_memory, dict):
        return {"available": False}
    ratio = _gpu_memory_ratio(gpu_memory)
    meta: dict[str, Any] = {
        "available": ratio is not None,
        "used_mb": _safe_int(gpu_memory.get("used_mb"), default=0),
        "total_mb": _safe_int(gpu_memory.get("total_mb"), default=0),
    }
    if ratio is not None:
        meta["used_ratio"] = round(ratio, 4)
    return meta


def _object_field(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def _page_vision_quality_from_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    return {
        "duration_ms": dict(_object_field(result, "duration_ms", {}) or {}),
        "cache_status": dict(_object_field(result, "cache_status", {}) or {}),
        "pipeline_status": dict(_object_field(result, "pipeline_status", {}) or {}),
        "warnings": list(_object_field(result, "warnings", []) or []),
    }


def _page_vision_quality_from_file_info(file_info: dict[str, Any], page: int) -> dict[str, Any]:
    quality_by_page = file_info.get("vision_quality") if isinstance(file_info, dict) else {}
    quality = {}
    if isinstance(quality_by_page, dict):
        quality = quality_by_page.get(page) or quality_by_page.get(str(page)) or {}
    return quality if isinstance(quality, dict) else {}


def _duration_breakdown_from_quality(quality: dict[str, Any]) -> dict[str, Any]:
    """Expose per-pipeline stage timings/status alongside top-level durations."""
    breakdown = dict(quality.get("duration_ms") or {})
    pipeline_status = quality.get("pipeline_status") or {}
    if not isinstance(pipeline_status, dict):
        return breakdown

    for pipeline_name, status in pipeline_status.items():
        if not isinstance(status, dict):
            continue
        stage_status = status.get("stage_duration_ms") or {}
        if not isinstance(stage_status, dict):
            continue
        prefix = str(pipeline_name or "pipeline")
        for key, value in stage_status.items():
            breakdown[f"{prefix}.{key}"] = value
    return breakdown


@dataclass
class TaskItem:
    job_id: str
    item_id: str
    file_id: str
    task_type: str = "recognition"  # "recognition" | "redaction"
    meta: dict[str, Any] = field(default_factory=dict)


class SimpleTaskQueue:
    """
    鍗曚緥寮傛浠诲姟闃熷垪銆?

    用法:
        queue = get_task_queue()
        queue.enqueue(TaskItem(job_id=..., item_id=..., file_id=...))

    鍐呴儴缁存姢涓€涓?asyncio.Queue锛屼竴涓悗鍙?worker coroutine 閫愪釜娑堣垂銆?
    """

    def __init__(self, concurrency: int = 1) -> None:
        self._queue: asyncio.Queue[TaskItem] = asyncio.Queue()
        self._worker_tasks: list[asyncio.Task] = []
        self._running = False
        self._current: dict[int, TaskItem | None] = {}  # worker_id -> current task
        self._pending_items: set[tuple[str, str]] = set()  # (task_type, item_id) dedupe
        self._concurrency = _clamp_job_concurrency(concurrency)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._enqueue_sequence = 0
        self._next_worker_id = 0

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start queue workers during application startup."""
        loop = asyncio.get_event_loop()
        if self._loop is not loop:
            self._queue = asyncio.Queue()
            self._worker_tasks.clear()
            self._current.clear()
            self._pending_items.clear()
            self._loop = loop
        if self._running:
            return
        self._running = True
        for i in range(self._concurrency):
            self._spawn_worker(loop, worker_id=i)
        self._next_worker_id = self._concurrency
        self._watchdog_task = loop.create_task(self._stale_processing_watchdog())
        logger.info("SimpleTaskQueue started (%d worker(s))", self._concurrency)

    def _spawn_worker(self, loop: asyncio.AbstractEventLoop, *, worker_id: int | None = None) -> None:
        if worker_id is None:
            worker_id = self._next_worker_id
            self._next_worker_id += 1
        else:
            self._next_worker_id = max(self._next_worker_id, worker_id + 1)
        task = loop.create_task(self._worker_loop(worker_id=worker_id))
        self._worker_tasks.append(task)

    @property
    def concurrency(self) -> int:
        return self._concurrency

    def set_concurrency(self, value: int, *, persist: bool = True) -> int:
        next_value = _clamp_job_concurrency(value)
        if persist:
            next_value = save_persisted_job_concurrency(next_value)
        self._concurrency = next_value
        if self._running and self._loop is not None:
            live_workers = sum(1 for task in self._worker_tasks if not task.done())
            for _ in range(max(0, next_value - live_workers)):
                self._spawn_worker(self._loop)
        logger.info("SimpleTaskQueue concurrency set to %d", self._concurrency)
        return self._concurrency

    def stop(self) -> list[asyncio.Task]:
        """Stop workers and return tasks for shutdown awaiting."""
        self._running = False
        tasks = []
        for t in self._worker_tasks:
            if not t.done():
                t.cancel()
                tasks.append(t)
        if self._watchdog_task is not None and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            tasks.append(self._watchdog_task)
        self._watchdog_task = None
        self._worker_tasks.clear()
        self._current.clear()
        self._pending_items.clear()
        self._queue = asyncio.Queue()
        self._loop = None
        logger.info("SimpleTaskQueue stopped")
        return tasks

    # ------------------------------------------------------------------
    # 入队
    # ------------------------------------------------------------------

    def enqueue(self, task: TaskItem) -> None:
        task_key = self._task_key(task)
        if task_key in self._pending_items:
            logger.info(
                "skip duplicate enqueue %s  item=%s  (already pending)",
                task.task_type, task.item_id[:8],
            )
            return
        task.meta.setdefault("enqueued_at", _utc_iso())
        task.meta.setdefault("enqueued_perf_counter", time.perf_counter())
        task.meta.setdefault("enqueue_sequence", self._enqueue_sequence)
        self._enqueue_sequence += 1
        self._ensure_task_priority_metadata(task)
        self._record_task_enqueued(task)
        self._pending_items.add(task_key)
        self._queue.put_nowait(task)
        self._sort_pending_queue()
        logger.info(
            "enqueued %s  job=%s item=%s file=%s  priority=%s work=%s (queue_size=%d)",
            task.task_type, task.job_id[:8], task.item_id[:8], task.file_id[:8],
            task.meta.get("priority_class"), task.meta.get("estimated_work_units"),
            self._queue.qsize(),
        )

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def current_task(self) -> TaskItem | None:
        for t in self._current.values():
            if t is not None:
                return t
        return None

    @staticmethod
    def _task_key(task: TaskItem) -> tuple[str, str]:
        return (str(task.task_type or "recognition"), task.item_id)

    def _active_item_ids(self) -> set[str]:
        active = {task.item_id for task in self._current.values() if task is not None}
        active.update(item_id for _task_type, item_id in self._pending_items)
        return active

    def _record_task_enqueued(self, task: TaskItem) -> None:
        try:
            store = self._get_store()
            store.update_item_performance(
                task.item_id,
                {
                    task.task_type: {
                        "queued_at": task.meta.get("enqueued_at"),
                        "queue_size_at_enqueue": self._queue.qsize(),
                    },
                    "queue": {
                        "last_task_type": task.task_type,
                        "last_enqueued_at": task.meta.get("enqueued_at"),
                        "priority_class": task.meta.get("priority_class"),
                        "estimated_work_units": task.meta.get("estimated_work_units"),
                    },
                },
            )
        except Exception:
            logger.debug("unable to record enqueue diagnostics for item %s", task.item_id, exc_info=True)

    def _ensure_task_priority_metadata(self, task: TaskItem) -> None:
        if "priority_class" in task.meta and "estimated_work_units" in task.meta:
            return
        priority_class, work_units = self._estimate_task_cost(task)
        task.meta.setdefault("priority_class", priority_class)
        task.meta.setdefault("estimated_work_units", work_units)

    def _estimate_task_cost(self, task: TaskItem) -> tuple[int, int]:
        if task.task_type == "structured":
            return (0, 1)
        if task.task_type != "recognition":
            return (20, 1)
        try:
            from app.services.file_operations import get_file_info

            info = get_file_info(task.file_id) or {}
        except Exception:
            logger.debug("unable to inspect file metadata for queue priority: %s", task.file_id, exc_info=True)
            info = {}
        return _estimate_recognition_task_cost(info)

    def _task_sort_key(self, task: TaskItem) -> tuple[int, int, int, int]:
        task_type_order = 0 if task.task_type in {"structured", "recognition"} else 1
        return (
            task_type_order,
            _safe_int(task.meta.get("priority_class"), default=99),
            max(1, _safe_int(task.meta.get("estimated_work_units"), default=1)),
            _safe_int(task.meta.get("enqueue_sequence"), default=0),
        )

    def _sort_pending_queue(self) -> None:
        try:
            pending = sorted(list(self._queue._queue), key=self._task_sort_key)  # noqa: SLF001
            self._queue._queue.clear()  # noqa: SLF001
            self._queue._queue.extend(pending)  # noqa: SLF001
        except Exception:
            logger.debug("unable to reorder pending queue", exc_info=True)

    def _record_task_started(self, task: TaskItem, store: Any) -> None:
        started_at = _utc_iso()
        enqueued_counter = task.meta.get("enqueued_perf_counter")
        wait_ms = None
        if isinstance(enqueued_counter, (int, float)):
            wait_ms = max(0, int(round((time.perf_counter() - float(enqueued_counter)) * 1000)))
        patch: dict[str, Any] = {
            task.task_type: {
                "started_at": started_at,
            },
            "queue": {
                "last_task_type": task.task_type,
                "last_started_at": started_at,
            },
        }
        if wait_ms is not None:
            patch[task.task_type]["queue_wait_ms"] = wait_ms
            patch["queue"]["last_wait_ms"] = wait_ms
        try:
            store.update_item_performance(task.item_id, patch)
        except Exception:
            logger.debug("unable to record start diagnostics for item %s", task.item_id, exc_info=True)

    def _record_item_performance(self, store: Any, item_id: str, patch: dict[str, Any]) -> None:
        try:
            store.update_item_performance(item_id, patch)
        except Exception:
            logger.debug("unable to record performance diagnostics for item %s", item_id, exc_info=True)

    # ------------------------------------------------------------------
    # 后台 worker
    # ------------------------------------------------------------------

    async def _stale_processing_watchdog(self) -> None:
        from app.core.config import settings

        interval_seconds = 30.0
        max_age_seconds = max(120.0, float(settings.BATCH_RECOGNITION_PAGE_TIMEOUT) * 2)
        while self._running:
            try:
                await asyncio.sleep(interval_seconds)
                store = self._get_store()
                repaired = store.repair_stale_processing_items(
                    exclude_item_ids=self._active_item_ids(),
                    max_age_seconds=max_age_seconds,
                )
                for row in repaired:
                    self.enqueue(
                        TaskItem(
                            job_id=str(row["job_id"]),
                            item_id=str(row["item_id"]),
                            file_id=str(row["file_id"]),
                            task_type=str(row.get("task") or "recognition"),
                        )
                    )
                if repaired:
                    logger.warning(
                        "stale processing watchdog requeued %d item(s)",
                        len(repaired),
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("stale processing watchdog failed")

    async def _worker_loop(self, worker_id: int = 0) -> None:
        logger.info("worker-%d loop started", worker_id)
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=2.0)
            except TimeoutError:
                if worker_id >= self._concurrency:
                    break
                continue
            except asyncio.CancelledError:
                break

            self._current[worker_id] = task
            logger.info(
                "worker-%d processing %s  job=%s item=%s file=%s  (remaining=%d)",
                worker_id, task.task_type, task.job_id[:8], task.item_id[:8],
                task.file_id[:8], self._queue.qsize(),
            )
            should_exit = False
            try:
                if task.task_type == "recognition":
                    await self._run_recognition(task)
                elif task.task_type == "redaction":
                    await self._run_redaction(task)
                elif task.task_type == "structured":
                    await self._run_structured(task)
                else:
                    logger.warning("unknown task_type: %s", task.task_type)
            except (TimeoutError, OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                logger.error(
                    "task failed: job=%s item=%s: %s: %s",
                    task.job_id[:8], task.item_id[:8],
                    type(exc).__name__, exc,
                )
                try:
                    from app.services.job_store import JobItemStatus
                    store = self._get_store()
                    store.update_item_status(
                        task.item_id, JobItemStatus.FAILED,
                        error_message=f"worker: {type(exc).__name__}: {str(exc)[:200]}",
                    )
                except Exception:
                    pass
            except Exception:
                logger.exception(
                    "task failed (unexpected): job=%s item=%s", task.job_id[:8], task.item_id[:8]
                )
                try:
                    from app.services.job_store import JobItemStatus
                    store = self._get_store()
                    store.update_item_status(
                        task.item_id, JobItemStatus.FAILED,
                        error_message="worker unhandled exception",
                    )
                except Exception:
                    pass
            finally:
                self._current[worker_id] = None
                self._pending_items.discard(self._task_key(task))
                self._queue.task_done()
                logger.info(
                    "done %s  job=%s item=%s  (remaining=%d)",
                    task.task_type, task.job_id[:8], task.item_id[:8],
                    self._queue.qsize(),
                )
                if worker_id >= self._concurrency:
                    should_exit = True
            if should_exit:
                break

        logger.info("worker-%d loop exited", worker_id)

    # ------------------------------------------------------------------
    # 璇嗗埆娴佹按绾?
    # ------------------------------------------------------------------

    async def _run_recognition(self, task: TaskItem) -> None:
        from app.services.job_store import JobItemStatus, JobStatus

        started = time.perf_counter()
        store = self._get_store()
        self._record_task_started(task, store)
        job = store.get_job(task.job_id)
        if not job:
            logger.warning("job %s not found, skip", task.job_id[:8])
            return

        item = store.get_item(task.item_id)
        if not item:
            logger.warning("item %s not found, skip", task.item_id[:8])
            return

        # 璺宠繃宸插畬鎴?/ 宸插彇娑堢殑锛圥ENDING 鍜?PROCESSING 鍏佽閲嶈瘯锛?
        skip_statuses = (
            JobItemStatus.AWAITING_REVIEW.value,
            JobItemStatus.COMPLETED.value,
            JobItemStatus.CANCELLED.value if hasattr(JobItemStatus, "CANCELLED") else "__none__",
        )
        if item["status"] in skip_statuses:
            logger.info("item %s already %s, skip", task.item_id[:8], item["status"])
            return

        # 妫€鏌?job 鏄惁宸茶鍙栨秷
        if job.get("status") == JobStatus.CANCELLED.value:
            logger.info("job %s cancelled, skip item %s", task.job_id[:8], task.item_id[:8])
            return

        cfg = json.loads(job.get("config_json") or "{}")

        try:
            # 鏍囪澶勭悊涓?
            store.update_item_status(task.item_id, JobItemStatus.PROCESSING)
            self._try_update_job_status(store, task.job_id, JobStatus.PROCESSING)

            # 1) 解析
            parse_started = time.perf_counter()
            await self._parse_file(task)
            parse_ms = _elapsed_ms(parse_started)
            self._record_item_performance(store, task.item_id, {"recognition": {"parse_ms": parse_ms}})
            logger.info(
                "[queue] item=%s parse elapsed=%.2fs",
                task.item_id[:8],
                parse_ms / 1000,
            )

            # 2) NER 鎴?Vision
            stage_started = time.perf_counter()
            await self._run_ner_or_vision(task, cfg)
            recognition_stage_ms = _elapsed_ms(stage_started)
            self._record_item_performance(store, task.item_id, {"recognition": {"model_ms": recognition_stage_ms}})
            logger.info(
                "[queue] item=%s recognition stage elapsed=%.2fs",
                task.item_id[:8],
                recognition_stage_ms / 1000,
            )

            # 3) 完成识别
            self._mark_recognition_complete(task, job, store)

        except (FileNotFoundError, OSError) as e:
            err_msg = str(e)[:500]
            logger.error("[queue] item=%s recognition I/O error: %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except (KeyError, ValueError):
                logger.warning("failed to mark item %s as FAILED (item not found or invalid transition)", task.item_id[:8])
        except TimeoutError as e:
            err_msg = str(e)[:500] or "recognition timed out"
            logger.error("[queue] item=%s recognition timeout: %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except (KeyError, ValueError):
                logger.warning("failed to mark item %s as FAILED (item not found or invalid transition)", task.item_id[:8])
        except (RuntimeError, ValueError, KeyError, json.JSONDecodeError) as e:
            err_msg = str(e)[:500]
            logger.error("[queue] item=%s recognition failed: %s: %s", task.item_id[:8], type(e).__name__, err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except (KeyError, ValueError):
                logger.warning("failed to mark item %s as FAILED (item not found or invalid transition)", task.item_id[:8])
        except Exception as e:
            err_msg = str(e)[:500]
            logger.exception("[queue] item=%s recognition failed (unexpected): %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except Exception:
                logger.exception("failed to mark item %s as FAILED", task.item_id[:8])
        finally:
            total_ms = _elapsed_ms(started)
            self._record_item_performance(
                store,
                task.item_id,
                {"recognition": {"finished_at": _utc_iso(), "duration_ms": total_ms}},
            )
            logger.info(
                "[queue] item=%s recognition total elapsed=%.2fs",
                task.item_id[:8],
                total_ms / 1000,
            )
            store.touch_job_updated(task.job_id)
            self._refresh_job_status(store, task.job_id)

    async def _parse_file(self, task: TaskItem) -> None:
        """Parse the uploaded file."""
        from app.services.file_operations import parse_file

        logger.info("[queue] item=%s parse", task.item_id[:8])
        await parse_file(task.file_id)

    async def _run_ner(self, task: TaskItem, entity_type_ids: list) -> None:
        """Run text recognition."""
        from app.services.file_operations import hybrid_ner

        store = self._get_store()
        store.update_item_progress(
            task.item_id,
            stage="ner",
            current=1,
            total=1,
            message="text_recognition_running",
        )
        logger.info("[queue] item=%s NER (%d types)", task.item_id[:8], len(entity_type_ids))
        ner_started = time.perf_counter()
        await hybrid_ner(task.file_id, entity_type_ids)
        self._record_item_performance(
            store,
            task.item_id,
            {
                "recognition": {
                    "mode": "text",
                    "ner_ms": _elapsed_ms(ner_started),
                    "entity_type_count": len(entity_type_ids),
                }
            },
        )
        store.update_item_progress(
            task.item_id,
            stage="ner",
            current=1,
            total=1,
            message="text_recognition_complete",
        )

    async def _run_vision(self, task: TaskItem, cfg: dict) -> None:
        """Run OCR and visual feature recognition for images or scanned pages."""
        from app.core.config import settings
        from app.services.file_operations import get_file_info, vision_detect
        from app.services.vision_config import resolve_optional_type_list

        fi = get_file_info(task.file_id) or {}
        ocr_types = resolve_optional_type_list(cfg, "ocr_has_types", "selected_ocr_has_types")
        configured_visual_types = resolve_optional_type_list(
            cfg,
            "visual_feature_types",
            "visualFeatureTypes",
            "selected_visual_feature_types",
        )
        visual_feature_types = configured_visual_types
        pages = int(fi.get("page_count") or 1)
        vision_started = time.perf_counter()
        logger.info(
            "[queue] item=%s vision (ocr=%s, visual_features=%s, pages=%d)",
            task.item_id[:8],
            len(ocr_types) if ocr_types is not None else "default",
            len(visual_feature_types) if visual_feature_types is not None else "default",
            pages,
        )
        # Pass empty lists as-is (user explicitly deselected a pipeline).
        # Missing keys stay None so orchestrator defaults still apply.
        page_timeout = float(settings.BATCH_RECOGNITION_PAGE_TIMEOUT)
        configured_page_concurrency = int(settings.BATCH_RECOGNITION_PAGE_CONCURRENCY)
        gpu_memory = None
        if pages > 1 and configured_page_concurrency > 1:
            try:
                from app.core.gpu_memory import query_gpu_memory

                gpu_memory = query_gpu_memory()
            except Exception:
                logger.debug("unable to query GPU memory for vision concurrency", exc_info=True)
        page_concurrency = _effective_vision_page_concurrency(
            fi,
            pages,
            configured_page_concurrency,
            gpu_memory=gpu_memory,
        )
        page_concurrency_reason = _vision_page_concurrency_reason(
            pages,
            configured_page_concurrency,
            page_concurrency,
            gpu_memory,
        )
        sparse_probe: dict[str, Any] = {"ran": False}
        if pages > 1 and _file_type_value(fi.get("file_type")) == "pdf_scanned":
            try:
                from app.services.vision_service import prime_pdf_text_layer_sparse_probe

                sparse_probe = await prime_pdf_text_layer_sparse_probe(
                    str(fi.get("file_path") or ""),
                    fi.get("file_type"),
                    page=1,
                )
            except Exception:
                sparse_probe = {"ran": False, "error": "probe_failed"}
                logger.debug("unable to prime scanned PDF text-layer sparse probe", exc_info=True)
        page_sem = asyncio.Semaphore(page_concurrency)
        store = self._get_store()
        store.update_item_progress(
            task.item_id,
            stage="vision",
            current=0,
            total=pages,
            message=f"Vision recognition queued for {pages} page(s)",
        )
        self._record_item_performance(
            store,
            task.item_id,
            {
                "recognition": {
                    "mode": "vision",
                    "page_count": pages,
                    "page_concurrency": page_concurrency,
                    "page_concurrency_configured": configured_page_concurrency,
                    "page_concurrency_reason": page_concurrency_reason,
                    "gpu_memory": _gpu_memory_metadata(gpu_memory),
                    "pdf_text_layer_sparse_probe": sparse_probe,
                    "pages": {},
                }
            },
        )
        active_pages = 0
        max_active_pages = 0

        async def run_page(
            p: int,
            *,
            selected_ocr_types: list[str] | None,
            selected_visual_feature_types: list[str] | None,
            merge_existing: bool = False,
            signature_ocr_types: list[str] | None = None,
            signature_visual_feature_types: list[str] | None = None,
            stage_label: str = "瑙嗚璇嗗埆",
        ) -> None:
            nonlocal active_pages, max_active_pages
            async with page_sem:
                page_started = time.perf_counter()
                page_started_at = _utc_iso()
                active_pages += 1
                max_active_pages = max(max_active_pages, active_pages)
                active_at_start = active_pages
                store.update_item_progress(
                    task.item_id,
                    stage="vision",
                    current=p,
                    total=pages,
                    message=f"{stage_label} page {p}/{pages}",
                )
                logger.info(
                    "[queue] item=%s %s page %d/%d START (page_concurrency=%d active_pages=%d)",
                    task.item_id[:8], stage_label, p, pages, page_concurrency, active_at_start,
                )
                self._record_item_performance(
                    store,
                    task.item_id,
                    {
                        "recognition": {
                            "pages": {
                                str(p): {
                                    "page": p,
                                    "started_at": page_started_at,
                                    "active_pages_at_start": active_at_start,
                                    "page_concurrency": page_concurrency,
                                }
                            }
                        }
                    },
                )
                try:
                    result = await asyncio.wait_for(
                        vision_detect(
                            task.file_id,
                            p,
                            ocr_has_types=selected_ocr_types,
                            visual_feature_types=selected_visual_feature_types,
                            merge_existing=merge_existing,
                            signature_ocr_has_types=signature_ocr_types,
                            signature_visual_feature_types=signature_visual_feature_types,
                        ),
                        timeout=page_timeout,
                    )
                except TimeoutError as exc:
                    page_ms = _elapsed_ms(page_started)
                    active_pages = max(0, active_pages - 1)
                    self._record_item_performance(
                        store,
                        task.item_id,
                        {
                            "recognition": {
                                "pages": {
                                    str(p): {
                                        "finished_at": _utc_iso(),
                                        "duration_ms": page_ms,
                                        "status": "timeout",
                                        "active_pages_at_end": active_pages,
                                    }
                                }
                            }
                        },
                    )
                    raise TimeoutError(
                        f"{stage_label} page {p}/{pages} timed out after {page_timeout:.0f}s"
                    ) from exc
                except Exception:
                    page_ms = _elapsed_ms(page_started)
                    active_pages = max(0, active_pages - 1)
                    self._record_item_performance(
                        store,
                        task.item_id,
                        {
                            "recognition": {
                                "pages": {
                                    str(p): {
                                        "finished_at": _utc_iso(),
                                        "duration_ms": page_ms,
                                        "status": "failed",
                                        "active_pages_at_end": active_pages,
                                    }
                                }
                            }
                        },
                    )
                    raise
                else:
                    page_ms = _elapsed_ms(page_started)
                    active_pages = max(0, active_pages - 1)
                    active_at_end = active_pages
                    quality = _page_vision_quality_from_result(result)
                    if not any(quality.values()):
                        quality = _page_vision_quality_from_file_info(get_file_info(task.file_id) or {}, p)
                    self._record_item_performance(
                        store,
                        task.item_id,
                        {
                            "recognition": {
                                "pages": {
                                    str(p): {
                                        "page": p,
                                        "finished_at": _utc_iso(),
                                        "duration_ms": page_ms,
                                        "status": "completed",
                                        "active_pages_at_end": active_at_end,
                                        "duration_breakdown_ms": _duration_breakdown_from_quality(quality),
                                        "cache_status": dict(quality.get("cache_status") or {}),
                                        "pipeline_status": dict(quality.get("pipeline_status") or {}),
                                        "warnings": list(quality.get("warnings") or []),
                                    }
                                }
                            }
                        },
                    )
                    logger.info(
                        "[queue] item=%s %s page %d/%d DONE elapsed=%.2fs active_pages=%d",
                        task.item_id[:8],
                        stage_label,
                        p,
                        pages,
                        page_ms / 1000,
                        active_at_end,
                    )

        async def run_page_stage(
            *,
            selected_ocr_types: list[str] | None,
            selected_visual_feature_types: list[str] | None,
            merge_existing: bool = False,
            signature_ocr_types: list[str] | None = None,
            signature_visual_feature_types: list[str] | None = None,
            stage_label: str = "瑙嗚璇嗗埆",
        ) -> None:
            page_tasks = {
                asyncio.create_task(
                    run_page(
                        p,
                        selected_ocr_types=selected_ocr_types,
                        selected_visual_feature_types=selected_visual_feature_types,
                        merge_existing=merge_existing,
                        signature_ocr_types=signature_ocr_types,
                        signature_visual_feature_types=signature_visual_feature_types,
                        stage_label=stage_label,
                    )
                ): p
                for p in range(1, max(1, pages) + 1)
            }
            try:
                for page_task in asyncio.as_completed(page_tasks):
                    await page_task
            except Exception:
                for page_task in page_tasks:
                    page_task.cancel()
                raise

        try:
            if pages > 1 and visual_feature_types != []:
                logger.info(
                    "[queue] item=%s vision multi-page scheduling: OCR first (concurrency=%d), then visual features merge pass (concurrency=1)",
                    task.item_id[:8],
                    page_concurrency,
                )
                await run_page_stage(
                    selected_ocr_types=ocr_types,
                    selected_visual_feature_types=[],
                    stage_label="OCR+HaS识别",
                )
                page_sem = asyncio.Semaphore(1)
                await run_page_stage(
                    selected_ocr_types=[],
                    selected_visual_feature_types=visual_feature_types,
                    merge_existing=True,
                    signature_ocr_types=ocr_types,
                    signature_visual_feature_types=visual_feature_types,
                    stage_label="视觉特征识别",
                )
            else:
                await run_page_stage(
                    selected_ocr_types=ocr_types,
                    selected_visual_feature_types=visual_feature_types,
                )
            store.update_item_progress(
                task.item_id,
                stage="vision",
                current=pages,
                total=pages,
                message="vision_recognition_complete",
            )
            self._record_item_performance(
                store,
                task.item_id,
                {
                    "recognition": {
                        "vision_ms": _elapsed_ms(vision_started),
                        "max_active_pages": max_active_pages,
                    }
                },
            )
            logger.info(
                "[queue] item=%s vision total elapsed=%.2fs pages=%d page_concurrency=%d max_active_pages=%d",
                task.item_id[:8],
                time.perf_counter() - vision_started,
                pages,
                page_concurrency,
                max_active_pages,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"vision recognition timed out after {page_timeout:.0f}s per page"
            ) from exc

    async def _run_ner_or_vision(self, task: TaskItem, cfg: dict) -> None:
        """Choose text or vision recognition based on file type."""
        from app.services.file_operations import get_file_info

        fi = get_file_info(task.file_id) or {}
        ft = str(fi.get("file_type", ""))
        is_img = ft == "image" or bool(fi.get("is_scanned"))

        if is_img:
            await self._run_vision(task, cfg)
        else:
            entity_type_ids = list(cfg.get("entity_type_ids") or [])
            await self._run_ner(task, entity_type_ids)

    def _mark_recognition_complete(self, task: TaskItem, job: dict, store: JobStore) -> None:
        """Mark recognition complete and optionally enqueue redaction."""
        from app.services.job_store import JobItemStatus

        skip_review = bool(job.get("skip_item_review"))
        store.update_item_status(task.item_id, JobItemStatus.AWAITING_REVIEW)

        if skip_review:
            # skip_item_review=true: 直接入队匿名化，不等人工审阅
            # 浣跨敤 enqueue() 鑰岄潪鐩存帴 put_nowait()锛岀‘淇濆幓閲嶉€昏緫涓€鑷?
            logger.info("[queue] item=%s skip review, enqueue redaction", task.item_id[:8])
            self.enqueue(TaskItem(
                job_id=task.job_id, item_id=task.item_id,
                file_id=task.file_id, task_type="redaction",
            ))
        else:
            logger.info("[queue] item=%s awaiting_review", task.item_id[:8])

    # ------------------------------------------------------------------
    # 匿名化流水线
    # ------------------------------------------------------------------

    async def _run_structured(self, task: TaskItem) -> None:
        from app.services.job_store import JobItemStatus, JobStatus
        from app.services.structured_service import run_structured_job_item

        started = time.perf_counter()
        store = self._get_store()
        self._record_task_started(task, store)
        job = store.get_job(task.job_id)
        if not job:
            return
        item = store.get_item(task.item_id)
        if not item or item["status"] == JobItemStatus.COMPLETED.value:
            return
        if job.get("status") == JobStatus.CANCELLED.value:
            return

        cfg = json.loads(job.get("config_json") or "{}")
        owner_id = str(job.get("owner_id") or "local_user")
        export_format = str(cfg.get("export_format") or "csv")
        try:
            store.update_item_status(task.item_id, JobItemStatus.PROCESSING)
            self._try_update_job_status(store, task.job_id, JobStatus.PROCESSING)
            result = await run_structured_job_item(
                job_id=task.job_id,
                item_id=task.item_id,
                dataset_id=task.file_id,
                owner_id=owner_id,
                export_format=export_format,
                store=store,
            )
            self._record_item_performance(
                store,
                task.item_id,
                {
                    "structured": {
                        "finished_at": _utc_iso(),
                        "duration_ms": result.get("duration_ms") or _elapsed_ms(started),
                        "export": result.get("export"),
                        "profile": result.get("profile"),
                    }
                },
            )
            store.update_item_status(task.item_id, JobItemStatus.COMPLETED)
            logger.info("[queue] item=%s structured export completed", task.item_id[:8])
        except (RuntimeError, ValueError, KeyError, OSError) as exc:
            err_msg = str(exc)[:500]
            logger.error("[queue] item=%s structured failed: %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except (KeyError, ValueError):
                pass
        except Exception as exc:
            err_msg = str(exc)[:500]
            logger.exception("[queue] item=%s structured failed (unexpected): %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except Exception:
                pass
        finally:
            self._record_item_performance(
                store,
                task.item_id,
                {"structured": {"last_seen_duration_ms": _elapsed_ms(started)}},
            )
            store.touch_job_updated(task.job_id)
            self._refresh_job_status(store, task.job_id)

    async def _run_redaction(self, task: TaskItem) -> None:
        from app.models.schemas import RedactionConfig, ReplacementMode
        from app.services.file_operations import execute_redaction_request, get_file_info
        from app.services.job_store import JobItemStatus

        started = time.perf_counter()
        store = self._get_store()
        self._record_task_started(task, store)
        job = store.get_job(task.job_id)
        if not job:
            return

        item = store.get_item(task.item_id)
        if not item or item["status"] == JobItemStatus.COMPLETED.value:
            return

        cfg = json.loads(job.get("config_json") or "{}")

        try:
            store.update_item_status(task.item_id, JobItemStatus.PROCESSING)

            fi = get_file_info(task.file_id)
            if not fi:
                raise RuntimeError(f"file not found: {task.file_id}")
            if fi.get("output_path"):
                # 已匿名化
                self._record_item_performance(
                    store,
                    task.item_id,
                    {
                        "redaction": {
                            "finished_at": _utc_iso(),
                            "duration_ms": _elapsed_ms(started),
                            "skipped_existing_output": True,
                        }
                    },
                )
                store.update_item_status(task.item_id, JobItemStatus.COMPLETED)
                return

            from app.models.schemas import BoundingBox, Entity
            raw_ents = fi.get("entities") or []
            entities = []
            for e in raw_ents:
                if isinstance(e, Entity):
                    entities.append(e)
                elif isinstance(e, dict):
                    entities.append(Entity.model_validate(e))

            raw_boxes = fi.get("bounding_boxes")
            boxes = []
            if isinstance(raw_boxes, list):
                for b in raw_boxes:
                    if isinstance(b, dict):
                        boxes.append(BoundingBox.model_validate(b))
            elif isinstance(raw_boxes, dict):
                for pk, arr in raw_boxes.items():
                    page_num = int(pk) if str(pk).isdigit() else 1
                    if isinstance(arr, list):
                        for b in arr:
                            if isinstance(b, dict):
                                d = {**b, "page": b.get("page", page_num)}
                                boxes.append(BoundingBox.model_validate(d))

            rm = cfg.get("replacement_mode") or "structured"
            try:
                replacement_mode = ReplacementMode(str(rm))
            except ValueError:
                replacement_mode = ReplacementMode.STRUCTURED

            config = RedactionConfig(
                replacement_mode=replacement_mode,
                entity_types=list(cfg.get("entity_type_ids") or []),
                custom_replacements=dict(cfg.get("custom_replacements") or {}),
                image_redaction_method=cfg.get("image_redaction_method"),
                image_redaction_strength=int(cfg.get("image_redaction_strength") or 75),
                image_fill_color=str(cfg.get("image_fill_color") or "#000000"),
            )
            await execute_redaction_request(task.file_id, entities, boxes, config)
            self._record_item_performance(
                store,
                task.item_id,
                {
                    "redaction": {
                        "finished_at": _utc_iso(),
                        "duration_ms": _elapsed_ms(started),
                        "entity_count": len(entities),
                        "bounding_box_count": len(boxes),
                    }
                },
            )
            store.update_item_status(task.item_id, JobItemStatus.COMPLETED)
            logger.info("[queue] item=%s redaction completed", task.item_id[:8])

        except (FileNotFoundError, OSError) as e:
            err_msg = str(e)[:500]
            logger.error("[queue] item=%s redaction I/O error: %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except (KeyError, ValueError):
                pass
        except (RuntimeError, ValueError, KeyError) as e:
            err_msg = str(e)[:500]
            logger.error("[queue] item=%s redaction failed: %s: %s", task.item_id[:8], type(e).__name__, err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except (KeyError, ValueError):
                pass
        except Exception as e:
            err_msg = str(e)[:500]
            logger.exception("[queue] item=%s redaction failed (unexpected): %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except Exception:
                pass
        finally:
            self._record_item_performance(
                store,
                task.item_id,
                {"redaction": {"last_seen_duration_ms": _elapsed_ms(started)}},
            )
            store.touch_job_updated(task.job_id)
            self._refresh_job_status(store, task.job_id)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _get_store(self) -> JobStore:
        from app.services.job_store import get_job_store
        return get_job_store()

    def _try_update_job_status(self, store, job_id: str, status) -> None:
        from app.services.job_store import InvalidStatusTransition
        try:
            store.update_job_status(job_id, status)
        except (InvalidStatusTransition, KeyError, ValueError):
            pass  # 鐘舵€佸凡鍓嶈繘鎴?job 涓嶅瓨鍦紝蹇界暐

    def _refresh_job_status(self, store, job_id: str) -> None:
        """Refresh the job status from item statuses."""
        from app.services.job_store import JobItemStatus, JobStatus

        job = store.get_job(job_id)
        if not job or job["status"] in (JobStatus.CANCELLED.value,):
            return
        items = store.list_items(job_id)
        if not items:
            return

        sts = [i["status"] for i in items]
        active = {JobItemStatus.PENDING.value, JobItemStatus.PROCESSING.value}
        terminal = {JobItemStatus.AWAITING_REVIEW.value, JobItemStatus.COMPLETED.value, JobItemStatus.FAILED.value}
        try:
            if any(s in active for s in sts):
                # 杩樻湁 item 鍦ㄨ窇鎴栨帓闃?鈥?job 淇濇寔娲昏穬鐘舵€?
                if any(s == JobItemStatus.PROCESSING.value for s in sts):
                    self._try_update_job_status(store, job_id, JobStatus.PROCESSING)
                else:
                    self._try_update_job_status(store, job_id, JobStatus.QUEUED)
            elif all(s == JobItemStatus.COMPLETED.value for s in sts):
                self._try_update_job_status(store, job_id, JobStatus.COMPLETED)
            elif all(s == JobItemStatus.FAILED.value for s in sts):
                self._try_update_job_status(store, job_id, JobStatus.FAILED)
            elif all(s in terminal for s in sts):
                # 娣峰悎缁堟€侊細鏈夊緟瀹?鈫?AWAITING_REVIEW锛屽惁鍒?COMPLETED锛堝惈閮ㄥ垎澶辫触锛?
                if any(s == JobItemStatus.AWAITING_REVIEW.value for s in sts):
                    self._try_update_job_status(store, job_id, JobStatus.AWAITING_REVIEW)
                else:
                    self._try_update_job_status(store, job_id, JobStatus.COMPLETED)
        except Exception:
            logger.warning("_refresh_job_status failed for job %s", job_id[:8], exc_info=True)


# ------------------------------------------------------------------
# 单例
# ------------------------------------------------------------------
_instance: SimpleTaskQueue | None = None


def get_task_queue() -> SimpleTaskQueue:
    global _instance
    if _instance is None:
        from app.core.config import settings
        _instance = SimpleTaskQueue(
            concurrency=load_persisted_job_concurrency(settings.JOB_CONCURRENCY)
        )
    return _instance

