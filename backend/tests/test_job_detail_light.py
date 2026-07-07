"""W0-1：GET /jobs/{id} 轻量模式——万级任务 38MB 载荷是向导恢复卡死的根因。"""
from __future__ import annotations

import asyncio

from app.api.jobs import get_job_detail
from app.services.job_store import JobItemStatus, JobStore, JobType


def _make_job(tmp_path):
    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t", owner_id="admin")
    item_ids = [store.add_item(jid, f"f{i}") for i in range(3)]
    for iid in item_ids:
        store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
        store.update_item_performance(
            iid, {"recognition": {"pages": {str(p): {"duration_ms": 1234} for p in range(5)}}}
        )
    return store, jid


def test_light_mode_strips_performance(tmp_path):
    store, jid = _make_job(tmp_path)
    detail = asyncio.run(get_job_detail(jid, performance=False, store=store, owner_id="admin"))
    assert len(detail["items"]) == 3
    assert all("performance" not in item or not item["performance"] for item in detail["items"])
    # 恢复所需的状态字段仍在
    assert all(item["status"] == "awaiting_review" and item["file_id"] for item in detail["items"])


def test_default_mode_keeps_performance(tmp_path):
    store, jid = _make_job(tmp_path)
    detail = asyncio.run(get_job_detail(jid, performance=True, store=store, owner_id="admin"))
    assert any(
        (item.get("performance") or {}).get("recognition") for item in detail["items"]
    ), "default mode must keep per-item performance (benchmark depends on it)"
