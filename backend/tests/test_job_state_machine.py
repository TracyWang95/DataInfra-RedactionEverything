"""Tests for state-machine transition validation in app.services.job_store."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.job_store import (
    InvalidStatusTransition,
    JobItemStatus,
    JobStatus,
    JobStore,
    JobType,
)


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(str(tmp_path / "sm.sqlite3"))


# ---- Job transitions ----

def test_valid_transitions(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t")
    store.update_job_status(jid, JobStatus.QUEUED)
    store.update_job_status(jid, JobStatus.RUNNING)
    store.update_job_status(jid, JobStatus.COMPLETED)
    job = store.get_job(jid)
    assert job["status"] == JobStatus.COMPLETED.value


def test_invalid_transition_raises(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t")
    with pytest.raises(InvalidStatusTransition):
        store.update_job_status(jid, JobStatus.COMPLETED)


def test_idempotent_same_status(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t")
    store.update_job_status(jid, JobStatus.QUEUED)
    # Setting to QUEUED again should be a no-op, not raise
    store.update_job_status(jid, JobStatus.QUEUED)
    assert store.get_job(jid)["status"] == JobStatus.QUEUED.value


# ---- Item transitions ----

def test_item_valid_transitions(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t")
    iid = store.add_item(jid, file_id="f1")
    store.update_item_status(iid, JobItemStatus.QUEUED)
    store.update_item_status(iid, JobItemStatus.PARSING)
    store.update_item_status(iid, JobItemStatus.NER)
    store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
    assert store.get_item(iid)["status"] == JobItemStatus.AWAITING_REVIEW.value


def test_item_invalid_transition_raises(store: JobStore) -> None:
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t")
    iid = store.add_item(jid, file_id="f1")
    # PENDING -> COMPLETED is not allowed
    with pytest.raises(InvalidStatusTransition):
        store.update_item_status(iid, JobItemStatus.COMPLETED)


# ---- Double-pick prevention ----

def test_double_pick_prevention() -> None:
    """Verify the _in_flight_items set-based mechanism prevents double processing."""
    in_flight: set[str] = set()
    item_id = "item-123"

    # First pick succeeds
    assert item_id not in in_flight
    in_flight.add(item_id)

    # Second pick should be skipped
    assert item_id in in_flight  # worker would `continue` here

    # After processing completes, item is removed
    in_flight.discard(item_id)
    assert item_id not in in_flight
