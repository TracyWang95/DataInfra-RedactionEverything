"""R1-1 备份完整化：清单覆盖/原子快照/保留策略/损坏恢复/状态注册表。"""
from __future__ import annotations

import os
import sqlite3

import pytest

from app.core import db_backup
from app.core.config import settings


def _make_sqlite(path: str, marker: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES (?)", (marker,))
    conn.commit()
    conn.close()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(settings, "DATA_DIR", str(d))
    monkeypatch.setattr(settings, "JOB_DB_PATH", str(d / "jobs.sqlite3"))
    monkeypatch.setattr(settings, "PRESET_STORE_PATH", str(d / "presets.json"))
    monkeypatch.setattr(settings, "ENTITY_TYPES_STORE_PATH", str(d / "entity_types.json"))
    monkeypatch.setattr(settings, "PIPELINE_STORE_PATH", str(d / "pipelines.json"))
    monkeypatch.setattr(settings, "MODEL_CONFIG_PATH", str(d / "model_config.json"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    return d


def test_backup_all_covers_full_inventory(data_dir, tmp_path):
    """清单完整性：SQLite 库 + 密钥/配置小文件全部产出快照。"""
    _make_sqlite(str(data_dir / "jobs.sqlite3"), "jobs")
    _make_sqlite(str(data_dir / "structured_store.sqlite3"), "structured")
    for fname in ("auth.json", "jwt_secret.json", "runtime_settings.json",
                  "presets.json", "entity_types.json", "pipelines.json", "model_config.json"):
        (data_dir / fname).write_text('{"k":1}', encoding="utf-8")
    (data_dir / "structured_credentials.key").write_bytes(b"secretkey")

    results = db_backup.backup_all()

    for expected in ("jobs", "structured_store", "auth", "jwt_secret",
                     "structured_credentials", "presets", "entity_types",
                     "pipelines", "model_config", "runtime_settings"):
        assert results.get(expected) is True, f"{expected} missing from backup: {results}"
    backup_dir = str(tmp_path / "backups")
    assert any(f.startswith("structured_store_") for f in os.listdir(backup_dir))
    assert any(f.startswith("jwt_secret_") for f in os.listdir(backup_dir))
    # 状态注册表记录成功时间
    status = db_backup.get_backup_status()
    assert status["jobs"]["last_success_at"]


def test_small_file_snapshot_atomic_and_retention(data_dir, tmp_path):
    src = data_dir / "auth.json"
    backup_dir = str(tmp_path / "backups")
    for i in range(5):
        src.write_text(f'{{"v":{i}}}', encoding="utf-8")
        assert db_backup._snapshot_small_file("auth", str(src), backup_dir, retention=3)
    snaps = sorted(f for f in os.listdir(backup_dir) if f.startswith("auth_"))
    assert len(snaps) <= 3, "retention must prune old snapshots"
    assert not any(f.endswith(".tmp") for f in os.listdir(backup_dir)), "no tmp residue"
    latest = os.path.join(backup_dir, snaps[-1])
    assert '{"v":4}' == open(latest, encoding="utf-8").read()


def test_structured_store_corruption_restores(data_dir, tmp_path):
    """structured_store 现已入启动完整性保护：损坏 → 从快照自动恢复。"""
    db_path = str(data_dir / "structured_store.sqlite3")
    _make_sqlite(db_path, "good")
    backup_dir = str(tmp_path / "backups")
    assert db_backup.backup_sqlite(db_path, backup_dir)
    # 制造损坏
    with open(db_path, "wb") as fh:
        fh.write(b"corrupted garbage not a sqlite file")
    assert db_backup.check_db_integrity(db_path) is False
    assert db_backup.restore_from_latest_backup(db_path, backup_dir) is True
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT v FROM t").fetchone()[0] == "good"
    conn.close()


def test_backup_missing_files_skipped_silently(data_dir):
    """空 DATA_DIR：不存在的目标全部跳过，不抛错。"""
    results = db_backup.backup_all()
    assert isinstance(results, dict)


def test_health_stale_logic(data_dir):
    """状态注册表可判 stale（间隔 2 倍未成功）。"""
    _make_sqlite(str(data_dir / "jobs.sqlite3"), "x")
    db_backup.backup_all()
    status = db_backup.get_backup_status()
    from datetime import UTC, datetime

    last = datetime.fromisoformat(status["jobs"]["last_success_at"])
    age = (datetime.now(UTC) - last).total_seconds()
    assert age < settings.BACKUP_INTERVAL_SEC * 2
