# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Shared SQLite connection helpers."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading

_thread_local = threading.local()
logger = logging.getLogger(__name__)
_wsl_drvfs_wal_disabled_log_lock = threading.Lock()
_wsl_drvfs_wal_disabled_logged_paths: set[str] = set()
_sqlite_journal_fallback_log_lock = threading.Lock()
_sqlite_journal_fallback_logged_paths: set[str] = set()


def ensure_db_dir(db_path: str) -> None:
    """Create the parent directory for a database file if it does not exist."""
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def ensure_wal_sidecars(db_path: str) -> None:
    """Best-effort recovery for Windows/WSL drvfs WAL sidecar creation."""
    ensure_db_dir(db_path)
    for suffix in ("-wal", "-shm"):
        sidecar = db_path + suffix
        try:
            with open(sidecar, "a", encoding="utf-8"):
                pass
        except OSError as exc:
            logger.debug("Unable to pre-create sqlite WAL sidecar %s: %s", sidecar, exc)


def _is_wsl_drvfs_path(db_path: str) -> bool:
    """Return true for Windows drives mounted through WSL drvfs (/mnt/c, /mnt/d)."""
    if os.name != "posix" or "microsoft" not in os.uname().release.lower():
        return False
    real = os.path.realpath(db_path)
    parts = real.replace("\\", "/").split("/")
    return len(parts) > 3 and parts[1] == "mnt" and len(parts[2]) == 1


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _log_wsl_drvfs_wal_disabled_once(db_path: str) -> None:
    log_key = os.path.realpath(db_path).replace("\\", "/")
    with _wsl_drvfs_wal_disabled_log_lock:
        if log_key in _wsl_drvfs_wal_disabled_logged_paths:
            return
        _wsl_drvfs_wal_disabled_logged_paths.add(log_key)
    logger.info(
        "SQLite WAL disabled by default for WSL drvfs database %s; set DATAINFRA_SQLITE_WAL_ON_DRVFS=1 to override",
        db_path,
    )


def _log_sqlite_journal_fallback_once(db_path: str, mode: str, exc: BaseException) -> None:
    normalized_db_path = os.path.realpath(db_path).replace("\\", "/")
    log_key = f"{mode}:{normalized_db_path}"
    with _sqlite_journal_fallback_log_lock:
        if log_key in _sqlite_journal_fallback_logged_paths:
            return
        _sqlite_journal_fallback_logged_paths.add(log_key)
    logger.info(
        "SQLite %s journal fallback unavailable for %s; continuing with current journal mode (%s)",
        mode,
        db_path,
        exc,
    )


def connect_sqlite(
    db_path: str,
    *,
    row_factory: bool = True,
    timeout: float = 10.0,
    busy_timeout_ms: int = 5000,
    wal: bool = True,
) -> sqlite3.Connection:
    """Create a SQLite connection with standard production pragmas.

    The WAL setup includes a Windows/WSL recovery path: if SQLite can open the
    database but cannot create the ``-wal``/``-shm`` files, pre-create those
    sidecars and retry. If WAL still cannot be enabled, keep the connection in
    SQLite's default journal mode instead of failing uploads/jobs/auth flows.
    """
    ensure_db_dir(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=timeout)
    if row_factory:
        conn.row_factory = sqlite3.Row

    busy_timeout_ms = int(busy_timeout_ms)
    if not (0 <= busy_timeout_ms <= 600_000):
        raise ValueError(f"busy_timeout_ms must be 0-600000, got {busy_timeout_ms}")
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")

    use_wal = wal
    if wal and _is_wsl_drvfs_path(db_path) and not _env_flag("DATAINFRA_SQLITE_WAL_ON_DRVFS"):
        use_wal = False
        _log_wsl_drvfs_wal_disabled_once(db_path)

    if use_wal:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            if "unable to open database file" not in str(exc).lower():
                conn.close()
                raise
            ensure_wal_sidecars(db_path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                logger.warning(
                    "SQLite WAL unavailable for %s; continuing with default journal mode",
                    db_path,
                    exc_info=True,
                )
    elif wal:
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.OperationalError as exc:
            _log_sqlite_journal_fallback_once(db_path, "DELETE", exc)
    return conn


def get_thread_local_connection(
    db_path: str,
    pool_key: str,
    **kwargs,
) -> sqlite3.Connection:
    """Return a thread-local cached connection, reconnecting if stale."""
    conn: sqlite3.Connection | None = getattr(_thread_local, pool_key, None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except sqlite3.ProgrammingError:
            pass
    conn = connect_sqlite(db_path, **kwargs)
    setattr(_thread_local, pool_key, conn)
    return conn
