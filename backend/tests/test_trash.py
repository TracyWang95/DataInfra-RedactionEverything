"""R1-4 软删除回收站：标记/还原/彻底删/超期清扫。"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.services import file_management_service as fms
from app.services.retention_service import trash_sweep


@pytest.fixture
def seeded_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "OUTPUT_DIR", str(tmp_path))
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    fid = "trash-test-file"
    fms.file_store.set(fid, {
        "original_filename": "doc.txt",
        "file_type": "txt",
        "file_path": str(src),
        "owner_id": "admin",
        "created_at": datetime.now(UTC).isoformat(),
    })
    yield fid, src
    fms.file_store.pop(fid, None)


def test_soft_delete_restore_roundtrip(seeded_file):
    fid, src = seeded_file

    async def flow():
        snap = await fms.soft_delete_file(fid)
        assert snap and snap["deleted_at"]
        assert src.exists(), "soft delete must keep the disk file"
        # 重复软删无效
        assert await fms.soft_delete_file(fid) is None
        trashed = await fms.list_trashed_files(owner_id="admin")
        assert any(r["file_id"] == fid for r in trashed)
        # 还原
        restored = await fms.restore_file(fid)
        assert restored and "deleted_at" not in restored
        assert await fms.restore_file(fid) is None  # 不在回收站
        assert not any(
            r["file_id"] == fid for r in await fms.list_trashed_files(owner_id="admin")
        )

    asyncio.run(flow())


def test_purge_removes_disk_file(seeded_file):
    fid, src = seeded_file

    async def flow():
        await fms.soft_delete_file(fid)
        snap = await fms.delete_file(fid)
        assert snap is not None
        assert not src.exists(), "purge must remove the disk file"

    asyncio.run(flow())


def test_trash_sweep_purges_only_expired(seeded_file, monkeypatch):
    fid, src = seeded_file
    monkeypatch.setattr(settings, "TRASH_RETENTION_DAYS", 7)

    async def flow():
        await fms.soft_delete_file(fid)
        # 未超期：不清
        assert await trash_sweep() == 0
        assert src.exists()
        # 伪造超期
        info = dict(fms.file_store.get(fid))
        info["deleted_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        fms.file_store.set(fid, info)
        purged = await trash_sweep()
        assert purged == 1
        assert not src.exists()
        assert fms.file_store.get(fid) is None

    asyncio.run(flow())


def test_dataset_soft_delete_restore_purge(tmp_path):
    """F1-1：结构化数据集软删/还原/超期清扫。"""
    from datetime import UTC, datetime, timedelta

    from app.services.structured_store import StructuredStore

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    ds = store.upsert_dataset(
        owner_id="admin", name="t.csv", dataset_type="file",
        source_kind="csv", shape_kind="flat_table",
    )
    ds_id = ds["id"]
    assert store.soft_delete_dataset(ds_id, owner_id="admin") is True
    # 列表不见、回收站可见
    assert all(d["id"] != ds_id for d in store.list_datasets(owner_id="admin"))
    trashed = store.list_trashed_datasets(owner_id="admin")
    assert any(d["id"] == ds_id for d in trashed)
    # 重复软删/越权
    assert store.soft_delete_dataset(ds_id, owner_id="admin") is False
    assert store.restore_dataset(ds_id, owner_id="intruder") is False
    # 还原
    assert store.restore_dataset(ds_id, owner_id="admin") is True
    assert any(d["id"] == ds_id for d in store.list_datasets(owner_id="admin"))
    # 超期清扫
    store.soft_delete_dataset(ds_id, owner_id="admin")
    future_cutoff = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert store.purge_expired_trashed_datasets(older_than_iso=future_cutoff) == 1
    assert store.list_trashed_datasets(owner_id="admin") == []
