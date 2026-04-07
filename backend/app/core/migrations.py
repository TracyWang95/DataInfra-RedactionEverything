# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
Simple version-tracked database migration system.

Uses a ``_meta`` table with a single ``schema_version`` integer.
Each migration is a function ``migrate_v<N>(conn)`` that is executed
inside a transaction.  ``run_migrations(db_path)`` should be called
once at application startup, before any other database access.
"""
from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Meta table helpers
# ---------------------------------------------------------------------------

_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS _meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _get_version(conn: sqlite3.Connection) -> int:
    conn.executescript(_META_SCHEMA)
    row = conn.execute(
        "SELECT value FROM _meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return 0
    return int(row[0])


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO _meta (key, value) VALUES ('schema_version', ?)",
        (str(version),),
    )


# ---------------------------------------------------------------------------
# Migration functions
# ---------------------------------------------------------------------------

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def migrate_v1(conn: sqlite3.Connection) -> None:
    """Port inline ALTER TABLE logic from job_store._init_db().

    - Add ``review_draft_json`` and ``review_draft_updated_at`` columns to
      ``job_items`` (if missing).
    - Add ``priority`` column to ``jobs`` (if missing).
    - Rebuild ``jobs`` table so the CHECK constraint includes ``smart_batch``.

    On a fresh database the tables may not exist yet (they are created by
    JobStore._init_db which runs later).  In that case this migration is a
    no-op — the CREATE TABLE DDL already includes all required columns.
    """
    # On a fresh DB the tables don't exist yet — nothing to migrate.
    if not _table_exists(conn, "jobs") or not _table_exists(conn, "job_items"):
        logger.info("migrate_v1: tables not yet created — skipping (fresh database)")
        return

    # --- job_items columns ---------------------------------------------------
    cols = {
        str(r[1])
        for r in conn.execute("PRAGMA table_info(job_items)").fetchall()
    }
    if "review_draft_json" not in cols:
        conn.execute("ALTER TABLE job_items ADD COLUMN review_draft_json TEXT")
    if "review_draft_updated_at" not in cols:
        conn.execute("ALTER TABLE job_items ADD COLUMN review_draft_updated_at TEXT")

    # --- jobs.priority -------------------------------------------------------
    job_cols = {
        str(r[1])
        for r in conn.execute("PRAGMA table_info(jobs)").fetchall()
    }
    if "priority" not in job_cols:
        conn.execute(
            "ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
        )

    # --- Rebuild jobs table for CHECK constraint including smart_batch --------
    needs_rebuild = False
    try:
        conn.execute(
            "INSERT INTO jobs (id, job_type, status, created_at, updated_at) "
            "VALUES ('__test_smart', 'smart_batch', 'draft', '', '')"
        )
        conn.execute("DELETE FROM jobs WHERE id = '__test_smart'")
    except sqlite3.IntegrityError:
        needs_rebuild = True

    if needs_rebuild:
        conn.execute("ALTER TABLE jobs RENAME TO jobs_old")
        conn.execute("""
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL CHECK(job_type IN ('text_batch','image_batch','smart_batch')),
                title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                skip_item_review INTEGER NOT NULL DEFAULT 0,
                config_json TEXT NOT NULL DEFAULT '{}',
                priority INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO jobs (id, job_type, title, status, skip_item_review,
                             config_json, priority, error_message, created_at, updated_at)
            SELECT id, job_type, title, status, skip_item_review,
                   config_json, COALESCE(priority, 0), error_message, created_at, updated_at
            FROM jobs_old
        """)
        conn.execute("DROP TABLE jobs_old")

    # Recreate indexes that may have been dropped during the rebuild
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_items_job ON job_items(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_items_status ON job_items(status)")


# ---------------------------------------------------------------------------
# Migration registry — append new migrations here in order.
# ---------------------------------------------------------------------------

_MIGRATIONS: list[tuple[int, callable]] = [
    (1, migrate_v1),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_migrations(db_path: str) -> None:
    """Execute all pending migrations against *db_path*.

    Safe to call on every startup — already-applied migrations are skipped.
    Each migration runs inside its own transaction.
    """
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout = 5000")

    try:
        current = _get_version(conn)
        pending = [(v, fn) for v, fn in _MIGRATIONS if v > current]

        if not pending:
            logger.debug("Database at schema version %d — no migrations needed", current)
            return

        for version, fn in pending:
            logger.info("Running migration v%d …", version)
            conn.execute("BEGIN IMMEDIATE")
            try:
                fn(conn)
                _set_version(conn, version)
                conn.execute("COMMIT")
                logger.info("Migration v%d complete", version)
            except Exception:
                conn.execute("ROLLBACK")
                logger.exception("Migration v%d FAILED — rolled back", version)
                raise

        logger.info(
            "All migrations applied (v%d → v%d)",
            current,
            _get_version(conn),
        )
    finally:
        conn.close()
