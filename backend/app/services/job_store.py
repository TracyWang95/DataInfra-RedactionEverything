"""
批量任务 Job / JobItem — SQLite（WAL）持久化。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobType(str, Enum):
    TEXT_BATCH = "text_batch"
    IMAGE_BATCH = "image_batch"
    SMART_BATCH = "smart_batch"


class JobStatus(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    REDACTING = "redacting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobItemStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PARSING = "parsing"
    NER = "ner"
    VISION = "vision"
    AWAITING_REVIEW = "awaiting_review"
    REVIEW_APPROVED = "review_approved"
    REDACTING = "redacting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# State-machine: allowed status transitions
# ---------------------------------------------------------------------------

VALID_JOB_TRANSITIONS: dict[JobStatus, tuple[JobStatus, ...]] = {
    JobStatus.DRAFT: (JobStatus.QUEUED, JobStatus.CANCELLED),
    JobStatus.QUEUED: (JobStatus.RUNNING, JobStatus.CANCELLED),
    JobStatus.RUNNING: (JobStatus.AWAITING_REVIEW, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED),
    JobStatus.AWAITING_REVIEW: (JobStatus.REDACTING, JobStatus.CANCELLED),
    JobStatus.REDACTING: (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED),
    JobStatus.COMPLETED: (),  # terminal
    JobStatus.FAILED: (JobStatus.QUEUED, JobStatus.CANCELLED),  # retry allowed
    JobStatus.CANCELLED: (),  # terminal
}

VALID_ITEM_TRANSITIONS: dict[JobItemStatus, tuple[JobItemStatus, ...]] = {
    JobItemStatus.PENDING: (JobItemStatus.QUEUED, JobItemStatus.CANCELLED),
    JobItemStatus.QUEUED: (JobItemStatus.PARSING, JobItemStatus.CANCELLED),
    JobItemStatus.PARSING: (JobItemStatus.NER, JobItemStatus.FAILED, JobItemStatus.CANCELLED),
    JobItemStatus.NER: (JobItemStatus.VISION, JobItemStatus.AWAITING_REVIEW, JobItemStatus.REVIEW_APPROVED, JobItemStatus.FAILED, JobItemStatus.CANCELLED),
    JobItemStatus.VISION: (JobItemStatus.AWAITING_REVIEW, JobItemStatus.REVIEW_APPROVED, JobItemStatus.FAILED, JobItemStatus.CANCELLED),
    JobItemStatus.AWAITING_REVIEW: (JobItemStatus.REVIEW_APPROVED, JobItemStatus.CANCELLED),
    JobItemStatus.REVIEW_APPROVED: (JobItemStatus.REDACTING, JobItemStatus.CANCELLED),
    JobItemStatus.REDACTING: (JobItemStatus.COMPLETED, JobItemStatus.FAILED, JobItemStatus.CANCELLED),
    JobItemStatus.COMPLETED: (),  # terminal
    JobItemStatus.FAILED: (),  # terminal
    JobItemStatus.CANCELLED: (),  # terminal
}


class InvalidStatusTransition(Exception):
    """Raised when a status transition violates the state machine."""

    def __init__(self, entity: str, entity_id: str, current: str, target: str) -> None:
        self.entity = entity
        self.entity_id = entity_id
        self.current = current
        self.target = target
        super().__init__(
            f"Invalid {entity} status transition: {current} → {target} (id={entity_id})"
        )


_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL CHECK(job_type IN ('text_batch','image_batch','smart_batch')),
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  skip_item_review INTEGER NOT NULL DEFAULT 0,
  config_json TEXT NOT NULL DEFAULT '{}',
  priority INTEGER NOT NULL DEFAULT 0,
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
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_items_job ON job_items(job_id);
CREATE INDEX IF NOT EXISTS idx_job_items_status ON job_items(status);
"""


class JobStore:
    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        import os

        d = os.path.dirname(self._path)
        if d:
            os.makedirs(d, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(job_items)").fetchall()}
            if "review_draft_json" not in cols:
                conn.execute("ALTER TABLE job_items ADD COLUMN review_draft_json TEXT")
            if "review_draft_updated_at" not in cols:
                conn.execute("ALTER TABLE job_items ADD COLUMN review_draft_updated_at TEXT")
            job_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            if "priority" not in job_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
            # Migrate CHECK constraint to include smart_batch
            try:
                conn.execute(
                    "INSERT INTO jobs (id, job_type, status, created_at, updated_at) "
                    "VALUES ('__test_smart', 'smart_batch', 'draft', '', '')"
                )
                conn.execute("DELETE FROM jobs WHERE id = '__test_smart'")
            except sqlite3.IntegrityError:
                conn.executescript("""
                    ALTER TABLE jobs RENAME TO jobs_old;
                    CREATE TABLE jobs (
                        id TEXT PRIMARY KEY,
                        job_type TEXT NOT NULL CHECK(job_type IN ('text_batch','image_batch','smart_batch')),
                        title TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL,
                        skip_item_review INTEGER NOT NULL DEFAULT 0,
                        config_json TEXT NOT NULL DEFAULT '{}',
                        priority INTEGER NOT NULL DEFAULT 0,
                        error_message TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO jobs SELECT * FROM jobs_old;
                    DROP TABLE jobs_old;
                """)
            conn.commit()

    def create_job(
        self,
        *,
        job_type: JobType,
        title: str = "",
        config: Optional[dict[str, Any]] = None,
        skip_item_review: bool = False,
        priority: int = 0,
    ) -> str:
        jid = str(uuid.uuid4())
        now = _utc_iso()
        cfg = json.dumps(config or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, job_type, title, status, skip_item_review, config_json, priority, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    jid,
                    job_type.value,
                    title or "",
                    JobStatus.DRAFT.value,
                    1 if skip_item_review else 0,
                    cfg,
                    int(priority),
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

    def submit_job(self, job_id: str) -> None:
        now = _utc_iso()
        with self._connect() as conn:
            cur = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(job_id)
            if row["status"] not in (JobStatus.DRAFT.value, JobStatus.QUEUED.value):
                raise ValueError(f"job not submittable: {row['status']}")
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (JobStatus.QUEUED.value, now, job_id),
            )
            conn.execute(
                """
                UPDATE job_items SET status = ?, updated_at = ?
                WHERE job_id = ? AND status IN (?, ?)
                """,
                (JobItemStatus.QUEUED.value, now, job_id, JobItemStatus.PENDING.value, JobItemStatus.QUEUED.value),
            )
            conn.commit()

    def cancel_job(self, job_id: str) -> None:
        now = _utc_iso()
        with self._connect() as conn:
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

    def delete_job(self, job_id: str) -> None:
        with self._connect() as conn:
            cur = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(job_id)
            conn.execute("DELETE FROM job_items WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()

    def list_schedulable_jobs(self, limit: int = 5000) -> list[dict[str, Any]]:
        """供 Worker 扫描：不限于分页列表，避免仅处理「最近 N 条」任务。"""
        lim = max(1, min(50_000, int(limit)))
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status IN (?, ?, ?, ?)
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.AWAITING_REVIEW.value,
                    JobStatus.REDACTING.value,
                    lim,
                ),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_item(self, item_id: str) -> Optional[dict[str, Any]]:
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
        job_type: Optional[JobType] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size
        where = ""
        params: list[Any] = []
        if job_type is not None:
            where = "WHERE job_type = ?"
            params.append(job_type.value)
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS c FROM jobs {where}", params).fetchone()["c"]
            cur = conn.execute(
                f"SELECT * FROM jobs {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            )
            rows = [dict(r) for r in cur.fetchall()]
        return rows, int(total)

    def update_item_status(
        self,
        item_id: str,
        status: JobItemStatus,
        error_message: Optional[str] = None,
    ) -> None:
        now = _utc_iso()
        with self._connect() as conn:
            cur = conn.execute("SELECT status FROM job_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(item_id)
            current = JobItemStatus(row["status"])
            if current == status:
                return  # idempotent: already in target state
            if status not in VALID_ITEM_TRANSITIONS.get(current, ()):
                raise InvalidStatusTransition("job_item", item_id, current.value, status.value)
            conn.execute(
                """
                UPDATE job_items SET status = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, error_message, now, item_id),
            )
            conn.commit()

    def update_job_status(self, job_id: str, status: JobStatus, error_message: Optional[str] = None) -> None:
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

    def approve_item_review(self, item_id: str, reviewer: str = "local") -> None:
        """幂等：已为 review_approved / completed 则不变。"""
        now = _utc_iso()
        with self._connect() as conn:
            cur = conn.execute("SELECT status FROM job_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(item_id)
            st = row["status"]
            if st in (JobItemStatus.REVIEW_APPROVED.value, JobItemStatus.COMPLETED.value):
                return
            if st != JobItemStatus.AWAITING_REVIEW.value:
                raise ValueError(f"item not awaiting review: {st}")
            conn.execute(
                """
                UPDATE job_items
                SET status = ?, reviewed_at = ?, reviewer = ?, updated_at = ?
                WHERE id = ?
                """,
                (JobItemStatus.REVIEW_APPROVED.value, now, reviewer, now, item_id),
            )
            conn.commit()

    def reject_item_review(self, item_id: str, reviewer: str = "local") -> None:
        """打回重跑识别：回到 queued。"""
        now = _utc_iso()
        with self._connect() as conn:
            cur = conn.execute("SELECT status FROM job_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(item_id)
            if row["status"] != JobItemStatus.AWAITING_REVIEW.value:
                raise ValueError("item not awaiting review")
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

    def get_item_review_draft(self, item_id: str) -> Optional[dict[str, Any]]:
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
        now = _utc_iso()
        with self._connect() as conn:
            cur = conn.execute("SELECT id FROM job_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(item_id)
            conn.execute(
                """
                UPDATE job_items SET status = ?, error_message = NULL, updated_at = ?
                WHERE id = ?
                """,
                (JobItemStatus.REDACTING.value, now, item_id),
            )
            conn.commit()

    def complete_item_review(self, item_id: str, reviewer: str = "local") -> None:
        now = _utc_iso()
        with self._connect() as conn:
            cur = conn.execute("SELECT id FROM job_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(item_id)
            conn.execute(
                """
                UPDATE job_items
                SET status = ?, error_message = NULL, reviewed_at = ?, reviewer = ?, review_draft_json = NULL,
                    review_draft_updated_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (JobItemStatus.COMPLETED.value, now, reviewer, now, item_id),
            )
            conn.commit()

    def touch_job_updated(self, job_id: str) -> None:
        now = _utc_iso()
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", (now, job_id))
            conn.commit()

    def update_job_draft(self, job_id: str, patch: dict[str, Any]) -> bool:
        """仅 draft；patch 键：title、config、skip_item_review、priority。"""
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
