"""Audit log query API (Phase 1b) — who did what, when.

Reads the JSONL written by app.core.audit. Query is tail-oriented: only the
last few MB are scanned so the endpoint stays fast even after months of
entries; enterprises wanting full retention export the file itself.
"""
from __future__ import annotations

import csv
import io
import json
import os

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.auth import require_super_admin
from app.core.config import settings

router = APIRouter(prefix="/audit", tags=["audit"])

_TAIL_BYTES = 5 * 1024 * 1024
_MAX_LIMIT = 1000
_EXPORT_MAX_ROWS = 50_000


def _audit_log_path() -> str:
    return os.path.join(settings.DATA_DIR, "audit", "audit.log")


def _read_entries(
    *,
    user: str | None,
    action: str | None,
    resource_type: str | None,
    q: str | None,
    max_rows: int,
) -> list[dict]:
    path = _audit_log_path()
    if not os.path.exists(path):
        return []
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        if size > _TAIL_BYTES:
            fh.seek(size - _TAIL_BYTES)
            fh.readline()  # drop the partial first line
        raw = fh.read().decode("utf-8", "replace")

    entries: list[dict] = []
    # newest first
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if user and str(entry.get("user", "")).lower() != user.lower():
            continue
        if action and str(entry.get("action", "")).lower() != action.lower():
            continue
        if resource_type and str(entry.get("resource_type", "")).lower() != resource_type.lower():
            continue
        if q:
            haystack = json.dumps(entry, ensure_ascii=False).lower()
            if q.lower() not in haystack:
                continue
        entries.append(entry)
        if len(entries) >= max_rows:
            break
    return entries


@router.get("/logs", response_model=dict)
async def query_audit_logs(
    user: str | None = Query(None),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(200, ge=1, le=_MAX_LIMIT),
    _: str = Depends(require_super_admin),
) -> dict:
    entries = _read_entries(
        user=user, action=action, resource_type=resource_type, q=q, max_rows=limit
    )
    return {"entries": entries, "count": len(entries), "tail_bytes": _TAIL_BYTES}


@router.get("/logs/export")
async def export_audit_logs(
    user: str | None = Query(None),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    _: str = Depends(require_super_admin),
):
    entries = _read_entries(
        user=user, action=action, resource_type=resource_type, q=q, max_rows=_EXPORT_MAX_ROWS
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["timestamp", "user", "action", "resource_type", "resource_id", "detail"])
    for entry in entries:
        writer.writerow(
            [
                entry.get("timestamp", ""),
                entry.get("user", ""),
                entry.get("action", ""),
                entry.get("resource_type", ""),
                entry.get("resource_id", ""),
                json.dumps(entry.get("detail") or {}, ensure_ascii=False),
            ]
        )
    # utf-8-sig so Excel opens Chinese content directly
    data = ("﻿" + buffer.getvalue()).encode("utf-8")
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-logs.csv"'},
    )
