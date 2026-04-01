from __future__ import annotations

from pathlib import Path

from app.api import files as files_mod
from app.services.job_store import JobItemStatus, JobStatus, JobStore, JobType


def test_repair_failed_missing_files_requeues_existing_files(tmp_path: Path) -> None:
    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    upload_path = tmp_path / "uploads"
    upload_path.mkdir()
    file_path = upload_path / "sample.docx"
    file_path.write_bytes(b"demo")

    backup = dict(files_mod.file_store)
    files_mod.file_store.clear()
    try:
        files_mod.file_store.set(
            "f1",
            {
                "original_filename": "sample.docx",
                "file_type": "docx",
                "file_path": str(file_path),
            },
        )
        job_id = store.create_job(job_type=JobType.TEXT_BATCH, title="repair")
        item_id = store.add_item(job_id, file_id="f1", sort_order=0)
        store.submit_job(job_id)
        store.update_item_status(item_id, JobItemStatus.PARSING)
        store.update_item_status(item_id, JobItemStatus.FAILED, error_message="文件不存在")
        store.update_job_status(job_id, JobStatus.RUNNING)
        store.update_job_status(job_id, JobStatus.FAILED)

        repaired = store.repair_failed_missing_files()

        assert repaired == 1
        assert store.get_item(item_id)["status"] == JobItemStatus.QUEUED.value
        assert store.get_item(item_id)["error_message"] is None
        assert store.get_job(job_id)["status"] == JobStatus.QUEUED.value
    finally:
        files_mod.file_store.clear()
        files_mod.file_store.update(backup)
