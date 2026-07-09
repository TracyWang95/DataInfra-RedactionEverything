"""
崩溃/热重载后的自愈修复例程（原 JobStore 的 repair_* 簇）。

以 mixin 形式提供，依赖宿主类的 ``self._connect()`` 与
``self._clear_outputs_for_file_ids()``；纯搬运，行为不变。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.job_models import (
    JobItemStatus,
    JobStatus,
    JobType,
    _coerce_performance,
    _deep_merge_dict,
    _utc_iso,
)


class RepairMixin:
    def repair_completed_without_output(self) -> int:
        """Reset completed items without an output file to awaiting review."""
        from app.services.file_management_service import get_file_store
        file_store = get_file_store()
        repaired = 0
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ji.id, ji.file_id, ji.job_id, j.job_type
                FROM job_items ji
                JOIN jobs j ON j.id = ji.job_id
                WHERE ji.status = ?
                """,
                (JobItemStatus.COMPLETED.value,),
            ).fetchall()
            for row in rows:
                if row["job_type"] == JobType.STRUCTURED_BATCH.value:
                    continue
                fid = row["file_id"]
                info = file_store.get(fid)
                if info and info.get("output_path"):
                    continue
                conn.execute(
                    "UPDATE job_items SET status = ?, error_message = NULL, updated_at = ? WHERE id = ?",
                    (JobItemStatus.AWAITING_REVIEW.value, _utc_iso(), row["id"]),
                )
                repaired += 1
                logging.getLogger(__name__).info("repair_completed_without_output: item %s (file %s) reset to awaiting_review", row["id"], fid)
            if repaired:
                # Force affected jobs back because the public state machine does not allow this repair transition.
                affected_jobs = set(
                    row["job_id"]
                    for row in rows
                    if row["job_type"] != JobType.STRUCTURED_BATCH.value
                    and not (file_store.get(row["file_id"]) or {}).get("output_path")
                )
                for jid in affected_jobs:
                    conn.execute(
                        "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                        (JobStatus.AWAITING_REVIEW.value, _utc_iso(), jid),
                    )
                    logging.getLogger(__name__).info(
                        "repair_completed_without_output: job %s reset to awaiting_review", jid
                    )
                conn.commit()
        return repaired

    def repair_failed_missing_files(self) -> int:
        """Repair stale data: file exists but item was wrongly marked as failed."""
        from app.services.file_management_service import get_file_store
        file_store = get_file_store()

        repaired = 0
        affected_jobs: set[str] = set()
        repaired_file_ids: set[str] = set()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ji.id, ji.file_id, ji.job_id, ji.error_message, j.job_type
                FROM job_items ji
                JOIN jobs j ON j.id = ji.job_id
                WHERE ji.status = ?
                """,
                (JobItemStatus.FAILED.value,),
            ).fetchall()
            for row in rows:
                if row["job_type"] == JobType.STRUCTURED_BATCH.value:
                    continue
                err = str(row["error_message"] or "")
                err_lower = err.lower()
                if "file not found" not in err_lower and "not found" not in err_lower:
                    continue

                info = file_store.get(str(row["file_id"]))
                if not isinstance(info, dict):
                    continue
                file_path = info.get("file_path")
                if not isinstance(file_path, str) or not file_path.strip() or not os.path.exists(file_path):
                    continue

                conn.execute(
                    "UPDATE job_items SET status = ?, error_message = NULL, updated_at = ? WHERE id = ?",
                    (JobItemStatus.QUEUED.value, _utc_iso(), row["id"]),
                )
                affected_jobs.add(str(row["job_id"]))
                repaired_file_ids.add(str(row["file_id"]))
                repaired += 1

            for job_id in affected_jobs:
                conn.execute(
                    "UPDATE jobs SET status = ?, error_message = NULL, updated_at = ? WHERE id = ?",
                    (JobStatus.QUEUED.value, _utc_iso(), job_id),
                )

            if repaired:
                conn.commit()

        self._clear_outputs_for_file_ids(repaired_file_ids)

        return repaired

    def repair_stuck_in_flight_items(self) -> list[dict]:
        """
        Reset in-flight items left by a crashed worker.

        - PARSING / NER / VISION -> QUEUED
        - REDACTING -> AWAITING_REVIEW
        This intentionally uses SQL to mirror the other repair routines.
        """
        logger = logging.getLogger(__name__)
        to_redispatch: list[dict] = []
        reset_file_ids: set[str] = set()
        stuck_recognition = [
            JobItemStatus.PARSING.value,
            JobItemStatus.NER.value,
            JobItemStatus.VISION.value,
        ]
        now = _utc_iso()

        with self._connect() as conn:
            # 1. PARSING / NER / VISION -> QUEUED
            placeholders = ",".join("?" for _ in stuck_recognition)
            rows = conn.execute(
                f"SELECT id, job_id, file_id, status FROM job_items WHERE status IN ({placeholders})",
                stuck_recognition,
            ).fetchall()
            affected_jobs: set[str] = set()
            for row in rows:
                conn.execute(
                    "UPDATE job_items SET status = ?, error_message = 'auto-reset: stuck in recognition', updated_at = ? WHERE id = ?",
                    (JobItemStatus.QUEUED.value, now, row["id"]),
                )
                affected_jobs.add(row["job_id"])
                reset_file_ids.add(str(row["file_id"]))
                to_redispatch.append({
                    "item_id": row["id"],
                    "job_id": row["job_id"],
                    "file_id": row["file_id"],
                    "task": "process_item",
                })
                logger.info(
                    "repair_stuck: item %s (status=%s) -> queued, job=%s",
                    row["id"], row["status"], row["job_id"],
                )

            # 2. REDACTING -> AWAITING_REVIEW
            redacting_rows = conn.execute(
                "SELECT id, job_id, file_id FROM job_items WHERE status = ?",
                (JobItemStatus.REDACTING.value,),
            ).fetchall()
            for row in redacting_rows:
                conn.execute(
                    "UPDATE job_items SET status = ?, error_message = 'auto-reset: stuck in redaction', updated_at = ? WHERE id = ?",
                    (JobItemStatus.AWAITING_REVIEW.value, now, row["id"]),
                )
                affected_jobs.add(row["job_id"])
                reset_file_ids.add(str(row["file_id"]))
                logger.info(
                    "repair_stuck: item %s (REDACTING) -> awaiting_review, job=%s",
                    row["id"], row["job_id"],
                )

            # 3. Move affected terminal jobs back to an active state.
            for job_id in affected_jobs:
                conn.execute(
                    "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ? AND status IN (?, ?)",
                    (JobStatus.QUEUED.value, now, job_id,
                     JobStatus.COMPLETED.value, JobStatus.FAILED.value),
                )

            if to_redispatch or redacting_rows:
                conn.commit()

        self._clear_outputs_for_file_ids(reset_file_ids)
        return to_redispatch

    def repair_stale_processing_items(
        self,
        *,
        exclude_item_ids: set[str] | None = None,
        max_age_seconds: float = 300.0,
    ) -> list[dict[str, Any]]:
        """Reset abandoned PROCESSING items so the in-process queue can resume.

        A healthy worker keeps the current item in memory, so callers pass the
        active item IDs and this repair only touches database rows that are no
        longer owned by a live worker. This covers dev reloads and worker task
        crashes that leave merged ``processing`` rows behind.
        """
        logger = logging.getLogger(__name__)
        excluded = {str(item_id) for item_id in (exclude_item_ids or set()) if item_id}
        cutoff = (datetime.now(UTC) - timedelta(seconds=max(1.0, float(max_age_seconds)))).isoformat()
        to_redispatch: list[dict[str, Any]] = []
        reset_file_ids: set[str] = set()
        now = _utc_iso()

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    ji.id, ji.job_id, ji.file_id, ji.status, ji.progress_stage,
                    ji.progress_updated_at, ji.updated_at, ji.performance_json, j.job_type
                FROM job_items ji
                JOIN jobs j ON j.id = ji.job_id
                WHERE ji.status = ?
                  AND COALESCE(ji.progress_updated_at, ji.updated_at) < ?
                """,
                (JobItemStatus.PROCESSING.value, cutoff),
            ).fetchall()
            affected_jobs: set[str] = set()
            for row in rows:
                item_id = str(row["id"])
                if item_id in excluded:
                    continue
                performance = _deep_merge_dict(
                    _coerce_performance(row["performance_json"]),
                    {
                        "repair": {
                            "stale_processing": {
                                "status": "requeued",
                                "repaired_at": now,
                                "previous_stage": row["progress_stage"],
                                "previous_updated_at": row["progress_updated_at"] or row["updated_at"],
                            }
                        }
                    },
                )
                conn.execute(
                    """
                    UPDATE job_items
                    SET status = ?, error_message = 'auto-reset: stale processing',
                        progress_message = 'Requeued after stale processing heartbeat',
                        performance_json = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        JobItemStatus.PENDING.value,
                        json.dumps(performance, ensure_ascii=False, sort_keys=True),
                        now,
                        item_id,
                    ),
                )
                affected_jobs.add(str(row["job_id"]))
                reset_file_ids.add(str(row["file_id"]))
                to_redispatch.append(
                    {
                        "item_id": item_id,
                        "job_id": str(row["job_id"]),
                        "file_id": str(row["file_id"]),
                        "task": "structured"
                        if row["job_type"] == JobType.STRUCTURED_BATCH.value
                        else "recognition",
                    }
                )
                logger.warning(
                    "repair_stale_processing: item %s stage=%s updated=%s -> pending",
                    item_id,
                    row["progress_stage"],
                    row["progress_updated_at"] or row["updated_at"],
                )

            for job_id in affected_jobs:
                conn.execute(
                    "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ? AND status IN (?, ?, ?)",
                    (
                        JobStatus.QUEUED.value,
                        now,
                        job_id,
                        JobStatus.PROCESSING.value,
                        JobStatus.RUNNING.value,
                        JobStatus.REDACTING.value,
                    ),
                )

            if to_redispatch:
                conn.commit()

        self._clear_outputs_for_file_ids(reset_file_ids)
        return to_redispatch
