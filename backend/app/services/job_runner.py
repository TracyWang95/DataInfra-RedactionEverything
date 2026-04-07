# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
批量任务 Worker：识别链路与审阅闸门；可注入 JobRunnerPorts 供测试。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import HTTPException  # caught from API-layer delegates

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
    """识别 / 匿名化步骤（测试替换为 Mock）。"""

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
        except Exception as e:
            logger.debug("_walk_job_to: skip %s→%s for job %s: %s", current, step.value, job_id, e)
        if step == target:
            return


def _refresh_job_status(store: JobStore, job_id: str) -> None:
    """Sync job-level status from item statuses (high-water-mark: only walks forward)."""
    job = store.get_job(job_id)
    if not job or job["status"] == JobStatus.CANCELLED.value:
        return
    items = store.list_items(job_id)
    if not items:
        return
    sts = [i["status"] for i in items]
    if not sts:
        return
    try:
        if all(s == JobItemStatus.COMPLETED.value for s in sts):
            _walk_job_to(store, job_id, JobStatus.COMPLETED)
        elif all(s == JobItemStatus.CANCELLED.value for s in sts):
            store.update_job_status(job_id, JobStatus.CANCELLED)
        elif any(s in ACTIVE_ITEM_STATUSES for s in sts):
            _walk_job_to(store, job_id, JobStatus.RUNNING)
        elif any(s == JobItemStatus.AWAITING_REVIEW.value for s in sts):
            _walk_job_to(store, job_id, JobStatus.AWAITING_REVIEW)
        elif any(s == JobItemStatus.REVIEW_APPROVED.value for s in sts):
            _walk_job_to(store, job_id, JobStatus.REDACTING)
        elif any(s == JobItemStatus.FAILED.value for s in sts):
            active = {JobItemStatus.PENDING.value, JobItemStatus.PROCESSING.value,
                      JobItemStatus.QUEUED.value, JobItemStatus.PARSING.value,
                      JobItemStatus.NER.value, JobItemStatus.VISION.value}
            if any(s in active for s in sts):
                # 还有 item 在跑，不标 FAILED
                pass
            elif all(s == JobItemStatus.FAILED.value for s in sts):
                store.update_job_status(job_id, JobStatus.FAILED)
            else:
                # 混合终态（failed + completed/awaiting_review）
                _walk_job_to(store, job_id, JobStatus.AWAITING_REVIEW)
        else:
            logger.warning("_refresh_job_status: job %s has unhandled item statuses %s, not changing status", job_id, sts)
    except Exception:
        logger.warning("_refresh_job_status: failed to update job %s status (items: %s)", job_id, sts, exc_info=True)




def _job_config_dict(job_row: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(job_row.get("config_json") or "{}")
    except json.JSONDecodeError:
        return {}


MAX_ITEM_RETRIES = 3


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

    for attempt in range(1, MAX_ITEM_RETRIES + 1):
        try:
            store.update_item_status(item_id, JobItemStatus.PARSING)
            try:
                store.update_job_status(job_row["id"], JobStatus.RUNNING)
            except Exception:
                logger.debug("job %s already in non-DRAFT state, skip RUNNING transition", job_row["id"][:8])
            logger.info("[worker] item=%s file=%s → parse_file", item_id[:8], file_id[:8])
            await ports.parse_file(file_id)

            from app.services.file_operations import get_file_info
            fi = get_file_info(file_id) or {}
            ft = str(fi.get("file_type", ""))
            is_img = ft == "image" or bool(fi.get("is_scanned"))
            logger.info("[worker] item=%s file=%s → file_type=%s is_img=%s", item_id[:8], file_id[:8], ft, is_img)
            if is_img:
                store.update_item_status(item_id, JobItemStatus.VISION)
                logger.info("[worker] item=%s file=%s → vision_pages START", item_id[:8], file_id[:8])
                await ports.vision_pages(file_id, cfg)
            else:
                store.update_item_status(item_id, JobItemStatus.NER)
                await ports.hybrid_ner(file_id, entity_type_ids)

            if skip:
                store.update_item_status(item_id, JobItemStatus.REVIEW_APPROVED)
                await _run_redaction(store, ports, job_row, item_id, file_id)
            else:
                store.update_item_status(item_id, JobItemStatus.AWAITING_REVIEW)
            break  # success
        except HTTPException as e:
            err_msg = str(e.detail)[:500]
            if attempt == MAX_ITEM_RETRIES:
                logger.exception("worker item failed (recognition): %s", err_msg)
                store.update_item_status(item_id, JobItemStatus.FAILED, error_message=err_msg)
            else:
                delay = 2 ** (attempt - 1)
                logger.warning("Item %s attempt %d/%d failed: %s, retrying in %ds", item_id, attempt, MAX_ITEM_RETRIES, err_msg, delay)
                await asyncio.sleep(delay)
        except Exception as e:
            err_msg = str(e)[:500]
            if attempt == MAX_ITEM_RETRIES:
                logger.exception("worker item failed (recognition): %s", err_msg)
                store.update_item_status(item_id, JobItemStatus.FAILED, error_message=err_msg)
            else:
                delay = 2 ** (attempt - 1)
                logger.warning("Item %s attempt %d/%d failed: %s, retrying in %ds", item_id, attempt, MAX_ITEM_RETRIES, err_msg, delay)
                await asyncio.sleep(delay)

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
        # 验证匿名化产物：output_path 必须存在才标记完成
        from app.services.file_operations import get_file_info as _get_fi
        _fi = _get_fi(file_id) or {}
        if not _fi.get("output_path"):
            raise RuntimeError(f"redaction returned normally but output_path not set for {file_id}")
        store.update_item_status(item_id, JobItemStatus.COMPLETED)
    except HTTPException as e:
        err_msg = str(e.detail)[:500]
        logger.exception("worker item failed (redaction): %s", err_msg)
        store.update_item_status(item_id, JobItemStatus.FAILED, error_message=err_msg)
    except Exception as e:
        err_msg = str(e)[:500]
        logger.exception("worker item failed (redaction): %s", err_msg)
        store.update_item_status(item_id, JobItemStatus.FAILED, error_message=err_msg)
    finally:
        store.touch_job_updated(job_row["id"])
        _refresh_job_status(store, job_row["id"])




class DefaultJobRunnerPorts(JobRunnerPorts):
    """Default ports that delegate to the service layer (file_operations).

    All imports go through ``app.services.file_operations`` so that this
    module never imports directly from ``app.api.*``.
    """

    async def parse_file(self, file_id: str) -> None:
        from app.services.file_operations import parse_file as _parse
        await _parse(file_id)

    async def hybrid_ner(self, file_id: str, entity_type_ids: list[str]) -> None:
        from app.services.file_operations import hybrid_ner as _ner
        await _ner(file_id, entity_type_ids)

    async def vision_pages(self, file_id: str, job_config: dict[str, Any]) -> None:
        from app.services.file_operations import get_file_info, vision_detect

        ocr_types = list(job_config.get("ocr_has_types") or job_config.get("selected_ocr_has_types") or [])
        has_img = list(job_config.get("has_image_types") or job_config.get("selected_has_image_types") or [])
        fi = get_file_info(file_id) or {}
        pages = int(fi.get("page_count") or 1)
        for p in range(1, max(1, pages) + 1):
            await vision_detect(file_id, p, ocr_types or None, has_img or None)

    async def execute_redaction(self, file_id: str, job_config: dict[str, Any]) -> None:
        from app.services.file_operations import get_file_info, execute_redaction_request
        from app.models.schemas import BoundingBox, Entity, RedactionConfig, ReplacementMode

        fi = get_file_info(file_id)
        if not fi:
            raise RuntimeError(f"文件不存在: {file_id}")
        # 前端已执行匿名化时跳过，避免重复写文件；仍由 _run_redaction 将 item 标为完成
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
        await execute_redaction_request(file_id, entities, boxes_flat, cfg)


def default_job_runner_ports() -> JobRunnerPorts:
    return DefaultJobRunnerPorts()


