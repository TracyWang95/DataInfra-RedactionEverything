"""
批量任务 Job / JobItem 的领域模型层：状态枚举、状态机转换表、
异常、纯序列化辅助与 SQLite schema DDL。

从 job_store.py 抽出，纯定义、无内部依赖，供持久化层与修复例程复用。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any


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
