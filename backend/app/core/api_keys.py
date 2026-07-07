# Copyright 2026 DataInfra-RedactionEverything Contributors
"""API 密钥（R1-5）：机器对接（M2M）认证。

密钥形如 ``rk_<32位随机>``，只在创建时明文返回一次，存储只留 SHA-256 哈希。
scope=readonly/readwrite；subject=``service:<name>`` 走既有审计与租户隔离。
默认零密钥 = 行为不变。存储在 DATA_DIR/api_keys.json（原子替换，单 worker）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_SCOPES = ("readonly", "readwrite")


def _store_path() -> str:
    return os.path.join(settings.DATA_DIR, "api_keys.json")


def _load() -> dict[str, Any]:
    path = _store_path()
    if not os.path.exists(path):
        return {"keys": {}}
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {"keys": {}}
    except (OSError, json.JSONDecodeError):
        logger.exception("api_keys.json unreadable")
        return {"keys": {}}


def _save(doc: dict[str, Any]) -> None:
    path = _store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_api_key(
    name: str, *, scope: str = "readonly", expires_at: str | None = None, created_by: str = ""
) -> dict[str, Any]:
    """创建密钥。返回含明文 key 的记录——明文仅此一次。"""
    clean_name = (name or "").strip()
    if not clean_name or len(clean_name) > 64:
        raise HTTPException(status_code=400, detail="密钥名称须为 1-64 字符")
    if scope not in _SCOPES:
        raise HTTPException(status_code=400, detail=f"scope 须为 {'/'.join(_SCOPES)}")
    if expires_at:
        try:
            datetime.fromisoformat(expires_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="expires_at 须为 ISO 日期")
    raw = f"rk_{secrets.token_urlsafe(32)}"
    with _lock:
        doc = _load()
        keys = doc.setdefault("keys", {})
        if any(k.get("name") == clean_name and not k.get("revoked_at") for k in keys.values()):
            raise HTTPException(status_code=409, detail="同名密钥已存在")
        key_id = secrets.token_hex(8)
        keys[key_id] = {
            "name": clean_name,
            "key_hash": _hash_key(raw),
            "scope": scope,
            "expires_at": expires_at,
            "created_at": datetime.now(UTC).isoformat(),
            "created_by": created_by,
            "last_used_at": None,
            "revoked_at": None,
        }
        _save(doc)
    return {"key_id": key_id, "name": clean_name, "scope": scope, "api_key": raw}


def revoke_api_key(key_id: str) -> bool:
    with _lock:
        doc = _load()
        record = doc.get("keys", {}).get(key_id)
        if not isinstance(record, dict) or record.get("revoked_at"):
            return False
        record["revoked_at"] = datetime.now(UTC).isoformat()
        _save(doc)
        return True


def list_api_keys() -> list[dict[str, Any]]:
    doc = _load()
    out = []
    for key_id, record in sorted(doc.get("keys", {}).items()):
        if not isinstance(record, dict):
            continue
        out.append({
            "key_id": key_id,
            "name": record.get("name"),
            "scope": record.get("scope"),
            "expires_at": record.get("expires_at"),
            "created_at": record.get("created_at"),
            "last_used_at": record.get("last_used_at"),
            "revoked": bool(record.get("revoked_at")),
        })
    return out


def verify_api_key(raw: str | None) -> dict[str, Any] | None:
    """校验 X-API-Key。通过返回 {subject, scope}；无效/过期/吊销返回 None。"""
    if not raw or not raw.startswith("rk_"):
        return None
    hashed = _hash_key(raw)
    with _lock:
        doc = _load()
        for record in doc.get("keys", {}).values():
            if not isinstance(record, dict) or record.get("key_hash") != hashed:
                continue
            if record.get("revoked_at"):
                return None
            expires = record.get("expires_at")
            if expires:
                try:
                    if datetime.fromisoformat(expires).replace(tzinfo=UTC) < datetime.now(UTC):
                        return None
                except ValueError:
                    return None
            record["last_used_at"] = datetime.now(UTC).isoformat()
            _save(doc)
            return {
                "subject": f"service:{record.get('name')}",
                "scope": str(record.get("scope") or "readonly"),
            }
    return None
