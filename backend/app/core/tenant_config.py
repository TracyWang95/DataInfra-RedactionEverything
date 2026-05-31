"""Helpers for user-scoped runtime configuration stores."""

from __future__ import annotations

import os
import re
import shutil

from app.core.config import settings

_SAFE_OWNER_RE = re.compile(r"[^A-Za-z0-9_.@-]+")


def normalize_owner_id(owner_id: str | None) -> str | None:
    raw = str(owner_id or "").strip().lower()
    if not raw:
        return None
    safe = _SAFE_OWNER_RE.sub("_", raw).strip("._-")
    return safe or None


def tenant_dir(owner_id: str) -> str:
    owner = normalize_owner_id(owner_id)
    if not owner:
        raise ValueError("owner_id is required for tenant-scoped config")
    return os.path.join(settings.DATA_DIR, "tenants", owner)


def tenant_store_path(owner_id: str | None, legacy_path: str, filename: str) -> str:
    """Return the runtime config path for an owner, preserving legacy global mode.

    Existing installs stored config globally. To avoid losing that admin-facing
    configuration, the first admin access seeds its tenant store from the legacy
    file when the tenant file does not yet exist.
    """
    owner = normalize_owner_id(owner_id)
    if not owner:
        return legacy_path

    path = os.path.join(tenant_dir(owner), filename)
    if owner == "admin" and legacy_path and os.path.exists(legacy_path) and not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(legacy_path, path)
    return path
