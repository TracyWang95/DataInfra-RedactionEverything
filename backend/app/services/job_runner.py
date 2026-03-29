"""
批量任务 Worker：识别链路与审阅闸门；可注入 JobRunnerPorts 供测试。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException

from app.services.job_store import JobItemStatus, JobStatus, JobStore

ACTIVE_ITEM_STATUSES = frozenset(
    {
        JobItemStatus.QUEUED.value,
        JobItemStatus.PARSING.value,
        JobItemStatus.NER.value,
        JobItemStatus.VISION.value,
        JobItemStatus.REDACTING.value,
    }
)


class JobRunnerPorts:
    """识别 / 脱敏步骤（测试替换为 Mock）。"""

    async def parse_file(self, file_id: str) -> None:
        raise NotImplementedError

    async def hybrid_ner(self, file_id: str, entity_type_ids: list[str]) -> None:
        raise NotImplementedError

    async def vision_pages(self, file_id: str, job_config: dict[str, Any]) -> None:
        raise NotImplementedError

    async def execute_redaction(self, file_id: str, job_config: dict[str, Any]) -> None:
        raise NotImplementedError


def _walk_job_to(store: JobStore, job_id: str, target: JobStatus) -> None:
    """Walk a job through valid transitions to reach the target status."""
    chain = [
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.AWAITING_REVIEW,
        JobStatus.REDACTING,
        JobStatus.COMPLETED,
    ]
    for step in chain:
        current = store.get_job(job_id)["status"]
        if current == target.value:
            return
        try:
            store.update_job_status(job_id, step)
        except Exception:
            pass
        if step == target:
            return


def _refresh_job_status(store: JobStore, job_id: str) -> None:
    job = store.get_job(job_id)
    if not job or job["status"] == JobStatus.CANCELLED.value:
        return
    items = store.list_items(job_id)
    if not items:
        return
    sts = [i["status"] for i in items]
    if all(s == JobItemStatus.COMPLETED.value for s in sts):
        _walk_job_to(store, job_id, JobStatus.COMPLETED)
    elif any(s == JobItemStatus.FAILED.value for s in sts):
        store.update_job_status(job_id, JobStatus.FAILED)
    elif any(s in ACTIVE_ITEM_STATUSES for s in sts):
        _walk_job_to(store, job_id, JobStatus.RUNNING)
    elif any(s == JobItemStatus.AWAITING_REVIEW.value for s in sts):
        _walk_job_to(store, job_id, JobStatus.AWAITING_REVIEW)
    elif any(s == JobItemStatus.REVIEW_APPROVED.value for s in sts):
        _walk_job_to(store, job_id, JobStatus.REDACTING)
    else:
        _walk_job_to(store, job_id, JobStatus.RUNNING)


def _pick_next_item(store: JobStore) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
    jobs = store.list_schedulable_jobs()
    jobs.sort(key=lambda j: -(j.get("priority", 0)))  # Higher priority first

    def items_for_job(jid: str) -> list[dict[str, Any]]:
        return store.list_items(jid)

    for job in jobs:
        st = job["status"]
        if st in (JobStatus.DRAFT.value, JobStatus.CANCELLED.value, JobStatus.COMPLETED.value, JobStatus.FAILED.value):
            continue
        jid = job["id"]
        for it in items_for_job(jid):
            if it["status"] == JobItemStatus.QUEUED.value:
                return job, it
    for job in jobs:
        st = job["status"]
        if st in (JobStatus.DRAFT.value, JobStatus.CANCELLED.value, JobStatus.COMPLETED.value, JobStatus.FAILED.value):
            continue
        jid = job["id"]
        for it in items_for_job(jid):
            if it["status"] == JobItemStatus.REVIEW_APPROVED.value:
                return job, it
    return None


def _job_config_dict(job_row: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(job_row.get("config_json") or "{}")
    except json.JSONDecodeError:
        return {}


async def _run_recognition(
    store: JobStore,
    ports: JobRunnerPorts,
    job_row: dict[str, Any],
    item_id: str,
    file_id: str,
) -> None:
    cfg = _job_config_dict(job_row)
    skip = bool(job_row.get("skip_item_review"))
    entity_type_ids = list(cfg.get("entity_type_ids") or [])

    try:
        store.update_item_status(item_id, JobItemStatus.PARSING)
        store.update_job_status(job_row["id"], JobStatus.RUNNING)
        await ports.parse_file(file_id)

        from app.api.files import file_store as fs
        fi = fs.get(file_id) or {}
        ft = str(fi.get("file_type", ""))
        is_img = ft == "image" or bool(fi.get("is_scanned"))
        if is_img:
            store.update_item_status(item_id, JobItemStatus.VISION)
            await ports.vision_pages(file_id, cfg)
        else:
            store.update_item_status(item_id, JobItemStatus.NER)
            await ports.hybrid_ner(file_id, entity_type_ids)

        if skip:
            store.update_item_status(item_id, JobItemStatus.REVIEW_APPROVED)
            await _run_redaction(store, ports, job_row, item_id, file_id)
        else:
            store.update_item_status(item_id, JobItemStatus.AWAITING_REVIEW)
    except HTTPException as e:
        store.update_item_status(item_id, JobItemStatus.FAILED, str(e.detail))
    except Exception as e:
        store.update_item_status(item_id, JobItemStatus.FAILED, str(e))
    finally:
        store.touch_job_updated(job_row["id"])
        _refresh_job_status(store, job_row["id"])


async def _run_redaction(
    store: JobStore,
    ports: JobRunnerPorts,
    job_row: dict[str, Any],
    item_id: str,
    file_id: str,
) -> None:
    cfg = _job_config_dict(job_row)
    try:
        store.update_item_status(item_id, JobItemStatus.REDACTING)
        await ports.execute_redaction(file_id, cfg)
        store.update_item_status(item_id, JobItemStatus.COMPLETED)
    except HTTPException as e:
        store.update_item_status(item_id, JobItemStatus.FAILED, str(e.detail))
    except Exception as e:
        store.update_item_status(item_id, JobItemStatus.FAILED, str(e))
    finally:
        store.touch_job_updated(job_row["id"])
        _refresh_job_status(store, job_row["id"])


async def process_next_queue_item(
    store: JobStore,
    ports: Optional[JobRunnerPorts] = None,
) -> bool:
    """
    处理队列中下一个 JobItem（单次调用最多推进一条 item 的一条主链路）。
    返回是否发生了实际工作。
    """
    ports = ports or default_job_runner_ports()
    picked = _pick_next_item(store)
    if not picked:
        return False
    job_row, item_row = picked
    item_id = item_row["id"]
    file_id = item_row["file_id"]
    if item_row["status"] == JobItemStatus.QUEUED.value:
        await _run_recognition(store, ports, job_row, item_id, file_id)
        return True
    if item_row["status"] == JobItemStatus.REVIEW_APPROVED.value:
        await _run_redaction(store, ports, job_row, item_id, file_id)
        return True
    return False


class DefaultJobRunnerPorts(JobRunnerPorts):
    async def parse_file(self, file_id: str) -> None:
        from app.api.files import parse_file

        await parse_file(file_id)

    async def hybrid_ner(self, file_id: str, entity_type_ids: list[str]) -> None:
        from app.api.files import HybridNERRequest, hybrid_ner_extract

        await hybrid_ner_extract(file_id, HybridNERRequest(entity_type_ids=entity_type_ids))

    async def vision_pages(self, file_id: str, job_config: dict[str, Any]) -> None:
        from app.api.files import file_store as fs
        from app.api.redaction import VisionDetectRequest, detect_sensitive_regions

        ocr_types = list(job_config.get("ocr_has_types") or job_config.get("selected_ocr_has_types") or [])
        has_img = list(job_config.get("has_image_types") or job_config.get("selected_has_image_types") or [])
        fi = fs.get(file_id) or {}
        pages = int(fi.get("page_count") or 1)
        req = VisionDetectRequest(selected_ocr_has_types=ocr_types or None, selected_has_image_types=has_img or None)
        for p in range(1, max(1, pages) + 1):
            await detect_sensitive_regions(file_id, p, req)

    async def execute_redaction(self, file_id: str, job_config: dict[str, Any]) -> None:
        from app.api.redaction import execute_redaction
        from app.api.files import file_store as fs
        from app.models.schemas import BoundingBox, Entity, RedactionConfig, RedactionRequest, ReplacementMode

        fi = fs.get(file_id)
        if not fi:
            raise HTTPException(status_code=404, detail="文件不存在")
        # 前端已执行脱敏时跳过，避免重复写文件；仍由 _run_redaction 将 item 标为完成
        if fi.get("output_path"):
            return

        raw_ents = fi.get("entities") or []
        entities: list[Entity] = []
        for e in raw_ents:
            if isinstance(e, Entity):
                entities.append(e)
            elif isinstance(e, dict):
                entities.append(Entity.model_validate(e))
        raw_boxes = fi.get("bounding_boxes")
        boxes_flat: list[BoundingBox] = []
        if isinstance(raw_boxes, list):
            for b in raw_boxes:
                if isinstance(b, dict):
                    boxes_flat.append(BoundingBox.model_validate(b))
        elif isinstance(raw_boxes, dict):
            for pk, arr in raw_boxes.items():
                page_num = int(pk) if str(pk).isdigit() else 1
                if not isinstance(arr, list):
                    continue
                for b in arr:
                    if isinstance(b, dict):
                        d = {**b, "page": b.get("page", page_num)}
                        boxes_flat.append(BoundingBox.model_validate(d))

        rm = job_config.get("replacement_mode") or "smart"
        try:
            replacement_mode = ReplacementMode(str(rm))
        except ValueError:
            replacement_mode = ReplacementMode.SMART
        cfg = RedactionConfig(
            replacement_mode=replacement_mode,
            entity_types=list(job_config.get("entity_types") or []),
            custom_entity_types=list(job_config.get("custom_entity_types") or []),
            custom_replacements=dict(job_config.get("custom_replacements") or {}),
            image_redaction_method=job_config.get("image_redaction_method"),
            image_redaction_strength=int(job_config.get("image_redaction_strength") or 25),
            image_fill_color=str(job_config.get("image_fill_color") or "#000000"),
        )
        req = RedactionRequest(file_id=file_id, entities=entities, bounding_boxes=boxes_flat, config=cfg)
        await execute_redaction(req)


def default_job_runner_ports() -> JobRunnerPorts:
    return DefaultJobRunnerPorts()


async def worker_loop_forever(store: JobStore, interval_sec: float = 1.5) -> None:
    """后台协程：定时拉取队列（单进程 Worker）。支持 JOB_CONCURRENCY 并发。"""
    import asyncio
    import logging

    from app.core.config import settings

    log = logging.getLogger("legal_redaction.job_worker")
    ports = default_job_runner_ports()
    active_tasks: set[asyncio.Task[bool]] = set()

    while True:
        try:
            concurrency = max(1, settings.JOB_CONCURRENCY)
            # Clean up finished tasks
            done = {t for t in active_tasks if t.done()}
            for t in done:
                try:
                    t.result()
                except Exception:
                    log.exception("job worker task failed")
            active_tasks -= done

            # Fill up to concurrency limit
            for _ in range(8):
                if len(active_tasks) >= concurrency:
                    break
                picked = _pick_next_item(store)
                if not picked:
                    break
                task = asyncio.create_task(process_next_queue_item(store, ports))
                active_tasks.add(task)
        except Exception:
            log.exception("job worker tick failed")
        await asyncio.sleep(interval_sec)
