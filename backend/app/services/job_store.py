"""
批量任务 Job / JobItem — SQLite（WAL）持久化。
"""
from __future__ import annotations

import logging
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
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
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        # 性能优化 pragmas
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self) -> None:
        import os

        d = os.path.dirname(self._path)
        if d:
            os.makedirs(d, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            # WAL 自动 checkpoint 阈值，防止 WAL 文件无限增长
            conn.execute("PRAGMA wal_autocheckpoint = 1000")
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
                # Rebuild table with updated CHECK constraint.
                # Wrap in IMMEDIATE transaction to prevent data loss on crash.
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute("ALTER TABLE jobs RENAME TO jobs_old")
                    conn.execute("""
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
                        )
                    """)
                    conn.execute("""
                        INSERT INTO jobs (id, job_type, title, status, skip_item_review,
                                         config_json, priority, error_message, created_at, updated_at)
                        SELECT id, job_type, title, status, skip_item_review,
                               config_json, COALESCE(priority, 0), error_message, created_at, updated_at
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
        """提交任务：将非终态 item 重置为 PENDING，等待队列消费。"""
        now = _utc_iso()
        terminal = (JobItemStatus.AWAITING_REVIEW.value, JobItemStatus.COMPLETED.value)
        with self._connect() as conn:
            cur = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError(job_id)
            st = row["status"]
            if st in (JobStatus.COMPLETED.value, JobStatus.CANCELLED.value):
                raise ValueError(f"job not submittable: {st}")
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (JobStatus.QUEUED.value, now, job_id),
            )
            # 将所有非终态 item 重置为 PENDING
            conn.execute(
                f"""
                UPDATE job_items SET status = ?, error_message = NULL, updated_at = ?
                WHERE job_id = ? AND status NOT IN (?, ?)
                """,
                (JobItemStatus.PENDING.value, now, job_id, *terminal),
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
        """供 Worker 扫描：包含所有可能有未完成 item 的 job 状态。"""
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

    def find_item_status_by_file_id(self, file_id: str) -> Optional[str]:
        """查找文件关联的最新 job_item 状态，用于三态匿名化显示。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM job_items WHERE file_id = ? ORDER BY updated_at DESC LIMIT 1",
                (file_id,),
            ).fetchone()
            return row["status"] if row else None

    def batch_find_item_statuses(self, file_ids: list[str]) -> dict[str, dict[str, str]]:
        """批量查找文件关联的最新 job_item 状态和 item_id。"""
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

    def repair_completed_without_output(self) -> int:
        """修复脏数据：status=completed 但文件没有 output_path 的 item 重置为 awaiting_review。"""
        from app.services.file_management_service import get_file_store
        file_store = get_file_store()
        repaired = 0
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, file_id, job_id FROM job_items WHERE status = ?",
                (JobItemStatus.COMPLETED.value,),
            ).fetchall()
            for row in rows:
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
                # 受影响的 job 需要强制回退状态（state machine 不允许 COMPLETED→AWAITING_REVIEW）
                affected_jobs = set(row["job_id"] for row in rows if not (file_store.get(row["file_id"]) or {}).get("output_path"))
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
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, file_id, job_id, error_message FROM job_items WHERE status = ?",
                (JobItemStatus.FAILED.value,),
            ).fetchall()
            for row in rows:
                err = str(row["error_message"] or "")
                err_lower = err.lower()
                if "文件不存在" not in err and "file not found" not in err_lower:
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
                repaired += 1

            for job_id in affected_jobs:
                conn.execute(
                    "UPDATE jobs SET status = ?, error_message = NULL, updated_at = ? WHERE id = ?",
                    (JobStatus.QUEUED.value, _utc_iso(), job_id),
                )

            if repaired:
                conn.commit()

        return repaired

    def repair_stuck_in_flight_items(self) -> list[dict]:
        """
        崩溃恢复：将上次进程异常退出时卡在中间识别状态的 item 重置，
        并返回需要重新投递到任务队列的 item 信息列表。

        - PARSING / NER / VISION  → QUEUED  （重新识别）
        - REDACTING               → AWAITING_REVIEW  （交还人工复核，避免重复覆盖输出）
        直接操作 SQL，绕过状态机，与已有 repair_* 方法保持一致。
        """
        logger = logging.getLogger(__name__)
        to_redispatch: list[dict] = []
        stuck_recognition = [
            JobItemStatus.PARSING.value,
            JobItemStatus.NER.value,
            JobItemStatus.VISION.value,
        ]
        now = _utc_iso()

        with self._connect() as conn:
            # 1. PARSING / NER / VISION → QUEUED
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
                to_redispatch.append({
                    "item_id": row["id"],
                    "job_id": row["job_id"],
                    "file_id": row["file_id"],
                    "task": "process_item",
                })
                logger.info(
                    "repair_stuck: item %s (status=%s) → queued, job=%s",
                    row["id"], row["status"], row["job_id"],
                )

            # 2. REDACTING → AWAITING_REVIEW
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
                logger.info(
                    "repair_stuck: item %s (REDACTING) → awaiting_review, job=%s",
                    row["id"], row["job_id"],
                )

            # 3. 受影响的 Job：若已 COMPLETED/FAILED 则拉回 QUEUED/AWAITING_REVIEW
            for job_id in affected_jobs:
                conn.execute(
                    "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ? AND status IN (?, ?)",
                    (JobStatus.QUEUED.value, now, job_id,
                     JobStatus.COMPLETED.value, JobStatus.FAILED.value),
                )

            if to_redispatch or redacting_rows:
                conn.commit()

        return to_redispatch

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


# ─── Singleton accessor ────────────────────────────────────
@lru_cache
def _singleton_store() -> JobStore:
    from app.core.config import settings
    return JobStore(settings.JOB_DB_PATH)


def get_job_store() -> JobStore:
    """Return the application-wide JobStore singleton."""
    return _singleton_store()
