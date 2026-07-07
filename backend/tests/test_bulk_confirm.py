from __future__ import annotations

import asyncio

from app.core import auth
from app.services import job_management_service as jms
from app.services.job_store import JobItemStatus


def _scope_auth(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "_AUTH_FILE", str(tmp_path / "auth.json"))


def test_bulk_confirm_permission_grant_and_revoke(monkeypatch, tmp_path):
    _scope_auth(monkeypatch, tmp_path)

    auth.create_user("emp1", "Passw0rd!", role="user")
    auth.create_user("boss", "Passw0rd!", role="super_admin")

    # Regular users start without the privilege; super admins always have it.
    assert auth.user_can_bulk_confirm("emp1") is False
    assert auth.user_can_bulk_confirm("boss") is True

    auth.set_user_bulk_confirm("emp1", True)
    assert auth.user_can_bulk_confirm("emp1") is True

    auth.set_user_bulk_confirm("emp1", False)
    assert auth.user_can_bulk_confirm("emp1") is False

    rows = {u["username"]: u for u in auth.list_users()}
    assert rows["boss"]["can_bulk_confirm"] is True
    assert rows["emp1"]["can_bulk_confirm"] is False


def test_set_bulk_confirm_unknown_user_raises(monkeypatch, tmp_path):
    _scope_auth(monkeypatch, tmp_path)
    try:
        auth.set_user_bulk_confirm("ghost", True)
    except Exception as exc:  # HTTPException(404)
        assert getattr(exc, "status_code", None) == 404
    else:
        raise AssertionError("expected 404 for unknown user")


class FakeBulkStore:
    """批量流 FakeStore：drafts 单查、单事务批量批准（带 status 守卫语义）。"""

    def __init__(self, items, drafts=None, approvable=None):
        self.items = items
        self.drafts = drafts or {}
        self.approvable = approvable  # None = 全部可批
        self.bulk_calls: list[list[str]] = []
        self.touched = False

    def get_job(self, job_id):
        return {"id": job_id}

    def list_items(self, job_id):
        return self.items

    def list_item_review_drafts(self, job_id):
        return self.drafts

    def approve_items_review_bulk(self, item_ids, reviewer="local"):
        self.bulk_calls.append(list(item_ids))
        by_id = {it["id"]: it for it in self.items}
        return [
            (iid, str(by_id[iid]["file_id"]))
            for iid in item_ids
            if self.approvable is None or iid in self.approvable
        ]

    def touch_job_updated(self, job_id):
        self.touched = True


def test_commit_all_reviews_targets_only_awaiting(monkeypatch):
    store = FakeBulkStore([
        {"id": "a", "file_id": "fa", "status": JobItemStatus.AWAITING_REVIEW.value},
        {"id": "b", "file_id": "fb", "status": JobItemStatus.AWAITING_REVIEW.value},
        {"id": "c", "file_id": "fc", "status": JobItemStatus.COMPLETED.value},
        {"id": "d", "file_id": "fd", "status": JobItemStatus.PENDING.value},
    ])
    enqueued: list[tuple] = []
    monkeypatch.setattr(
        jms, "enqueue_task", lambda tt, jid, iid, fid, meta=None: enqueued.append((tt, iid, fid))
    )
    monkeypatch.setattr(jms, "refresh_job_status", lambda store, job_id: None)

    result = asyncio.run(jms.commit_all_reviews(store, "j1", reviewer="boss"))

    assert store.bulk_calls == [["a", "b"]]
    assert enqueued == [("redaction", "a", "fa"), ("redaction", "b", "fb")]
    assert store.touched is True
    assert result["total_awaiting"] == 2 and result["confirmed"] == 2 and result["failed"] == []


def test_commit_all_reviews_reports_unapprovable_items(monkeypatch):
    store = FakeBulkStore(
        [
            {"id": "a", "file_id": "fa", "status": JobItemStatus.AWAITING_REVIEW.value},
            {"id": "b", "file_id": "fb", "status": JobItemStatus.AWAITING_REVIEW.value},
        ],
        approvable={"b"},  # a 在批准前被并发改了状态
    )
    enqueued: list[str] = []
    monkeypatch.setattr(
        jms, "enqueue_task", lambda tt, jid, iid, fid, meta=None: enqueued.append(iid)
    )
    monkeypatch.setattr(jms, "refresh_job_status", lambda store, job_id: None)

    result = asyncio.run(jms.commit_all_reviews(store, "j1"))

    assert result["confirmed"] == 1 and result["total_awaiting"] == 2
    assert enqueued == ["b"]
    assert result["failed"][0]["item_id"] == "a"


def test_commit_all_reviews_seeds_only_awaiting_drafts(monkeypatch):
    store = FakeBulkStore(
        [
            {"id": "a", "file_id": "fa", "status": JobItemStatus.AWAITING_REVIEW.value},
            {"id": "c", "file_id": "fc", "status": JobItemStatus.COMPLETED.value},
        ],
        drafts={
            "a": ("fa", {"entities": [{"id": "e1"}], "bounding_boxes": []}),
            "c": ("fc", {"entities": [{"id": "e2"}], "bounding_boxes": []}),
        },
    )
    seeded: list[str] = []

    async def fake_seed(file_id, draft):
        seeded.append(file_id)

    monkeypatch.setattr(jms, "_seed_file_store_from_draft_payload", fake_seed)
    monkeypatch.setattr(jms, "enqueue_task", lambda *a, **k: None)
    monkeypatch.setattr(jms, "refresh_job_status", lambda store, job_id: None)

    asyncio.run(jms.commit_all_reviews(store, "j1"))
    assert seeded == ["fa"]  # 已完成 item 的旧草稿不动 file_store


def test_bulk_approve_store_semantics(tmp_path):
    """真 sqlite 验证批量批准 SQL：status 守卫 + 单事务 + 幂等重放。"""
    from app.services.job_store import JobStore, JobType

    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    jid = store.create_job(job_type=JobType.TEXT_BATCH, title="t")
    i1 = store.add_item(jid, "f1")
    i2 = store.add_item(jid, "f2")
    for iid in (i1, i2):
        store.update_item_status(iid, JobItemStatus.AWAITING_REVIEW)
    i3 = store.add_item(jid, "f3")  # 还在 pending，不该被批

    approved = store.approve_items_review_bulk([i1, i2, i3], reviewer="boss")
    assert sorted(approved) == sorted([(i1, "f1"), (i2, "f2")])
    assert store.get_item(i1)["status"] == JobItemStatus.REVIEW_APPROVED.value
    assert store.get_item(i3)["status"] == JobItemStatus.PENDING.value
    # 重放幂等：已批准的不再返回
    assert store.approve_items_review_bulk([i1, i2, i3]) == []
    # 草稿单查：只返回有草稿的
    store.save_item_review_draft(i1, {"entities": [], "bounding_boxes": [{"id": "b"}]})
    drafts = store.list_item_review_drafts(jid)
    assert set(drafts) == {i1} and drafts[i1][0] == "f1"
