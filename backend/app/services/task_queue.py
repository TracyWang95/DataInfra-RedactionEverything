"""
进程内异步任务队列。
进程内异步任务队列。
单 GPU 串行处理，无跨进程问题。
队列运行在 FastAPI 主进程的事件循环中，submit 后立即入队，后台逐个消费。
"""

from __future__ import annotations

import asyncio
import bisect
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.services.task_queue_config import (
    _clamp_job_concurrency,
    load_persisted_job_concurrency,
    save_persisted_job_concurrency,
)
from app.services.task_queue_metrics import (
    _effective_vision_page_concurrency,  # noqa: F401  re-exported for tests/API
    _estimate_recognition_task_cost,
    _safe_int,
    _utc_iso,
    _vision_page_concurrency_reason,  # noqa: F401  re-exported for tests/API
)
from app.services.task_queue_pipelines import (
    RecognitionPipelineMixin,
    RedactionPipelineMixin,
    StructuredPipelineMixin,
)

if TYPE_CHECKING:
    from app.services.job_store import JobStore

logger = logging.getLogger(__name__)
_WORKER_ERROR_MSG_MAX_LEN = 200


@dataclass
class TaskItem:
    job_id: str
    item_id: str
    file_id: str
    task_type: str = "recognition"  # "recognition" | "redaction"
    meta: dict[str, Any] = field(default_factory=dict)


class SimpleTaskQueue(RecognitionPipelineMixin, StructuredPipelineMixin, RedactionPipelineMixin):
    """
    单例异步任务队列。

    用法:
        queue = get_task_queue()
        queue.enqueue(TaskItem(job_id=..., item_id=..., file_id=...))

    内部维护一个按优先级排序的待处理列表（_pending_tasks），并用一个
    asyncio.Queue 作为唤醒信号（每个待处理任务对应一个 token），后台 worker
    coroutine 逐个消费。
    """

    def __init__(self, concurrency: int = 1) -> None:
        # Signal queue: one None token per pending task. Workers block on it;
        # the actual TaskItem comes from the sorted _pending_tasks list.
        self._queue: asyncio.Queue[None] = asyncio.Queue()
        self._pending_tasks: list[TaskItem] = []
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
            self._pending_tasks.clear()
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
        self._pending_tasks.clear()
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
        self._insert_pending(task)
        self._queue.put_nowait(None)  # wake one waiting worker
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

    def _insert_pending(self, task: TaskItem) -> None:
        """Insert into the sorted pending list (stable: equal keys keep enqueue order)."""
        try:
            bisect.insort(self._pending_tasks, task, key=self._task_sort_key)
        except Exception:
            # Fallback mirrors the legacy behaviour: on sort failure the new
            # task simply goes to the back of the queue (FIFO position).
            logger.debug("unable to insert task into sorted pending queue", exc_info=True)
            self._pending_tasks.append(task)

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
                await asyncio.wait_for(self._queue.get(), timeout=2.0)
            except TimeoutError:
                if worker_id >= self._concurrency:
                    break
                continue
            except asyncio.CancelledError:
                break

            # One token was consumed, so exactly one pending task is ours.
            # Both structures are only mutated together on the event loop,
            # with no await between the paired mutations.
            task = self._pending_tasks.pop(0)
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
                        error_message=f"worker: {type(exc).__name__}: {str(exc)[:_WORKER_ERROR_MSG_MAX_LEN]}",
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
            pass  # 状态已前进或 job 不存在，忽略

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
                # 还有 item 在跑或排队 — job 保持活跃状态
                if any(s == JobItemStatus.PROCESSING.value for s in sts):
                    self._try_update_job_status(store, job_id, JobStatus.PROCESSING)
                else:
                    self._try_update_job_status(store, job_id, JobStatus.QUEUED)
            elif all(s == JobItemStatus.COMPLETED.value for s in sts):
                self._try_update_job_status(store, job_id, JobStatus.COMPLETED)
            elif all(s == JobItemStatus.FAILED.value for s in sts):
                self._try_update_job_status(store, job_id, JobStatus.FAILED)
            elif all(s in terminal for s in sts):
                # 混合终态：有待审 → AWAITING_REVIEW，否则 COMPLETED（含部分失败）
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
