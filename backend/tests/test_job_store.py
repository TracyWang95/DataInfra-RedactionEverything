"""Job / JobItem SQLite 存储与审阅闸门（TDD）。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.services.job_store import (
    JobItemStatus,
    JobStatus,
    JobStore,
    JobType,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "jobs.sqlite3"


@pytest.fixture
def store(db_path: Path) -> JobStore:
    return JobStore(str(db_path))


def test_init_enables_wal_and_tables(store: JobStore, db_path: Path) -> None:
    assert db_path.exists()
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row is not None
        assert str(row[0]).upper() == "WAL"
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "jobs" in tables
        assert "job_items" in tables
        cols = {r[1] for r in conn.execute("PRAGMA table_info(job_items)")}
        assert "review_draft_json" in cols
        assert "review_draft_updated_at" in cols


def test_create_job_draft_and_add_items(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="批1", config={"entity_type_ids": ["PERSON"]})
    store.add_item(jid, file_id="f-aaa", sort_order=0)
    store.add_item(jid, file_id="f-bbb", sort_order=1)
    job = store.get_job(jid)
    assert job is not None
    assert job["job_type"] == "text_batch"
    assert job["status"] == JobStatus.DRAFT.value
    items = store.list_items(jid)
    assert len(items) == 2
    assert items[0]["file_id"] == "f-aaa"
    assert items[0]["status"] == JobItemStatus.PENDING.value


def test_submit_moves_job_and_items_to_queued(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.IMAGE_BATCH, title="图批")
    store.add_item(jid, file_id="img1", sort_order=0)
    store.submit_job(jid)
    assert store.get_job(jid)["status"] == JobStatus.QUEUED.value
    assert all(i["status"] == JobItemStatus.QUEUED.value for i in store.list_items(jid))


def test_item_transition_to_awaiting_review(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t")
    iid = store.add_item(jid, file_id="f1", sort_order=0)
    store.submit_job(jid)
    store.update_item_status(iid, JobItemStatus.PARSING)
    store.update_item_status(iid, JobItemStatus.NER)
    store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
    row = store.get_item(iid)
    assert row["status"] == JobItemStatus.AWAITING_REVIEW.value


def test_approve_idempotent_and_sets_review_approved(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t")
    iid = store.add_item(jid, file_id="f1", sort_order=0)
    store.update_item_status(iid, JobItemStatus.QUEUED)
    store.update_item_status(iid, JobItemStatus.PARSING)
    store.update_item_status(iid, JobItemStatus.NER)
    store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
    store.approve_item_review(iid, reviewer="local")
    store.approve_item_review(iid, reviewer="local")
    row = store.get_item(iid)
    assert row["status"] == JobItemStatus.REVIEW_APPROVED.value
    assert row["reviewed_at"]


def test_list_jobs_filter_by_job_type(store: JobStore) -> None:
    store.create_job(job_type=JobType.TEXT_BATCH, title="a")
    store.create_job(job_type=JobType.IMAGE_BATCH, title="b")
    text_jobs, ttotal = store.list_jobs(job_type=JobType.TEXT_BATCH, page=1, page_size=20)
    assert ttotal == 1
    assert text_jobs[0]["title"] == "a"
    all_jobs, atotal = store.list_jobs(job_type=None, page=1, page_size=20)
    assert atotal == 2


def test_config_json_roundtrip(store: JobStore) -> None:
    cfg = {"entity_type_ids": ["X"], "replacement_mode": "structured"}
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="c", config=cfg)
    job = store.get_job(jid)
    assert json.loads(job["config_json"]) == cfg


def test_cancel_job(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="x")
    store.add_item(jid, file_id="f", sort_order=0)
    store.submit_job(jid)
    store.cancel_job(jid)
    assert store.get_job(jid)["status"] == JobStatus.CANCELLED.value
    assert store.list_items(jid)[0]["status"] == JobItemStatus.CANCELLED.value


def test_delete_job_removes_job_and_items(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="delete me")
    iid = store.add_item(jid, file_id="f1", sort_order=0)
    assert store.get_job(jid) is not None
    assert store.get_item(iid) is not None

    store.delete_job(jid)

    assert store.get_job(jid) is None
    assert store.list_items(jid) == []
    assert store.get_item(iid) is None


def test_review_draft_roundtrip(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="draft")
    iid = store.add_item(jid, file_id="f1", sort_order=0)
    store.update_item_status(iid, JobItemStatus.QUEUED)
    store.update_item_status(iid, JobItemStatus.PARSING)
    store.update_item_status(iid, JobItemStatus.NER)
    store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
    store.save_item_review_draft(
        iid,
        {
            "entities": [{"id": "e1", "text": "Alice", "type": "PERSON", "start": 0, "end": 5, "selected": True}],
            "bounding_boxes": [],
        },
    )
    draft = store.get_item_review_draft(iid)
    assert draft is not None
    assert draft["entities"][0]["text"] == "Alice"
    assert draft["updated_at"]
    store.clear_item_review_draft(iid)
    assert store.get_item_review_draft(iid) is None


def test_reject_clears_review_draft(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="reject")
    iid = store.add_item(jid, file_id="f1", sort_order=0)
    store.update_item_status(iid, JobItemStatus.QUEUED)
    store.update_item_status(iid, JobItemStatus.PARSING)
    store.update_item_status(iid, JobItemStatus.NER)
    store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
    store.save_item_review_draft(iid, {"entities": [{"id": "e1"}], "bounding_boxes": []})
    store.reject_item_review(iid)
    row = store.get_item(iid)
    assert row["status"] == JobItemStatus.QUEUED.value
    assert row["review_draft_json"] is None
    assert row["review_draft_updated_at"] is None
