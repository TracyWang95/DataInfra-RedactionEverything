"""Jobs REST API（挂载 jobs 路由 + 临时 JobStore）。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import jobs as jobs_mod
from app.api import files as files_mod
from app.core.config import settings
from app.models.schemas import RedactionResult
from app.services.job_store import JobItemStatus, JobStatus, JobStore, JobType


@pytest.fixture
def job_store(tmp_path: Path) -> JobStore:
    return JobStore(str(tmp_path / "jobs.sqlite3"))


@pytest.fixture
def client(job_store: JobStore) -> TestClient:
    app = FastAPI()
    app.include_router(jobs_mod.router, prefix=settings.API_PREFIX)

    def _override() -> JobStore:
        return job_store

    app.dependency_overrides[jobs_mod.get_job_store] = _override
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_file_store():
    backup = dict(files_mod.file_store)
    files_mod.file_store.clear()
    yield
    files_mod.file_store.clear()
    files_mod.file_store.update(backup)


def test_post_jobs_create_draft(client: TestClient) -> None:
    r = client.post(
        f"{settings.API_PREFIX}/jobs",
        json={"job_type": "text_batch", "title": "我的批次", "config": {"entity_type_ids": []}},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["id"]
    assert data["status"] == "draft"
    assert data["job_type"] == "text_batch"
    assert data["nav_hints"]["item_count"] == 0
    assert data["nav_hints"]["first_awaiting_review_item_id"] is None
    assert data["nav_hints"].get("batch_step1_configured") is False


def test_nav_hints_batch_step1_configured_when_entity_types(client: TestClient, job_store: JobStore) -> None:
    jid = job_store.create_job(
        job_type=JobType.TEXT_BATCH,
        title="cfg",
        config={"entity_type_ids": ["n1"], "wizard_furthest_step": 1},
    )
    r = client.get(f"{settings.API_PREFIX}/jobs")
    assert r.status_code == 200
    row = next(j for j in r.json()["jobs"] if j["id"] == jid)
    assert row["nav_hints"]["batch_step1_configured"] is True


def test_job_summary_nav_hints_list(client: TestClient, job_store: JobStore) -> None:
    jid = job_store.create_job(job_type=JobType.TEXT_BATCH, title="nav")
    r = client.get(f"{settings.API_PREFIX}/jobs")
    assert r.status_code == 200
    row = next(j for j in r.json()["jobs"] if j["id"] == jid)
    assert row["nav_hints"]["item_count"] == 0
    assert row["nav_hints"]["first_awaiting_review_item_id"] is None
    assert row["nav_hints"].get("batch_step1_configured") is False
    iid = job_store.add_item(jid, file_id="f1", sort_order=0)
    job_store.update_item_status(iid, JobItemStatus.QUEUED)
    job_store.update_item_status(iid, JobItemStatus.PARSING)
    job_store.update_item_status(iid, JobItemStatus.NER)
    job_store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
    job_store.update_job_status(jid, JobStatus.QUEUED)
    job_store.update_job_status(jid, JobStatus.RUNNING)
    job_store.update_job_status(jid, JobStatus.AWAITING_REVIEW)
    r2 = client.get(f"{settings.API_PREFIX}/jobs")
    row2 = next(j for j in r2.json()["jobs"] if j["id"] == jid)
    assert row2["nav_hints"]["item_count"] == 1
    assert row2["nav_hints"]["first_awaiting_review_item_id"] == iid


def test_get_jobs_filter_type(client: TestClient, job_store: JobStore) -> None:
    job_store.create_job(job_type=JobType.TEXT_BATCH, title="t")
    job_store.create_job(job_type=JobType.IMAGE_BATCH, title="i")
    r = client.get(f"{settings.API_PREFIX}/jobs", params={"job_type": "image_batch"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["jobs"][0]["job_type"] == "image_batch"


def test_job_detail_with_items_and_progress(client: TestClient, job_store: JobStore) -> None:
    jid = job_store.create_job(job_type=JobType.TEXT_BATCH, title="j")
    job_store.add_item(jid, file_id="f1", sort_order=0)
    job_store.add_item(jid, file_id="f2", sort_order=1)
    files_mod.file_store["f1"] = {"original_filename": "a.docx", "file_type": "docx", "entities": []}
    files_mod.file_store["f2"] = {"original_filename": "b.docx", "file_type": "docx", "entities": []}
    r = client.get(f"{settings.API_PREFIX}/jobs/{jid}")
    assert r.status_code == 200
    d = r.json()
    assert d["progress"]["total_items"] == 2
    assert len(d["items"]) == 2
    assert d["items"][0]["filename"] == "a.docx"
    assert d["items"][0]["has_review_draft"] is False
    assert d["nav_hints"]["item_count"] == 2
    assert d["nav_hints"]["first_awaiting_review_item_id"] is None


def test_submit_job(client: TestClient, job_store: JobStore) -> None:
    jid = job_store.create_job(job_type=JobType.TEXT_BATCH, title="j")
    job_store.add_item(jid, file_id="f1", sort_order=0)
    r = client.post(f"{settings.API_PREFIX}/jobs/{jid}/submit")
    assert r.status_code == 200
    assert r.json()["status"] in ("queued", "running")


def test_delete_job_detaches_file_links(
    client: TestClient,
    job_store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jid = job_store.create_job(job_type=JobType.TEXT_BATCH, title="delete")
    job_store.add_item(jid, file_id="f1", sort_order=0)
    files_mod.file_store["f1"] = {
        "original_filename": "batch.docx",
        "file_type": "docx",
        "job_id": jid,
        "batch_group_id": jid,
        "upload_source": "batch",
        "entities": [],
    }
    # persist_file_store removed — SQLite auto-persists; no monkeypatch needed

    res = client.delete(f"{settings.API_PREFIX}/jobs/{jid}")

    assert res.status_code == 200
    body = res.json()
    assert body["deleted"] is True
    assert body["deleted_item_count"] == 1
    assert body["detached_file_count"] == 1
    assert job_store.get_job(jid) is None
    assert job_store.list_items(jid) == []
    assert "job_id" not in files_mod.file_store["f1"]
    assert files_mod.file_store["f1"]["batch_group_id"] == jid


def test_delete_active_job_requires_cancel_first(client: TestClient, job_store: JobStore) -> None:
    jid = job_store.create_job(job_type=JobType.TEXT_BATCH, title="running")
    job_store.add_item(jid, file_id="f1", sort_order=0)
    job_store.submit_job(jid)

    res = client.delete(f"{settings.API_PREFIX}/jobs/{jid}")

    assert res.status_code == 409
    assert "cancelled before deletion" in res.json()["detail"]
    assert job_store.get_job(jid) is not None


def test_approve_review(client: TestClient, job_store: JobStore) -> None:
    jid = job_store.create_job(job_type=JobType.TEXT_BATCH, title="j")
    iid = job_store.add_item(jid, file_id="f1", sort_order=0)
    job_store.update_item_status(iid, JobItemStatus.QUEUED)
    job_store.update_item_status(iid, JobItemStatus.PARSING)
    job_store.update_item_status(iid, JobItemStatus.NER)
    job_store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
    r = client.post(f"{settings.API_PREFIX}/jobs/{jid}/items/{iid}/review/approve", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "review_approved"


def test_approve_twice_idempotent(client: TestClient, job_store: JobStore) -> None:
    jid = job_store.create_job(job_type=JobType.TEXT_BATCH, title="j")
    iid = job_store.add_item(jid, file_id="f1", sort_order=0)
    job_store.update_item_status(iid, JobItemStatus.QUEUED)
    job_store.update_item_status(iid, JobItemStatus.PARSING)
    job_store.update_item_status(iid, JobItemStatus.NER)
    job_store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
    url = f"{settings.API_PREFIX}/jobs/{jid}/items/{iid}/review/approve"
    assert client.post(url, json={}).status_code == 200
    assert client.post(url, json={}).status_code == 200


def test_add_item_by_file_id(client: TestClient, job_store: JobStore) -> None:
    jid = job_store.create_job(job_type=JobType.TEXT_BATCH, title="j")
    r = client.post(f"{settings.API_PREFIX}/jobs/{jid}/items", json={"file_id": "abc-123", "sort_order": 0})
    assert r.status_code == 200
    assert r.json()["file_id"] == "abc-123"


def test_review_draft_roundtrip_api(client: TestClient, job_store: JobStore) -> None:
    jid = job_store.create_job(job_type=JobType.TEXT_BATCH, title="j")
    iid = job_store.add_item(jid, file_id="f1", sort_order=0)
    job_store.update_item_status(iid, JobItemStatus.QUEUED)
    job_store.update_item_status(iid, JobItemStatus.PARSING)
    job_store.update_item_status(iid, JobItemStatus.NER)
    job_store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
    put_res = client.put(
        f"{settings.API_PREFIX}/jobs/{jid}/items/{iid}/review-draft",
        json={
            "entities": [{"id": "e1", "text": "Alice", "type": "PERSON", "start": 0, "end": 5, "selected": True}],
            "bounding_boxes": [],
        },
    )
    assert put_res.status_code == 200
    get_res = client.get(f"{settings.API_PREFIX}/jobs/{jid}/items/{iid}/review-draft")
    assert get_res.status_code == 200
    body = get_res.json()
    assert body["entities"][0]["text"] == "Alice"
    assert body["updated_at"]


def test_review_commit_marks_completed_and_clears_draft(
    client: TestClient,
    job_store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api import redaction as redaction_mod

    file_path = tmp_path / "input.docx"
    file_path.write_bytes(b"hello")
    files_mod.file_store["f1"] = {
        "original_filename": "input.docx",
        "file_type": "docx",
        "file_path": str(file_path),
        "entities": [],
    }
    jid = job_store.create_job(
        job_type=JobType.TEXT_BATCH,
        title="j",
        config={"replacement_mode": "structured", "entity_type_ids": ["PERSON"]},
    )
    iid = job_store.add_item(jid, file_id="f1", sort_order=0)
    job_store.update_item_status(iid, JobItemStatus.QUEUED)
    job_store.update_item_status(iid, JobItemStatus.PARSING)
    job_store.update_item_status(iid, JobItemStatus.NER)
    job_store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
    job_store.save_item_review_draft(iid, {"entities": [{"id": "e1"}], "bounding_boxes": []})

    async def fake_execute(request):
        output_path = tmp_path / "out.docx"
        output_path.write_bytes(b"redacted")
        files_mod.file_store["f1"]["output_path"] = str(output_path)
        files_mod.file_store["f1"]["entities"] = request.entities
        return RedactionResult(
            file_id=request.file_id,
            output_file_id="out-1",
            redacted_count=len(request.entities),
            entity_map={"Alice": "[PERSON]"},
            download_url="/api/v1/files/f1/download?redacted=true",
        )

    monkeypatch.setattr(redaction_mod, "execute_redaction", fake_execute)

    res = client.post(
        f"{settings.API_PREFIX}/jobs/{jid}/items/{iid}/review/commit",
        json={
            "entities": [{"id": "e1", "text": "Alice", "type": "PERSON", "start": 0, "end": 5, "selected": True}],
            "bounding_boxes": [],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "completed"
    assert body["has_output"] is True
    assert body["has_review_draft"] is False
    assert job_store.get_item(iid)["review_draft_json"] is None
    assert job_store.get_job(jid)["status"] == JobStatus.COMPLETED.value


def test_review_commit_recovers_output_path_from_output_file_id(
    client: TestClient,
    job_store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import redaction as redaction_mod

    output_file_id = "img-out-1"
    output_path = Path(settings.OUTPUT_DIR) / f"{output_file_id}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"png")

    files_mod.file_store["img1"] = {
        "original_filename": "sample.png",
        "file_type": "image",
        "file_path": "D:/tmp/sample.png",
        "bounding_boxes": {"1": []},
    }
    jid = job_store.create_job(
        job_type=JobType.IMAGE_BATCH,
        title="image",
        config={"image_redaction_method": "fill"},
    )
    iid = job_store.add_item(jid, file_id="img1", sort_order=0)
    job_store.update_item_status(iid, JobItemStatus.QUEUED)
    job_store.update_item_status(iid, JobItemStatus.PARSING)
    job_store.update_item_status(iid, JobItemStatus.VISION)
    job_store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)

    async def fake_execute(_request):
        info = files_mod.file_store["img1"]
        info.pop("output_path", None)
        files_mod.file_store["img1"] = info
        return RedactionResult(
            file_id="img1",
            output_file_id=output_file_id,
            redacted_count=1,
            entity_map={},
            download_url="/api/v1/files/img1/download?redacted=true",
        )

    monkeypatch.setattr(redaction_mod, "execute_redaction", fake_execute)

    try:
        res = client.post(
            f"{settings.API_PREFIX}/jobs/{jid}/items/{iid}/review/commit",
            json={
                "entities": [],
                "bounding_boxes": [
                    {
                        "id": "b1",
                        "x": 0.1,
                        "y": 0.2,
                        "width": 0.3,
                        "height": 0.4,
                        "page": 1,
                        "type": "face",
                        "selected": True,
                    }
                ],
            },
        )
        assert res.status_code == 200
        assert res.json()["status"] == "completed"
        assert res.json()["has_output"] is True
        assert files_mod.file_store["img1"]["output_path"] == str(output_path.resolve())
    finally:
        output_path.unlink(missing_ok=True)


def test_review_commit_idempotent_for_completed_item(client: TestClient, job_store: JobStore) -> None:
    files_mod.file_store["f1"] = {"original_filename": "done.docx", "file_type": "docx", "entities": []}
    jid = job_store.create_job(job_type=JobType.TEXT_BATCH, title="j")
    iid = job_store.add_item(jid, file_id="f1", sort_order=0)
    job_store.update_item_status(iid, JobItemStatus.QUEUED)
    job_store.update_item_status(iid, JobItemStatus.PARSING)
    job_store.update_item_status(iid, JobItemStatus.NER)
    job_store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
    job_store.update_item_status(iid, JobItemStatus.REVIEW_APPROVED)
    job_store.update_item_status(iid, JobItemStatus.REDACTING)
    job_store.update_item_status(iid, JobItemStatus.COMPLETED)
    res = client.post(
        f"{settings.API_PREFIX}/jobs/{jid}/items/{iid}/review/commit",
        json={"entities": [], "bounding_boxes": []},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "completed"
