"""Phase 1c 数据保留策略：默认关闭、超龄清理、单个失败不阻断。"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.services import retention_service


class FakeStore:
    def __init__(self, entries):
        self._entries = entries

    def items(self):
        return list(self._entries.items())


def _iso(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _run_sweep(monkeypatch, days, entries, fail_ids=frozenset()):
    import app.services.file_management_service as fms

    deleted: list[str] = []

    async def fake_delete(file_id):
        if file_id in fail_ids:
            raise RuntimeError("locked")
        deleted.append(file_id)

    monkeypatch.setattr(settings, "DATA_RETENTION_DAYS", days)
    monkeypatch.setattr(fms, "file_store", FakeStore(entries))
    monkeypatch.setattr(fms, "delete_file", fake_delete)
    count = asyncio.run(retention_service.retention_sweep())
    return count, deleted


def test_disabled_by_default_deletes_nothing(monkeypatch):
    entries = {"a": {"created_at": _iso(400)}}
    count, deleted = _run_sweep(monkeypatch, 0, entries)
    assert count == 0 and deleted == []


def test_deletes_only_expired(monkeypatch):
    entries = {
        "old": {"created_at": _iso(31)},
        "fresh": {"created_at": _iso(2)},
        "no_date": {"filename": "x"},
        "bad_date": {"created_at": "not-a-date"},
    }
    count, deleted = _run_sweep(monkeypatch, 30, entries)
    assert count == 1 and deleted == ["old"]


def test_one_failure_does_not_stop_the_sweep(monkeypatch):
    entries = {
        "old1": {"created_at": _iso(40)},
        "old2": {"created_at": _iso(50)},
    }
    count, deleted = _run_sweep(monkeypatch, 30, entries, fail_ids={"old1"})
    assert count == 1 and deleted == ["old2"]


def test_validator_clamps():
    settings_cls = type(settings)
    assert settings_cls(DATA_RETENTION_DAYS=-5).DATA_RETENTION_DAYS == 0
    assert settings_cls(DATA_RETENTION_DAYS=99999).DATA_RETENTION_DAYS == 3650
