"""Job Worker：识别后在 awaiting_review 暂停；approve 后才执行脱敏（TDD，使用 Mock ports）。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.job_runner import JobRunnerPorts, process_next_queue_item
from app.services.job_store import JobItemStatus, JobStatus, JobStore, JobType


class MockPorts(JobRunnerPorts):
    def __init__(self) -> None:
        self.parse_calls: list[str] = []
        self.ner_calls: list[str] = []
        self.vision_calls: list[str] = []
        self.execute_calls: list[str] = []

    async def parse_file(self, file_id: str) -> None:
        self.parse_calls.append(file_id)

    async def hybrid_ner(self, file_id: str, entity_type_ids: list[str]) -> None:
        self.ner_calls.append(file_id)

    async def vision_pages(self, file_id: str, job_config: dict) -> None:
        self.vision_calls.append(file_id)

    async def execute_redaction(self, file_id: str, job_config: dict) -> None:
        self.execute_calls.append(file_id)


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(str(tmp_path / "j.db"))


def test_recognition_ends_at_awaiting_review_no_execute(store: JobStore) -> None:
    ports = MockPorts()
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t", config={"entity_type_ids": ["PERSON"]})
    iid = store.add_item(jid, file_id="f1", sort_order=0)
    store.submit_job(jid)
    worked = asyncio.run(process_next_queue_item(store, ports))
    assert worked is True
    assert store.get_item(iid)["status"] == JobItemStatus.AWAITING_REVIEW.value
    assert len(ports.parse_calls) == 1
    assert len(ports.ner_calls) == 1
    assert len(ports.execute_calls) == 0


def test_skip_item_review_goes_straight_to_execute(store: JobStore) -> None:
    ports = MockPorts()
    jid = store.create_job(
        job_type=JobType.TEXT_BATCH,
        title="t",
        config={"entity_type_ids": []},
        skip_item_review=True,
    )
    iid = store.add_item(jid, file_id="f1", sort_order=0)
    store.submit_job(jid)
    asyncio.run(process_next_queue_item(store, ports))
    assert store.get_item(iid)["status"] == JobItemStatus.COMPLETED.value
    assert len(ports.execute_calls) == 1


def test_after_approve_worker_runs_execute(store: JobStore) -> None:
    ports = MockPorts()
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t", config={})
    iid = store.add_item(jid, file_id="f1", sort_order=0)
    store.submit_job(jid)
    asyncio.run(process_next_queue_item(store, ports))
    assert store.get_item(iid)["status"] == JobItemStatus.AWAITING_REVIEW.value
    store.approve_item_review(iid)
    asyncio.run(process_next_queue_item(store, ports))
    assert store.get_item(iid)["status"] == JobItemStatus.COMPLETED.value
    assert len(ports.execute_calls) == 1


def test_no_work_returns_false(store: JobStore) -> None:
    ports = MockPorts()
    assert asyncio.run(process_next_queue_item(store, ports)) is False
