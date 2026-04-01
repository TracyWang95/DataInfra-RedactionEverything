"""Job Worker：识别后在 awaiting_review 暂停；approve 后才执行脱敏（TDD，使用 Mock ports）。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.job_runner import JobRunnerPorts, _run_recognition, _run_redaction
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
        # Simulate setting output_path like the real redactor does
        from app.api.files import file_store
        info = file_store.get(file_id)
        if info is not None:
            info["output_path"] = "/tmp/mock_output.docx"
            file_store.set(file_id, info)


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(str(tmp_path / "j.db"))


def _make_job_and_item(store, file_id="f1", skip_item_review=False, config=None):
    """Helper: create a submitted job with one item, return (job_row, item_id)."""
    cfg = config or {"entity_type_ids": ["PERSON"]}
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t", config=cfg, skip_item_review=skip_item_review)
    iid = store.add_item(jid, file_id=file_id, sort_order=0)
    store.submit_job(jid)
    job_row = store.get_job(jid)
    return job_row, iid


def test_recognition_ends_at_awaiting_review_no_execute(store: JobStore) -> None:
    ports = MockPorts()
    job_row, iid = _make_job_and_item(store)
    item = store.get_item(iid)
    asyncio.run(_run_recognition(store, ports, job_row, iid, item["file_id"]))
    assert store.get_item(iid)["status"] == JobItemStatus.AWAITING_REVIEW.value
    assert len(ports.parse_calls) == 1
    assert len(ports.ner_calls) == 1
    assert len(ports.execute_calls) == 0


def test_skip_item_review_goes_straight_to_execute(store: JobStore) -> None:
    ports = MockPorts()
    from app.api.files import file_store
    file_store.set("f1", {"file_path": "/tmp/f1.docx", "file_type": "docx"})
    job_row, iid = _make_job_and_item(store, skip_item_review=True, config={"entity_type_ids": []})
    item = store.get_item(iid)
    asyncio.run(_run_recognition(store, ports, job_row, iid, item["file_id"]))
    assert store.get_item(iid)["status"] == JobItemStatus.COMPLETED.value
    assert len(ports.execute_calls) == 1


def test_after_approve_worker_runs_execute(store: JobStore) -> None:
    ports = MockPorts()
    from app.api.files import file_store
    file_store.set("f1", {"file_path": "/tmp/f1.docx", "file_type": "docx"})
    job_row, iid = _make_job_and_item(store, config={})
    item = store.get_item(iid)
    asyncio.run(_run_recognition(store, ports, job_row, iid, item["file_id"]))
    assert store.get_item(iid)["status"] == JobItemStatus.AWAITING_REVIEW.value
    store.approve_item_review(iid)
    asyncio.run(_run_redaction(store, ports, job_row, iid, item["file_id"]))
    assert store.get_item(iid)["status"] == JobItemStatus.COMPLETED.value
    assert len(ports.execute_calls) == 1


def test_failed_item_does_not_freeze_remaining_queue(store: JobStore) -> None:
    class FailFirstPorts(MockPorts):
        async def hybrid_ner(self, file_id: str, entity_type_ids: list[str]) -> None:
            if file_id == "f1":
                raise HTTPException(status_code=404, detail="文件不存在")
            await super().hybrid_ner(file_id, entity_type_ids)

    ports = FailFirstPorts()
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t", config={"entity_type_ids": ["PERSON"]})
    iid1 = store.add_item(jid, file_id="f1", sort_order=0)
    iid2 = store.add_item(jid, file_id="f2", sort_order=1)
    store.submit_job(jid)
    job_row = store.get_job(jid)

    asyncio.run(_run_recognition(store, ports, job_row, iid1, "f1"))
    assert store.get_item(iid1)["status"] == JobItemStatus.FAILED.value
    assert store.get_job(jid)["status"] == JobStatus.RUNNING.value

    asyncio.run(_run_recognition(store, ports, job_row, iid2, "f2"))
    assert store.get_item(iid2)["status"] == JobItemStatus.AWAITING_REVIEW.value
    assert store.get_job(jid)["status"] == JobStatus.AWAITING_REVIEW.value
