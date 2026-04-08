# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Shared SQLite connection helpers — deduplicate boilerplate across stores."""

import os
import sqlite3
import threading

_thread_local = threading.local()


def ensure_db_dir(db_path: str) -> None:
    """Create the parent directory for a database file if it doesn't exist."""
    d = os.path.dirname(db_path)
    if d:
        os.makedirs(d, exist_ok=True)


def connect_sqlite(
    db_path: str,
    *,
    row_factory: bool = True,
    timeout: float = 10.0,
    busy_timeout_ms: int = 5000,
    wal: bool = True,
) -> sqlite3.Connection:
    """Create a new SQLite connection with standard production pragmas.

    Parameters
    ----------
    db_path : path to the ``.db`` file
    row_factory : if *True*, set ``sqlite3.Row`` as the row factory
    timeout : connection-level lock wait (seconds)
    busy_timeout_ms : PRAGMA busy_timeout value (milliseconds)
    wal : if *True*, enable WAL journal mode
    """
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=timeout)
    if row_factory:
        conn.row_factory = sqlite3.Row
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    # SQLite PRAGMA statements do not support parameterized binding (?),
    # so we validate the value is an integer to prevent injection.
    busy_timeout_ms = int(busy_timeout_ms)
    if not (0 <= busy_timeout_ms <= 600_000):
        raise ValueError(f"busy_timeout_ms must be 0–600 000, got {busy_timeout_ms}")
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    return conn


def get_thread_local_connection(
    db_path: str,
    pool_key: str,
    **kwargs,
) -> sqlite3.Connection:
    """Return a thread-local cached connection, reconnecting if stale.

    Uses :func:`connect_sqlite` for initial creation.
    """
    conn: sqlite3.Connection | None = getattr(_thread_local, pool_key, None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except sqlite3.ProgrammingError:
            pass  # connection closed — fall through to create new
    conn = connect_sqlite(db_path, **kwargs)
    setattr(_thread_local, pool_key, conn)
    return conn
