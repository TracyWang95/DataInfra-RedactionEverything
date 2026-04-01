"""
file_store SQLite 后端 — 替代全量内存 JSON dict。

对外暴露与原 dict 兼容的接口（get/set/__contains__/values/items/pop），
内部用 SQLite + LRU 热缓存，支持万级文件不爆内存。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from typing import Any, Iterator, Optional

from app.core.persistence import to_jsonable

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_store (
    file_id TEXT PRIMARY KEY,
    data_json TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_fs_created ON file_store(created_at);
"""


class FileStoreDB:
    """SQLite-backed file store with dict-like API.

    注意：不使用进程内缓存，每次读写均直接访问 SQLite。
    这样 Celery worker 写入的数据可立即被 FastAPI 进程读到，避免跨进程脏缓存。
    SQLite WAL 模式 + busy_timeout=5000 可满足并发读写需求。
    """

    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        d = os.path.dirname(db_path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def get(self, file_id: str) -> Optional[dict]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT data_json FROM file_store WHERE file_id = ?", (file_id,)
                ).fetchone()
        if not row:
            return None
        return json.loads(row["data_json"])

    def __contains__(self, file_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM file_store WHERE file_id = ? LIMIT 1", (file_id,)
                ).fetchone()
        return row is not None

    def __getitem__(self, file_id: str) -> dict:
        val = self.get(file_id)
        if val is None:
            raise KeyError(file_id)
        return val

    def __setitem__(self, file_id: str, data: dict) -> None:
        self.set(file_id, data)

    def set(self, file_id: str, data: dict) -> None:
        data_json = json.dumps(to_jsonable(data), ensure_ascii=False, default=str)
        created = data.get("created_at", "")
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO file_store (file_id, data_json, created_at, updated_at)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    (file_id, data_json, created),
                )
                conn.commit()

    def update_fields(self, file_id: str, updates: dict) -> None:
        """部分更新：读取 → 合并 → 写回。"""
        existing = self.get(file_id)
        if existing is None:
            return
        existing.update(updates)
        self.set(file_id, existing)

    def pop(self, file_id: str, default: Any = None) -> Any:
        val = self.get(file_id)
        if val is None:
            return default
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM file_store WHERE file_id = ?", (file_id,))
                conn.commit()
        return val

    def __delitem__(self, file_id: str) -> None:
        self.pop(file_id)

    def values(self) -> list[dict]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT data_json FROM file_store").fetchall()
        return [json.loads(r["data_json"]) for r in rows]

    def items(self) -> list[tuple[str, dict]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT file_id, data_json FROM file_store").fetchall()
        return [(r["file_id"], json.loads(r["data_json"])) for r in rows]

    def keys(self) -> list[str]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT file_id FROM file_store").fetchall()
        return [r["file_id"] for r in rows]

    def __len__(self) -> int:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS c FROM file_store").fetchone()
        return row["c"]

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM file_store")
                conn.commit()

    def update(self, data: dict[str, dict]) -> None:
        """Bulk insert/replace entries (dict-compatible)."""
        with self._lock:
            with self._connect() as conn:
                for file_id, info in data.items():
                    data_json = json.dumps(to_jsonable(info), ensure_ascii=False, default=str)
                    created = info.get("created_at", "")
                    conn.execute(
                        "INSERT OR REPLACE INTO file_store (file_id, data_json, created_at, updated_at) "
                        "VALUES (?, ?, ?, datetime('now'))",
                        (file_id, data_json, created),
                    )
                conn.commit()

    def __iter__(self) -> Iterator[str]:
        """Iterate over file IDs (enables dict(store) compatibility)."""
        return iter(self.keys())

    def migrate_from_json(self, json_path: str) -> int:
        """从旧 JSON file_store 迁移数据到 SQLite。返回迁移条数。"""
        if not os.path.exists(json_path):
            return 0
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return 0
        if not isinstance(old_data, dict):
            return 0
        count = 0
        for file_id, info in old_data.items():
            if not isinstance(info, dict):
                continue
            self.set(file_id, info)
            count += 1
        logger.info("Migrated %d files from JSON to SQLite file_store", count)
        # 备份旧文件
        backup = json_path + ".migrated"
        try:
            os.rename(json_path, backup)
            logger.info("Old JSON file_store backed up to %s", backup)
        except OSError:
            pass
        return count
