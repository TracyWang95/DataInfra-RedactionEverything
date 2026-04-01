"""
进程内异步任务队列 —— 替代 Celery + Redis。

单 GPU 串行处理，无跨进程问题。
队列运行在 FastAPI 主进程的事件循环中，submit 后立即入队，后台逐个消费。
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("legal_redaction.task_queue")


@dataclass
class TaskItem:
    job_id: str
    item_id: str
    file_id: str
    task_type: str = "recognition"  # "recognition" | "redaction"
    meta: dict[str, Any] = field(default_factory=dict)


class SimpleTaskQueue:
    """
    单例异步任务队列。

    用法:
        queue = get_task_queue()
        queue.enqueue(TaskItem(job_id=..., item_id=..., file_id=...))

    内部维护一个 asyncio.Queue，一个后台 worker coroutine 逐个消费。
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[TaskItem] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
        self._current: Optional[TaskItem] = None
        self._pending_items: set[str] = set()  # item_id 去重

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """在 FastAPI startup 事件中调用。"""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.get_event_loop().create_task(self._worker_loop())
        log.info("SimpleTaskQueue started (in-process, sequential)")

    def stop(self) -> None:
        """在 FastAPI shutdown 事件中调用。"""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
        log.info("SimpleTaskQueue stopped")

    # ------------------------------------------------------------------
    # 入队
    # ------------------------------------------------------------------

    def enqueue(self, task: TaskItem) -> None:
        if task.item_id in self._pending_items:
            log.info(
                "skip duplicate enqueue %s  item=%s  (already pending)",
                task.task_type, task.item_id[:8],
            )
            return
        self._pending_items.add(task.item_id)
        self._queue.put_nowait(task)
        log.info(
            "enqueued %s  job=%s item=%s file=%s  (queue_size=%d)",
            task.task_type, task.job_id[:8], task.item_id[:8], task.file_id[:8],
            self._queue.qsize(),
        )

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def current_task(self) -> Optional[TaskItem]:
        return self._current

    # ------------------------------------------------------------------
    # 后台 worker
    # ------------------------------------------------------------------

    async def _worker_loop(self) -> None:
        log.info("worker loop started (strict sequential, 1 item at a time)")
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            self._current = task
            log.info(
                "▶ processing %s  job=%s item=%s file=%s  (remaining=%d)",
                task.task_type, task.job_id[:8], task.item_id[:8],
                task.file_id[:8], self._queue.qsize(),
            )
            try:
                if task.task_type == "recognition":
                    await self._run_recognition(task)
                elif task.task_type == "redaction":
                    await self._run_redaction(task)
                else:
                    log.warning("unknown task_type: %s", task.task_type)
            except Exception:
                log.exception(
                    "task failed: job=%s item=%s", task.job_id[:8], task.item_id[:8]
                )
                # 确保失败的 item 也被标记，不会被跳过
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
                self._current = None
                self._pending_items.discard(task.item_id)
                self._queue.task_done()
                log.info(
                    "■ done %s  job=%s item=%s  (remaining=%d)",
                    task.task_type, task.job_id[:8], task.item_id[:8],
                    self._queue.qsize(),
                )

        log.info("worker loop exited")

    # ------------------------------------------------------------------
    # 识别流水线
    # ------------------------------------------------------------------

    async def _run_recognition(self, task: TaskItem) -> None:
        from app.services.job_store import JobItemStatus, JobStatus, JobStore
        from app.services.file_operations import (
            get_file_info,
            parse_file,
            hybrid_ner,
            vision_detect,
        )
        import json

        store = self._get_store()
        job = store.get_job(task.job_id)
        if not job:
            log.warning("job %s not found, skip", task.job_id[:8])
            return

        item = store.get_item(task.item_id)
        if not item:
            log.warning("item %s not found, skip", task.item_id[:8])
            return

        # 跳过已完成 / 已取消的（PENDING 和 PROCESSING 允许重试）
        skip_statuses = (
            JobItemStatus.AWAITING_REVIEW.value,
            JobItemStatus.COMPLETED.value,
            JobItemStatus.CANCELLED.value if hasattr(JobItemStatus, "CANCELLED") else "__none__",
        )
        if item["status"] in skip_statuses:
            log.info("item %s already %s, skip", task.item_id[:8], item["status"])
            return

        # 检查 job 是否已被取消
        if job.get("status") == JobStatus.CANCELLED.value:
            log.info("job %s cancelled, skip item %s", task.job_id[:8], task.item_id[:8])
            return

        cfg = json.loads(job.get("config_json") or "{}")
        entity_type_ids = list(cfg.get("entity_type_ids") or [])

        try:
            # 标记处理中
            store.update_item_status(task.item_id, JobItemStatus.PROCESSING)
            self._try_update_job_status(store, task.job_id, JobStatus.PROCESSING)

            # 1) 解析
            log.info("[queue] item=%s → parse", task.item_id[:8])
            await parse_file(task.file_id)

            # 2) 判断类型 → NER 或 Vision
            fi = get_file_info(task.file_id) or {}
            ft = str(fi.get("file_type", ""))
            is_img = ft == "image" or bool(fi.get("is_scanned"))

            if is_img:
                log.info("[queue] item=%s → vision", task.item_id[:8])
                ocr_types = list(cfg.get("ocr_has_types") or [])
                has_img_types = list(cfg.get("has_image_types") or [])
                pages = int(fi.get("page_count") or 1)
                for p in range(1, max(1, pages) + 1):
                    await vision_detect(task.file_id, p, ocr_types or None, has_img_types or None)
            else:
                log.info("[queue] item=%s → NER (%d types)", task.item_id[:8], len(entity_type_ids))
                await hybrid_ner(task.file_id, entity_type_ids)

            # 3) 完成识别
            skip_review = bool(job.get("skip_item_review"))
            if skip_review:
                # skip_item_review=true: 直接入队脱敏，不等人工审阅
                store.update_item_status(task.item_id, JobItemStatus.AWAITING_REVIEW)
                log.info("[queue] item=%s → skip review, enqueue redaction", task.item_id[:8])
                self._queue.put_nowait(TaskItem(
                    job_id=task.job_id, item_id=task.item_id,
                    file_id=task.file_id, task_type="redaction",
                ))
                self._pending_items.add(task.item_id)
            else:
                store.update_item_status(task.item_id, JobItemStatus.AWAITING_REVIEW)
                log.info("[queue] item=%s → awaiting_review ✓", task.item_id[:8])

        except Exception as e:
            err_msg = str(e)[:500]
            log.exception("[queue] item=%s recognition failed: %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except Exception:
                log.exception("failed to mark item %s as FAILED", task.item_id[:8])
        finally:
            store.touch_job_updated(task.job_id)
            self._refresh_job_status(store, task.job_id)

    # ------------------------------------------------------------------
    # 脱敏流水线
    # ------------------------------------------------------------------

    async def _run_redaction(self, task: TaskItem) -> None:
        from app.services.job_store import JobItemStatus, JobStore
        from app.services.file_operations import get_file_info, execute_redaction_request
        from app.models.schemas import RedactionConfig, ReplacementMode
        import json

        store = self._get_store()
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
                # 已脱敏
                store.update_item_status(task.item_id, JobItemStatus.COMPLETED)
                return

            from app.models.schemas import Entity, BoundingBox
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
                image_redaction_strength=int(cfg.get("image_redaction_strength") or 25),
                image_fill_color=str(cfg.get("image_fill_color") or "#000000"),
            )
            await execute_redaction_request(task.file_id, entities, boxes, config)
            store.update_item_status(task.item_id, JobItemStatus.COMPLETED)
            log.info("[queue] item=%s → redaction completed ✓", task.item_id[:8])

        except Exception as e:
            err_msg = str(e)[:500]
            log.exception("[queue] item=%s redaction failed: %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except Exception:
                pass
        finally:
            store.touch_job_updated(task.job_id)
            self._refresh_job_status(store, task.job_id)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _get_store(self) -> "JobStore":
        from app.api.jobs import get_job_store
        return get_job_store()

    def _try_update_job_status(self, store, job_id: str, status) -> None:
        try:
            store.update_job_status(job_id, status)
        except Exception:
            pass  # 状态已前进，忽略

    def _refresh_job_status(self, store, job_id: str) -> None:
        """根据所有 item 状态聚合 job 级状态。"""
        from app.services.job_store import JobStatus, JobItemStatus

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
            log.warning("_refresh_job_status failed for job %s", job_id[:8], exc_info=True)


# ------------------------------------------------------------------
# 单例
# ------------------------------------------------------------------
_instance: Optional[SimpleTaskQueue] = None


def get_task_queue() -> SimpleTaskQueue:
    global _instance
    if _instance is None:
        _instance = SimpleTaskQueue()
    return _instance
