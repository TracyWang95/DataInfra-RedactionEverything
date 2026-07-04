"""
批量任务 Job / JobItem — SQLite（WAL）持久化。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from enum import Enum
from functools import lru_cache
from typing import Any

from app.core.sqlite_base import connect_sqlite, ensure_db_dir


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


class JobType(str, Enum):
    TEXT_BATCH = "text_batch"
    IMAGE_BATCH = "image_batch"
    SMART_BATCH = "smart_batch"
    STRUCTURED_BATCH = "structured_batch"


class JobStatus(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    PROCESSING = "processing"           # 合并旧 running/redacting
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # 兼容旧数据读取（不做新写入）
    RUNNING = "running"
    REDACTING = "redacting"


class JobItemStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"           # 合并旧 queued/parsing/ner/vision/redacting
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    # 兼容旧数据读取
    QUEUED = "queued"
    PARSING = "parsing"
    NER = "ner"
    VISION = "vision"
    REVIEW_APPROVED = "review_approved"
    REDACTING = "redacting"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# State-machine: 简化版，只有核心转换
# ---------------------------------------------------------------------------

# 新状态 + 旧状态兼容：任何旧中间状态都可转到新状态
_ALL_JOB = tuple(JobStatus)
VALID_JOB_TRANSITIONS: dict[JobStatus, tuple[JobStatus, ...]] = {
    JobStatus.DRAFT:           (JobStatus.QUEUED, JobStatus.PROCESSING, JobStatus.CANCELLED),
    JobStatus.QUEUED:          (JobStatus.PROCESSING, JobStatus.CANCELLED),
    JobStatus.PROCESSING:      (JobStatus.AWAITING_REVIEW, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED),
    JobStatus.AWAITING_REVIEW: (JobStatus.PROCESSING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED),
    JobStatus.COMPLETED:       (JobStatus.QUEUED,),
    JobStatus.FAILED:          (JobStatus.QUEUED, JobStatus.PROCESSING, JobStatus.CANCELLED),
    JobStatus.CANCELLED:       (),
    # 旧状态兼容：可以转到任何新状态
    JobStatus.RUNNING:         _ALL_JOB,
    JobStatus.REDACTING:       _ALL_JOB,
}

_ALL_ITEM = tuple(JobItemStatus)
VALID_ITEM_TRANSITIONS: dict[JobItemStatus, tuple[JobItemStatus, ...]] = {
    JobItemStatus.PENDING:         (JobItemStatus.PROCESSING, JobItemStatus.AWAITING_REVIEW, JobItemStatus.CANCELLED),
    JobItemStatus.PROCESSING:      (JobItemStatus.AWAITING_REVIEW, JobItemStatus.COMPLETED, JobItemStatus.FAILED),
    JobItemStatus.AWAITING_REVIEW: (JobItemStatus.PROCESSING, JobItemStatus.COMPLETED, JobItemStatus.FAILED),
    JobItemStatus.COMPLETED:       (),
    JobItemStatus.FAILED:          (JobItemStatus.PENDING, JobItemStatus.PROCESSING),
    # 旧状态兼容：可以转到任何新状态
    JobItemStatus.QUEUED:           _ALL_ITEM,
    JobItemStatus.PARSING:          _ALL_ITEM,
    JobItemStatus.NER:              _ALL_ITEM,
    JobItemStatus.VISION:           _ALL_ITEM,
    JobItemStatus.REVIEW_APPROVED:  _ALL_ITEM,
    JobItemStatus.REDACTING:        _ALL_ITEM,
    JobItemStatus.CANCELLED:        (),
}

_OUTPUT_STALE_ITEM_STATUSES = frozenset(
    {
        JobItemStatus.PENDING.value,
        JobItemStatus.PROCESSING.value,
        JobItemStatus.AWAITING_REVIEW.value,
        JobItemStatus.FAILED.value,
        JobItemStatus.QUEUED.value,
        JobItemStatus.PARSING.value,
        JobItemStatus.NER.value,
        JobItemStatus.VISION.value,
        JobItemStatus.REVIEW_APPROVED.value,
        JobItemStatus.REDACTING.value,
        JobItemStatus.CANCELLED.value,
    }
)


class InvalidStatusTransition(Exception):
    """Raised when a status transition violates the state machine."""

    def __init__(self, entity: str, entity_id: str, current: str, target: str) -> None:
        self.entity = entity
        self.entity_id = entity_id
        self.current = current
        self.target = target
        super().__init__(
            f"Invalid {entity} status transition: {current} -> {target} (id={entity_id})"
        )


def _coerce_performance(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _deep_merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge_dict(dict(base[key]), value)
        else:
            base[key] = value
    return base


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL CHECK(job_type IN ('text_batch','image_batch','smart_batch','structured_batch')),
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  skip_item_review INTEGER NOT NULL DEFAULT 0,
  config_json TEXT NOT NULL DEFAULT '{}',
  priority INTEGER NOT NULL DEFAULT 0,
  owner_id TEXT NOT NULL DEFAULT 'local_user',
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_items (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  file_id TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  error_message TEXT,
  reviewed_at TEXT,
  reviewer TEXT,
  review_draft_json TEXT,
  review_draft_updated_at TEXT,
  progress_stage TEXT,
  progress_current INTEGER NOT NULL DEFAULT 0,
  progress_total INTEGER NOT NULL DEFAULT 0,
  progress_message TEXT,
  progress_updated_at TEXT,
  performance_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_job_items_job ON job_items(job_id);
CREATE INDEX IF NOT EXISTS idx_job_items_status ON job_items(status);
"""


class JobStore:
    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self._path, timeout=10.0, busy_timeout_ms=5000, wal=True)

    def _init_db(self) -> None:
        ensure_db_dir(self._path)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            # WAL 自动 checkpoint 阈值，防止 WAL 文件无限增长
            conn.execute("PRAGMA wal_autocheckpoint = 1000")
            cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(job_items)").fetchall()}
            if "review_draft_json" not in cols:
                conn.execute("ALTER TABLE job_items ADD COLUMN review_draft_json TEXT")
            if "review_draft_updated_at" not in cols:
                conn.execute("ALTER TABLE job_items ADD COLUMN review_draft_updated_at TEXT")
            if "progress_stage" not in cols:
                conn.execute("ALTER TABLE job_items ADD COLUMN progress_stage TEXT")
            if "progress_current" not in cols:
                conn.execute("ALTER TABLE job_items ADD COLUMN progress_current INTEGER NOT NULL DEFAULT 0")
            if "progress_total" not in cols:
                conn.execute("ALTER TABLE job_items ADD COLUMN progress_total INTEGER NOT NULL DEFAULT 0")
            if "progress_message" not in cols:
                conn.execute("ALTER TABLE job_items ADD COLUMN progress_message TEXT")
            if "progress_updated_at" not in cols:
                conn.execute("ALTER TABLE job_items ADD COLUMN progress_updated_at TEXT")
            if "performance_json" not in cols:
                conn.execute("ALTER TABLE job_items ADD COLUMN performance_json TEXT NOT NULL DEFAULT '{}'")
            job_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            if "priority" not in job_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
            if "owner_id" not in job_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'local_user'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_owner ON jobs(owner_id)")
            # Migrate CHECK constraint to include all current job types.
            try:
                conn.execute(
                    "INSERT INTO jobs (id, job_type, status, created_at, updated_at) "
                    "VALUES ('__test_structured', 'structured_batch', 'draft', '', '')"
                )
                conn.execute("DELETE FROM jobs WHERE id = '__test_structured'")
            except sqlite3.IntegrityError:
                conn.rollback()
                # Rebuild table with updated CHECK constraint.
                # Wrap in IMMEDIATE transaction to prevent data loss on crash.
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute("ALTER TABLE jobs RENAME TO jobs_old")
                    conn.execute("""
                        CREATE TABLE jobs (
                            id TEXT PRIMARY KEY,
                            job_type TEXT NOT NULL CHECK(job_type IN ('text_batch','image_batch','smart_batch','structured_batch')),
                            title TEXT NOT NULL DEFAULT '',
                            status TEXT NOT NULL,
                            skip_item_review INTEGER NOT NULL DEFAULT 0,
                            config_json TEXT NOT NULL DEFAULT '{}',
                            priority INTEGER NOT NULL DEFAULT 0,
                            owner_id TEXT NOT NULL DEFAULT 'local_user',
                            error_message TEXT,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        INSERT INTO jobs (id, job_type, title, status, skip_item_review,
                                         config_json, priority, owner_id, error_message, created_at, updated_at)
                        SELECT id, job_type, title, status, skip_item_review,
                               config_json, COALESCE(priority, 0), COALESCE(owner_id, 'local_user'),
                               error_message, created_at, updated_at
                        FROM jobs_old
                    """)
                    conn.execute("DROP TABLE jobs_old")
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            conn.commit()

    def create_job(
        self,
        *,
        job_type: JobType,
        title: str = "",
        config: dict[str, Any] | None = None,
        skip_item_review: bool = False,
        priority: int = 0,
        owner_id: str = "local_user",
    ) -> str:
        jid = str(uuid.uuid4())
        now = _utc_iso()
        cfg = json.dumps(config or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, job_type, title, status, skip_item_review, config_json, priority, owner_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    jid,
                    job_type.value,
                    title or "",
                    JobStatus.DRAFT.value,
                    1 if skip_item_review else 0,
                    cfg,
                    int(priority),
                    owner_id or "local_user",
                    now,
                    now,
                ),
            )
            conn.commit()
        return jid

    def add_item(self, job_id: str, file_id: str, sort_order: int = 0) -> str:
        iid = str(uuid.uuid4())
        now = _utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO job_items (id, job_id, file_id, sort_order, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (iid, job_id, file_id, int(sort_order), JobItemStatus.PENDING.value, now, now),
            )
            conn.commit()
        return iid

    def _clear_outputs_for_file_ids(self, file_ids: list[str] | set[str]) -> None:
        if not file_ids:
            return
        try:
            from app.services.file_management_service import clear_file_output
        except Exception:
            logging.getLogger(__name__).warning("Unable to import file output cleanup", exc_info=True)
            return
        for file_id in dict.fromkeys(str(fid) for fid in file_ids if fid):
            try:
                clear_file_output(file_id)
            except Exception:
                logging.getLogger(__name__).warning(
                    "Failed to clear stale output for file %s", file_id, exc_info=True
                )

    def submit_job(self, job_id: str) -> None:
        """Submit a job and reset non-terminal items to pending."""
        now = _utc_iso()
        terminal = (JobItemStatus.AWAITING_REVIEW.value, JobItemStatus.COMPLETED.value)
        reset_file_ids: list[str] = []
        with self._connect() as conn:
            cur = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(job_id)
            st = row["status"]
            if st in (JobStatus.COMPLETED.value, JobStatus.CANCELLED.value):
                raise ValueError(f"job not submittable: {st}")
            reset_rows = conn.execute(
                """
                SELECT file_id FROM job_items
                WHERE job_id = ? AND status NOT IN (?, ?)
                """,
                (job_id, *terminal),
            ).fetchall()
            reset_file_ids = [str(r["file_id"]) for r in reset_rows if r["file_id"]]
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (JobStatus.QUEUED.value, now, job_id),
            )
            # Reset all non-terminal items to pending for queue dispatch.
            conn.execute(
                """
                UPDATE job_items
                SET status = ?, error_message = NULL, performance_json = '{}', updated_at = ?
                WHERE job_id = ? AND status NOT IN (?, ?)
                """,
                (JobItemStatus.PENDING.value, now, job_id, *terminal),
            )
            conn.commit()
        self._clear_outputs_for_file_ids(reset_file_ids)

    def cancel_job(self, job_id: str) -> None:
        now = _utc_iso()
        cancelled_file_ids: list[str] = []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT file_id FROM job_items
                WHERE job_id = ? AND status NOT IN (?, ?, ?)
                """,
                (
                    job_id,
                    JobItemStatus.COMPLETED.value,
                    JobItemStatus.FAILED.value,
                    JobItemStatus.CANCELLED.value,
                ),
            ).fetchall()
            cancelled_file_ids = [str(r["file_id"]) for r in rows if r["file_id"]]
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (JobStatus.CANCELLED.value, now, job_id),
            )
            conn.execute(
                """
                UPDATE job_items SET status = ?, error_message = 'cancelled', updated_at = ?
                WHERE job_id = ? AND status NOT IN (?, ?, ?)
                """,
                (
                    JobItemStatus.CANCELLED.value,
                    now,
                    job_id,
                    JobItemStatus.COMPLETED.value,
                    JobItemStatus.FAILED.value,
                    JobItemStatus.CANCELLED.value,
                ),
            )
            conn.commit()
        self._clear_outputs_for_file_ids(cancelled_file_ids)

    def delete_job(self, job_id: str) -> None:
        with self._connect() as conn:
            cur = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(job_id)
            conn.execute("DELETE FROM job_items WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()

    def clear_all_jobs(self) -> int:
        """Delete all jobs and job items in one transaction."""
        with self._connect() as conn:
            count = int(conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"])
            conn.execute("DELETE FROM job_items")
            conn.execute("DELETE FROM jobs")
            conn.commit()
            return count

    def clear_jobs_for_owner(self, owner_id: str) -> int:
        """Delete jobs and job items owned by one authenticated user."""
        with self._connect() as conn:
            count = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM jobs WHERE owner_id = ?",
                    (owner_id,),
                ).fetchone()["c"]
            )
            conn.execute(
                "DELETE FROM job_items WHERE job_id IN (SELECT id FROM jobs WHERE owner_id = ?)",
                (owner_id,),
            )
            conn.execute("DELETE FROM jobs WHERE owner_id = ?", (owner_id,))
            conn.commit()
            return count

    def delete_item(self, item_id: str) -> dict[str, Any] | None:
        """Remove a single item from its job. Returns the deleted row or None."""
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM job_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM job_items WHERE id = ?", (item_id,))
            conn.commit()
            return dict(row)

    def delete_items_for_file(self, file_id: str) -> list[dict[str, Any]]:
        """Remove all job item rows that reference a deleted file."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM job_items WHERE file_id = ?", (file_id,)).fetchall()
            if not rows:
                return []
            deleted = [dict(row) for row in rows]
            affected_job_ids = {str(row["job_id"]) for row in deleted if row.get("job_id")}
            conn.execute("DELETE FROM job_items WHERE file_id = ?", (file_id,))
            now = _utc_iso()
            for job_id in affected_job_ids:
                conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", (now, job_id))
            conn.commit()
            return deleted

    def list_schedulable_jobs(self, limit: int = 5000) -> list[dict[str, Any]]:
        """Return jobs that may still contain schedulable items."""
        lim = max(1, min(50_000, int(limit)))
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status IN (?, ?, ?, ?, ?)
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (
                    JobStatus.QUEUED.value,
                    JobStatus.PROCESSING.value,
                    JobStatus.RUNNING.value,
                    JobStatus.AWAITING_REVIEW.value,
                    JobStatus.REDACTING.value,
                    lim,
                ),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM job_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_items(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM job_items WHERE job_id = ? ORDER BY sort_order ASC, created_at ASC",
                (job_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def list_jobs(
        self,
        *,
        job_type: JobType | None = None,
        status_values: list[str] | None = None,
        owner_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size
        params: list[Any] = []
        clauses: list[str] = []
        if job_type is not None:
            clauses.append("job_type = ?")
            params.append(job_type.value)
        if status_values:
            placeholders = ",".join("?" for _ in status_values)
            clauses.append(f"status IN ({placeholders})")
            params.extend(status_values)
        if owner_id:
            clauses.append("owner_id = ?")
            params.append(owner_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS c FROM jobs {where}", params).fetchone()["c"]
            cur = conn.execute(
                f"SELECT * FROM jobs {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            )
            rows = [dict(r) for r in cur.fetchall()]
        return rows, int(total)

    def job_list_stats(self, *, job_type: JobType | None = None, owner_id: str | None = None) -> dict[str, int]:
        where = ""
        params: list[Any] = []
        if job_type is not None:
            where = "WHERE job_type = ?"
            params.append(job_type.value)
        if owner_id:
            where = f"{where} AND owner_id = ?" if where else "WHERE owner_id = ?"
            params.append(owner_id)

        active_job_statuses = (
            JobStatus.QUEUED.value,
            JobStatus.PROCESSING.value,
            JobStatus.RUNNING.value,
            JobStatus.REDACTING.value,
        )
        review_item_statuses = (
            JobItemStatus.AWAITING_REVIEW.value,
            JobItemStatus.REVIEW_APPROVED.value,
        )
        active_item_statuses = (
            JobItemStatus.PENDING.value,
            JobItemStatus.QUEUED.value,
            JobItemStatus.PROCESSING.value,
            JobItemStatus.PARSING.value,
            JobItemStatus.NER.value,
            JobItemStatus.VISION.value,
            JobItemStatus.REDACTING.value,
        )
        risk_item_statuses = (JobItemStatus.FAILED.value, JobItemStatus.CANCELLED.value)

        with self._connect() as conn:
            job_row = conn.execute(
                f"""
                SELECT
                  COUNT(*) AS total_jobs,
                  SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS draft_jobs,
                  SUM(CASE WHEN status IN ({','.join('?' for _ in active_job_statuses)}) THEN 1 ELSE 0 END) AS active_jobs,
                  SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS awaiting_review_jobs,
                  SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS completed_jobs,
                  SUM(CASE WHEN status IN (?, ?) THEN 1 ELSE 0 END) AS risk_jobs
                FROM jobs
                {where}
                """,
                [
                    JobStatus.DRAFT.value,
                    *active_job_statuses,
                    JobStatus.AWAITING_REVIEW.value,
                    JobStatus.COMPLETED.value,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELLED.value,
                    *params,
                ],
            ).fetchone()

            item_clauses: list[str] = []
            item_params: list[Any] = []
            if job_type is not None:
                item_clauses.append("j.job_type = ?")
                item_params.append(job_type.value)
            if owner_id:
                item_clauses.append("j.owner_id = ?")
                item_params.append(owner_id)
            item_where = f"WHERE {' AND '.join(item_clauses)}" if item_clauses else ""
            item_row = conn.execute(
                f"""
                SELECT
                  COUNT(ji.id) AS total_items,
                  SUM(CASE WHEN ji.status IN ({','.join('?' for _ in active_item_statuses)}) THEN 1 ELSE 0 END) AS active_items,
                  SUM(CASE WHEN ji.status IN ({','.join('?' for _ in review_item_statuses)}) THEN 1 ELSE 0 END) AS awaiting_review_items,
                  SUM(CASE WHEN ji.status = ? THEN 1 ELSE 0 END) AS completed_items,
                  SUM(CASE WHEN ji.status IN ({','.join('?' for _ in risk_item_statuses)}) THEN 1 ELSE 0 END) AS risk_items
                FROM job_items ji
                JOIN jobs j ON j.id = ji.job_id
                {item_where}
                """,
                [
                    *active_item_statuses,
                    *review_item_statuses,
                    JobItemStatus.COMPLETED.value,
                    *risk_item_statuses,
                    *item_params,
                ],
            ).fetchone()

        def n(row: sqlite3.Row, key: str) -> int:
            return int(row[key] or 0)

        return {
            "total_jobs": n(job_row, "total_jobs"),
            "draft_jobs": n(job_row, "draft_jobs"),
            "active_jobs": n(job_row, "active_jobs"),
            "awaiting_review_jobs": n(job_row, "awaiting_review_jobs"),
            "completed_jobs": n(job_row, "completed_jobs"),
            "risk_jobs": n(job_row, "risk_jobs"),
            "total_items": n(item_row, "total_items"),
            "active_items": n(item_row, "active_items"),
            "awaiting_review_items": n(item_row, "awaiting_review_items"),
            "completed_items": n(item_row, "completed_items"),
            "risk_items": n(item_row, "risk_items"),
        }

    def update_item_status(
        self,
        item_id: str,
        status: JobItemStatus,
        error_message: str | None = None,
    ) -> None:
        now = _utc_iso()
        file_id_to_clean: str | None = None
        already_in_target = False
        with self._connect() as conn:
            cur = conn.execute("SELECT status, file_id FROM job_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(item_id)
            current = JobItemStatus(row["status"])
            if current == status:
                if status.value in _OUTPUT_STALE_ITEM_STATUSES:
                    file_id_to_clean = str(row["file_id"])
                already_in_target = True
            elif status not in VALID_ITEM_TRANSITIONS.get(current, ()):
                raise InvalidStatusTransition("job_item", item_id, current.value, status.value)
            elif status.value in _OUTPUT_STALE_ITEM_STATUSES:
                file_id_to_clean = str(row["file_id"])
            if not already_in_target:
                conn.execute(
                    """
                    UPDATE job_items SET status = ?, error_message = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status.value, error_message, now, item_id),
                )
                conn.commit()
        if file_id_to_clean:
            self._clear_outputs_for_file_ids([file_id_to_clean])

    def update_job_status(self, job_id: str, status: JobStatus, error_message: str | None = None) -> None:
        now = _utc_iso()
        with self._connect() as conn:
            cur = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(job_id)
            current = JobStatus(row["status"])
            if current == status:
                return  # idempotent: already in target state
            if status not in VALID_JOB_TRANSITIONS.get(current, ()):
                raise InvalidStatusTransition("job", job_id, current.value, status.value)
            conn.execute(
                "UPDATE jobs SET status = ?, error_message = ?, updated_at = ? WHERE id = ?",
                (status.value, error_message, now, job_id),
            )
            conn.commit()

    def update_item_progress(
        self,
        item_id: str,
        *,
        stage: str,
        current: int = 0,
        total: int = 0,
        message: str | None = None,
    ) -> None:
        """Update best-effort recognition progress for long-running item work."""
        now = _utc_iso()
        current = max(0, int(current or 0))
        total = max(0, int(total or 0))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE job_items
                SET progress_stage = ?, progress_current = ?, progress_total = ?,
                    progress_message = ?, progress_updated_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (stage, current, total, message, now, now, item_id),
            )
            conn.commit()

    def update_item_performance(self, item_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Merge best-effort timing/cache diagnostics into a job item."""
        if not isinstance(patch, dict) or not patch:
            return self.get_item_performance(item_id)
        now = _utc_iso()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT performance_json FROM job_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if not row:
                raise KeyError(item_id)
            data = _deep_merge_dict(_coerce_performance(row["performance_json"]), patch)
            conn.execute(
                """
                UPDATE job_items
                SET performance_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(data, ensure_ascii=False, sort_keys=True), now, item_id),
            )
            conn.commit()
        return data

    def get_item_performance(self, item_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT performance_json FROM job_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if not row:
                raise KeyError(item_id)
            return _coerce_performance(row["performance_json"])

    def get_item_performance_map(self, job_id: str) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, performance_json FROM job_items WHERE job_id = ?",
                (job_id,),
            ).fetchall()
        return {str(row["id"]): _coerce_performance(row["performance_json"]) for row in rows}

    def approve_item_review(self, item_id: str, reviewer: str = "local") -> None:
        """Approve an item review if it is awaiting review."""
        now = _utc_iso()
        file_id_to_clean: str | None = None
        already_approved = False
        with self._connect() as conn:
            cur = conn.execute("SELECT status, file_id FROM job_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(item_id)
            st = row["status"]
            if st in (JobItemStatus.REVIEW_APPROVED.value, JobItemStatus.COMPLETED.value):
                if st == JobItemStatus.REVIEW_APPROVED.value:
                    file_id_to_clean = str(row["file_id"])
                already_approved = True
            elif st != JobItemStatus.AWAITING_REVIEW.value:
                raise ValueError(f"item not awaiting review: {st}")
            else:
                file_id_to_clean = str(row["file_id"])
            if not already_approved:
                conn.execute(
                    """
                    UPDATE job_items
                    SET status = ?, reviewed_at = ?, reviewer = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (JobItemStatus.REVIEW_APPROVED.value, now, reviewer, now, item_id),
                )
                conn.commit()
        if file_id_to_clean:
            self._clear_outputs_for_file_ids([file_id_to_clean])

    def reject_item_review(self, item_id: str, reviewer: str = "local") -> None:
        """Reject an item review and send it back to processing."""
        now = _utc_iso()
        file_id_to_clean: str | None = None
        with self._connect() as conn:
            cur = conn.execute("SELECT status, file_id FROM job_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(item_id)
            if row["status"] != JobItemStatus.AWAITING_REVIEW.value:
                raise ValueError("item not awaiting review")
            file_id_to_clean = str(row["file_id"])
            conn.execute(
                """
                UPDATE job_items
                SET status = ?, error_message = NULL, reviewed_at = ?, reviewer = ?, review_draft_json = NULL,
                    review_draft_updated_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (JobItemStatus.QUEUED.value, now, reviewer, now, item_id),
            )
            conn.commit()
        if file_id_to_clean:
            self._clear_outputs_for_file_ids([file_id_to_clean])

    def approve_items_review_bulk(
        self, item_ids: list[str], reviewer: str = "local"
    ) -> list[tuple[str, str]]:
        """Bulk-approve awaiting_review items in ONE transaction.

        万级批量确认的性能路径：逐条 approve_item_review 是每条一个事务 +
        每条一次全表 job 状态刷新，6000+ 条会拖到分钟级。这里单事务批量
        UPDATE（带 status 守卫，并发重复调用天然幂等），返回真正被批准的
        [(item_id, file_id)]。
        """
        if not item_ids:
            return []
        now = _utc_iso()
        approved: list[tuple[str, str]] = []
        with self._connect() as conn:
            for start in range(0, len(item_ids), 500):
                batch = [str(i) for i in item_ids[start : start + 500]]
                placeholders = ",".join("?" * len(batch))
                rows = conn.execute(
                    f"SELECT id, file_id FROM job_items WHERE id IN ({placeholders}) AND status = ?",
                    (*batch, JobItemStatus.AWAITING_REVIEW.value),
                ).fetchall()
                ids = [row["id"] for row in rows]
                if not ids:
                    continue
                update_placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"""
                    UPDATE job_items
                    SET status = ?, reviewed_at = ?, reviewer = ?, updated_at = ?
                    WHERE id IN ({update_placeholders})
                    """,
                    (JobItemStatus.REVIEW_APPROVED.value, now, reviewer, now, *ids),
                )
                approved.extend((row["id"], str(row["file_id"])) for row in rows)
            conn.commit()
        if approved:
            self._clear_outputs_for_file_ids([file_id for _, file_id in approved])
        return approved

    def list_item_review_drafts(self, job_id: str) -> dict[str, tuple[str, dict[str, Any]]]:
        """Return {item_id: (file_id, draft)} for items that have a saved draft."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, file_id, review_draft_json FROM job_items "
                "WHERE job_id = ? AND review_draft_json IS NOT NULL AND review_draft_json != ''",
                (job_id,),
            ).fetchall()
        drafts: dict[str, tuple[str, dict[str, Any]]] = {}
        for row in rows:
            try:
                draft = json.loads(row["review_draft_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(draft, dict):
                drafts[row["id"]] = (str(row["file_id"]), draft)
        return drafts

    def get_item_review_draft(self, item_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT review_draft_json, review_draft_updated_at FROM job_items WHERE id = ?",
                (item_id,),
            )
            row = cur.fetchone()
            if not row:
                raise KeyError(item_id)
            raw = row["review_draft_json"]
            if not raw:
                return None
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return None
            if not isinstance(data, dict):
                return None
            data["updated_at"] = row["review_draft_updated_at"]
            return data

    def save_item_review_draft(self, item_id: str, draft: dict[str, Any]) -> None:
        now = _utc_iso()
        payload = json.dumps(draft, ensure_ascii=False)
        with self._connect() as conn:
            cur = conn.execute("SELECT id FROM job_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(item_id)
            conn.execute(
                """
                UPDATE job_items
                SET review_draft_json = ?, review_draft_updated_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (payload, now, now, item_id),
            )
            conn.commit()

    def clear_item_review_draft(self, item_id: str) -> None:
        now = _utc_iso()
        with self._connect() as conn:
            cur = conn.execute("SELECT id FROM job_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(item_id)
            conn.execute(
                """
                UPDATE job_items
                SET review_draft_json = NULL, review_draft_updated_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (now, item_id),
            )
            conn.commit()

    def mark_item_redacting(self, item_id: str) -> None:
        self.update_item_status(item_id, JobItemStatus.PROCESSING)

    def complete_item_review(self, item_id: str, reviewer: str = "local") -> None:
        self.update_item_status(item_id, JobItemStatus.COMPLETED)
        now = _utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE job_items
                SET error_message = NULL, reviewed_at = ?, reviewer = ?, review_draft_json = NULL,
                    review_draft_updated_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (now, reviewer, now, item_id),
            )
            conn.commit()

    def find_item_status_by_file_id(self, file_id: str) -> str | None:
        """Return the latest job item status for a file."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM job_items WHERE file_id = ? ORDER BY updated_at DESC LIMIT 1",
                (file_id,),
            ).fetchone()
            return row["status"] if row else None

    def batch_find_item_statuses(self, file_ids: list[str]) -> dict[str, dict[str, str]]:
        """Batch lookup latest job item status and item id by file id."""
        if not file_ids:
            return {}
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in file_ids)
            rows = conn.execute(
                f"SELECT id, file_id, status FROM job_items WHERE file_id IN ({placeholders}) ORDER BY updated_at DESC",
                file_ids,
            ).fetchall()
            result: dict[str, dict[str, str]] = {}
            for row in rows:
                fid = row["file_id"]
                if fid not in result:
                    result[fid] = {"status": row["status"], "item_id": row["id"]}
            return result

    def list_referenced_file_ids(self) -> set[str]:
        """Return all file IDs still referenced by batch job items."""
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT file_id FROM job_items").fetchall()
        return {str(row["file_id"]) for row in rows if row["file_id"]}

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

    def touch_job_updated(self, job_id: str) -> None:
        now = _utc_iso()
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", (now, job_id))
            conn.commit()

    def update_job_draft(self, job_id: str, patch: dict[str, Any]) -> bool:
        """Update draft fields: title, config, skip_item_review, priority."""
        job = self.get_job(job_id)
        if not job or job["status"] != JobStatus.DRAFT.value:
            return False
        now = _utc_iso()
        sets: list[str] = []
        params: list[Any] = []
        if "title" in patch:
            sets.append("title = ?")
            params.append(patch["title"])
        if "config" in patch:
            sets.append("config_json = ?")
            params.append(json.dumps(patch["config"], ensure_ascii=False))
        if "skip_item_review" in patch:
            sets.append("skip_item_review = ?")
            params.append(1 if patch["skip_item_review"] else 0)
        if "priority" in patch:
            sets.append("priority = ?")
            params.append(int(patch["priority"]))
        if not sets:
            return False
        sets.append("updated_at = ?")
        params.append(now)
        params.append(job_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", params)
            conn.commit()
        return True


# --- Singleton accessor ------------------------------------------------------
@lru_cache
def _singleton_store() -> JobStore:
    from app.core.config import settings
    return JobStore(settings.JOB_DB_PATH)


def get_job_store() -> JobStore:
    """Return the application-wide JobStore singleton."""
    return _singleton_store()
