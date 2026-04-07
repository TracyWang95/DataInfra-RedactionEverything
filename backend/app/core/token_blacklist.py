# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""JWT token blacklist -- simple SQLite-backed revocation list."""
import logging
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS blacklisted_tokens (
    jti        TEXT    PRIMARY KEY,
    exp        INTEGER NOT NULL,
    created_at INTEGER NOT NULL
)
"""

_CLEANUP_INTERVAL_SEC = 600  # 10 minutes


class TokenBlacklist:
    """Thread-safe, SQLite-backed JWT revocation list.

    Expired entries are cleaned up periodically so the database stays small.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._last_cleanup = 0.0
        # Initialise schema
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE_SQL)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _maybe_cleanup(self) -> None:
        now = time.time()
        if now - self._last_cleanup < _CLEANUP_INTERVAL_SEC:
            return
        self._last_cleanup = now
        try:
            self.cleanup_expired()
        except Exception:
            logger.exception("token blacklist cleanup failed")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def revoke(self, jti: str, exp: int) -> None:
        """Add a token (by its JTI) to the blacklist."""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO blacklisted_tokens (jti, exp, created_at) VALUES (?, ?, ?)",
                    (jti, exp, int(time.time())),
                )
            self._maybe_cleanup()

    def is_revoked(self, jti: str) -> bool:
        """Return True if the token JTI has been revoked."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM blacklisted_tokens WHERE jti = ?", (jti,)
                ).fetchone()
            self._maybe_cleanup()
            return row is not None

    def cleanup_expired(self) -> int:
        """Remove entries whose ``exp`` is in the past. Returns count removed."""
        now = int(time.time())
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM blacklisted_tokens WHERE exp < ?", (now,)
            )
            removed = cursor.rowcount
        if removed:
            logger.debug("token blacklist: cleaned up %d expired entries", removed)
        return removed


# ---------------------------------------------------------------------------
# Module-level singleton (lazily initialised)
# ---------------------------------------------------------------------------

_instance: TokenBlacklist | None = None
_init_lock = threading.Lock()


def get_blacklist() -> TokenBlacklist:
    """Return the global ``TokenBlacklist`` singleton."""
    global _instance
    if _instance is None:
        with _init_lock:
            if _instance is None:
                from app.core.config import settings
                import os

                db_path = os.path.join(settings.DATA_DIR, "token_blacklist.sqlite3")
                os.makedirs(settings.DATA_DIR, exist_ok=True)
                _instance = TokenBlacklist(db_path)
    return _instance
