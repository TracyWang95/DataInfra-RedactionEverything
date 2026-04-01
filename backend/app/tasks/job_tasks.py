"""
Celery 任务：批量任务 Worker 的识别与脱敏处理单元。

每个 task 对应一个 JobItem 的一个阶段：
  - process_item      : QUEUED → PARSING → NER/VISION → AWAITING_REVIEW（或直接脱敏）
  - process_redaction : REVIEW_APPROVED → REDACTING → COMPLETED
"""
import asyncio
import logging

from app.celery_app import celery_app

log = logging.getLogger("legal_redaction.job_tasks")


def _get_store_job_item(job_id: str, item_id: str):
    """
    加载 store / job / item；任一不存在则返回 (None, None, None)，调用方直接 return。
    """
    from app.api.jobs import get_job_store

    store = get_job_store()
    job = store.get_job(job_id)
    if not job:
        log.warning("job %s not found, skipping item %s", job_id[:8], item_id[:8])
        return None, None, None
    item = next((i for i in store.list_items(job_id) if i["id"] == item_id), None)
    if not item:
        log.warning("item %s not found in job %s", item_id[:8], job_id[:8])
        return None, None, None
    return store, job, item


@celery_app.task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    name="legal_redaction.process_item",
    # _run_recognition 内部已有 MAX_ITEM_RETRIES=3 指数退避，Celery 层不再重试
    max_retries=0,
)
def process_item(self, job_id: str, item_id: str, file_id: str) -> None:  # type: ignore[override]
    """
    识别流水线：QUEUED → PARSING → NER/VISION → AWAITING_REVIEW（或 skip_review 时直接脱敏完成）。
    """
    from app.services.job_runner import DefaultJobRunnerPorts, _run_recognition
    from app.services.job_store import JobItemStatus

    store, job, item = _get_store_job_item(job_id, item_id)
    if store is None:
        return

    # 允许 QUEUED / PENDING / 卡在中间状态（PARSING/NER/VISION）的 item 继续处理
    PROCESSABLE = {
        JobItemStatus.QUEUED.value,
        JobItemStatus.PENDING.value,
        JobItemStatus.PARSING.value,
        JobItemStatus.NER.value,
        JobItemStatus.VISION.value,
    }
    if item["status"] not in PROCESSABLE:
        log.info(
            "process_item: item %s status=%s（已完成或终态），跳过",
            item_id[:8],
            item["status"],
        )
        return

    log.info(
        "process_item START  job=%s item=%s file=%s status=%s",
        job_id[:8], item_id[:8], file_id[:8], item["status"],
    )
    asyncio.run(_run_recognition(store, DefaultJobRunnerPorts(), job, item_id, file_id))
    log.info("process_item DONE   item=%s", item_id[:8])


@celery_app.task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    name="legal_redaction.process_redaction",
    max_retries=0,
)
def process_redaction(self, job_id: str, item_id: str, file_id: str) -> None:  # type: ignore[override]
    """
    脱敏流水线：REVIEW_APPROVED → REDACTING → COMPLETED。
    """
    from app.services.job_runner import DefaultJobRunnerPorts, _run_redaction
    from app.services.job_store import JobItemStatus

    store, job, item = _get_store_job_item(job_id, item_id)
    if store is None:
        return

    if item["status"] != JobItemStatus.REVIEW_APPROVED.value:
        log.info(
            "process_redaction: item %s status=%s（非 REVIEW_APPROVED），跳过（幂等保护）",
            item_id[:8],
            item["status"],
        )
        return

    log.info(
        "process_redaction START  job=%s item=%s file=%s",
        job_id[:8], item_id[:8], file_id[:8],
    )
    asyncio.run(_run_redaction(store, DefaultJobRunnerPorts(), job, item_id, file_id))
    log.info("process_redaction DONE   item=%s", item_id[:8])
