"""Offline license API (W2) — status is public, upload is super-admin only.

GET  /license/status  license state + seat usage (no auth: the login screen
                      and monitoring need it before a token exists)
POST /license/upload  install a vendor-signed license.json; the signature is
                      verified BEFORE anything touches the license path, and
                      the write is atomic (tmp + rename).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile

from fastapi import APIRouter, Body, Depends, HTTPException

from app.core.auth import list_users, require_super_admin
from app.core.license import (
    STATE_EXPIRING_SOON,
    STATE_VALID,
    get_license_state,
    invalidate_license_cache,
    license_file_path,
    verify_license_document,
)

router = APIRouter(prefix="/license", tags=["license"])

logger = logging.getLogger(__name__)


@router.get("/status", response_model=dict)
async def license_status() -> dict:
    state = get_license_state()
    try:
        seats_used = len(list_users())
    except HTTPException:
        seats_used = None
    return {
        "state": state.state,
        "reason": state.reason,
        "customer": state.customer,
        "edition": state.edition,
        "expires_at": state.expires_at or None,
        "days_left": state.days_left,
        "max_users": state.max_users,
        "seats_used": seats_used,
        "features": state.features,
    }


@router.post("/upload", response_model=dict)
async def upload_license(
    document: dict = Body(...),
    _: str = Depends(require_super_admin),
) -> dict:
    # Verify BEFORE writing: an already-expired or unverifiable license must
    # never replace the installed one.
    state = verify_license_document(document)
    if state.state not in (STATE_VALID, STATE_EXPIRING_SOON):
        raise HTTPException(status_code=400, detail=f"License 无效，已拒绝安装：{state.reason or state.state}")

    path = license_file_path()
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f"{os.path.basename(path)}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    invalidate_license_cache()
    fresh = get_license_state()
    logger.info(
        "License installed: state=%s customer=%s expires=%s", fresh.state, fresh.customer, fresh.expires_at
    )
    return {
        "state": fresh.state,
        "customer": fresh.customer,
        "edition": fresh.edition,
        "expires_at": fresh.expires_at or None,
        "days_left": fresh.days_left,
        "max_users": fresh.max_users,
    }
