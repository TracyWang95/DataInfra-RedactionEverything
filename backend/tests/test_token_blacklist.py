"""Tests for app.core.token_blacklist -- SQLite-backed JWT revocation list."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.core.token_blacklist import TokenBlacklist


@pytest.fixture
def blacklist(tmp_path: Path) -> TokenBlacklist:
    return TokenBlacklist(str(tmp_path / "blacklist.sqlite3"))


def test_revoke_and_check(blacklist: TokenBlacklist) -> None:
    jti = "tok-abc-123"
    exp = int(time.time()) + 3600
    blacklist.revoke(jti, exp)
    assert blacklist.is_revoked(jti) is True


def test_not_revoked(blacklist: TokenBlacklist) -> None:
    assert blacklist.is_revoked("random-jti-never-added") is False


def test_cleanup_expired(blacklist: TokenBlacklist) -> None:
    jti_alive = "alive-tok"
    jti_expired = "expired-tok"

    # Insert a non-expired token first (also triggers initial cleanup on empty db)
    blacklist.revoke(jti_alive, int(time.time()) + 3600)

    # Now insert an expired token. _maybe_cleanup won't fire again within the
    # cleanup interval, so the expired entry stays in the table.
    blacklist.revoke(jti_expired, int(time.time()) - 10)
    assert blacklist.is_revoked(jti_expired) is True

    # Explicitly clean up expired entries
    removed = blacklist.cleanup_expired()
    assert removed >= 1
    assert blacklist.is_revoked(jti_expired) is False
    # The alive token should still be present
    assert blacklist.is_revoked(jti_alive) is True
