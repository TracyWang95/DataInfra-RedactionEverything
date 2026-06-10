"""Helpers for user-scoped runtime configuration stores."""

from __future__ import annotations

import os
import re
import shutil
import threading

from app.core.config import settings

_SAFE_OWNER_RE = re.compile(r"[^A-Za-z0-9_.@-]+")

# Per-store-path locks: serialize load-modify-save sequences on JSON stores.
# Writes themselves are already atomic (os.replace); this prevents lost
# updates when two requests mutate the same store concurrently.
_store_locks: dict[str, threading.Lock] = {}
_store_locks_guard = threading.Lock()


def store_lock(path: str) -> threading.Lock:
    """Return the process-wide lock guarding one JSON store file."""
    key = os.path.normcase(os.path.abspath(path))
    with _store_locks_guard:
        lock = _store_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _store_locks[key] = lock
        return lock


def normalize_owner_id(owner_id: str | None) -> str | None:
    raw = str(owner_id or "").strip().lower()
    if not raw:
        return None
    safe = _SAFE_OWNER_RE.sub("_", raw).strip("._-")
    return safe or None


def _tenants_base_dir() -> str:
    return os.path.realpath(os.path.join(settings.DATA_DIR, "tenants"))


def _contained_tenant_path(*parts: str) -> str:
    """Join path parts under the tenants base and reject any escape.

    normalize_owner_id() already strips path separators, but the explicit
    containment check is the actual security boundary: any resolved path that
    leaves the tenants directory is rejected regardless of how it was built.
    """
    base = _tenants_base_dir()
    candidate = os.path.realpath(os.path.join(base, *parts))
    if candidate != base and not candidate.startswith(base + os.sep):
        raise ValueError("tenant path escapes the tenants directory")
    return candidate


def tenant_dir(owner_id: str) -> str:
    owner = normalize_owner_id(owner_id)
    if not owner:
        raise ValueError("owner_id is required for tenant-scoped config")
    return _contained_tenant_path(owner)


def tenant_store_path(owner_id: str | None, legacy_path: str, filename: str) -> str:
    """Return the runtime config path for an owner, preserving legacy global mode.

    Existing installs stored config globally. To avoid losing that admin-facing
    configuration, the first admin access seeds its tenant store from the legacy
    file when the tenant file does not yet exist.
    """
    owner = normalize_owner_id(owner_id)
    if not owner:
        return legacy_path

    path = _contained_tenant_path(owner, filename)
    if owner == "admin" and legacy_path and os.path.exists(legacy_path) and not os.path.exists(path):
        with store_lock(path):
            if not os.path.exists(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                shutil.copyfile(legacy_path, path)
    return path
