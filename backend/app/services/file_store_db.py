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
import time
from collections.abc import Callable, Iterator
from copy import deepcopy
from typing import Any

from app.core.persistence import to_jsonable
from app.core.sqlite_base import connect_sqlite

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

_RETRYABLE_SQLITE_MESSAGES = (
    "unable to open database file",
    "database is locked",
    "disk i/o error",
)


class FileStoreDB:
    """SQLite-backed file store with dict-like API.

    注意：不使用进程内缓存，每次读写均直接访问 SQLite。
    SQLite WAL 模式 + busy_timeout=5000 可满足并发读写需求。
    """

    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._item_cache: dict[str, dict] = {}
        self._all_rows_cache: list[tuple[str, str]] | None = None
        d = os.path.dirname(db_path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._init_db()

    @property
    def db_path(self) -> str:
        return self._path

    def _connect(self):
        return connect_sqlite(self._path, timeout=10.0, busy_timeout_ms=5000, wal=True)

    def _invalidate_read_cache(self, file_id: str | None = None) -> None:
        self._all_rows_cache = None
        if file_id is None:
            self._item_cache.clear()
        else:
            self._item_cache.pop(file_id, None)

    def _cached_all_rows(self) -> list[tuple[str, str]]:
        with self._lock:
            if self._all_rows_cache is not None:
                return list(self._all_rows_cache)

        def op():
            with self._lock:
                if self._all_rows_cache is not None:
                    return list(self._all_rows_cache)
                with self._connect() as conn:
                    rows = conn.execute("SELECT file_id, data_json FROM file_store").fetchall()
                cached = [(r["file_id"], r["data_json"]) for r in rows]
                self._all_rows_cache = cached
                return list(cached)

        return self._run_with_retry("items", op)

    def _run_with_retry(self, op_name: str, fn: Callable[[], Any]) -> Any:
        last_exc: sqlite3.OperationalError | None = None
        for attempt in range(4):
            try:
                return fn()
            except sqlite3.OperationalError as exc:
                last_exc = exc
                message = str(exc).lower()
                if not any(token in message for token in _RETRYABLE_SQLITE_MESSAGES) or attempt == 3:
                    raise
                delay = 0.05 * (2**attempt)
                logger.warning(
                    "SQLite file_store %s failed for %s; retrying in %.2fs",
                    op_name,
                    self._path,
                    delay,
                )
                time.sleep(delay)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"file_store retry loop exited unexpectedly: {op_name}")

    def _init_db(self) -> None:
        def op() -> None:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA)
                conn.commit()
            finally:
                conn.close()

        self._run_with_retry("init", op)

    def get(self, file_id: str) -> dict | None:
        with self._lock:
            cached = self._item_cache.get(file_id)
            if cached is not None:
                return deepcopy(cached)

        def op():
            with self._lock:
                with self._connect() as conn:
                    return conn.execute(
                        "SELECT data_json FROM file_store WHERE file_id = ?", (file_id,)
                    ).fetchone()

        row = self._run_with_retry("get", op)
        if not row:
            return None
        data = json.loads(row["data_json"])
        with self._lock:
            self._item_cache[file_id] = deepcopy(data)
        return data

    def __contains__(self, file_id: str) -> bool:
        def op():
            with self._lock:
                with self._connect() as conn:
                    return conn.execute(
                        "SELECT 1 FROM file_store WHERE file_id = ? LIMIT 1", (file_id,)
                    ).fetchone()

        row = self._run_with_retry("contains", op)
        return row is not None

    def __getitem__(self, file_id: str) -> dict:
        val = self.get(file_id)
        if val is None:
            raise KeyError(file_id)
        return val

    def __setitem__(self, file_id: str, data: dict) -> None:
        self.set(file_id, data)

    def set(self, file_id: str, data: dict) -> None:
        jsonable_data = to_jsonable(data)
        data_json = json.dumps(jsonable_data, ensure_ascii=False, default=str)
        created = data.get("created_at", "")
        def op() -> None:
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
                self._invalidate_read_cache(file_id)
                self._item_cache[file_id] = deepcopy(jsonable_data)

        self._run_with_retry("set", op)

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
        def op() -> None:
            with self._lock:
                with self._connect() as conn:
                    conn.execute("DELETE FROM file_store WHERE file_id = ?", (file_id,))
                    conn.commit()
                self._invalidate_read_cache(file_id)

        self._run_with_retry("pop", op)
        return val

    def __delitem__(self, file_id: str) -> None:
        self.pop(file_id)

    def values(self) -> list[dict]:
        rows = self._cached_all_rows()
        return [json.loads(data_json) for _file_id, data_json in rows]

    def items(self) -> list[tuple[str, dict]]:
        rows = self._cached_all_rows()
        return [(file_id, json.loads(data_json)) for file_id, data_json in rows]

    def keys(self) -> list[str]:
        rows = self._cached_all_rows()
        return [file_id for file_id, _data_json in rows]

    def __len__(self) -> int:
        def op():
            with self._lock:
                with self._connect() as conn:
                    return conn.execute("SELECT COUNT(*) AS c FROM file_store").fetchone()

        row = self._run_with_retry("len", op)
        return row["c"]

    def clear(self) -> None:
        """Remove all entries."""
        def op() -> None:
            with self._lock:
                with self._connect() as conn:
                    conn.execute("DELETE FROM file_store")
                    conn.commit()
                self._invalidate_read_cache()

        self._run_with_retry("clear", op)

    def update(self, data: dict[str, dict]) -> None:
        """Bulk insert/replace entries (dict-compatible)."""
        def op() -> None:
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
                self._invalidate_read_cache()

        self._run_with_retry("update", op)

    def __iter__(self) -> Iterator[str]:
        """Iterate over file IDs (enables dict(store) compatibility)."""
        return iter(self.keys())

    def migrate_from_json(self, json_path: str) -> int:
        """从旧 JSON file_store 迁移数据到 SQLite。返回迁移条数。"""
        if not os.path.exists(json_path):
            return 0
        try:
            with open(json_path, encoding="utf-8") as f:
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
