"""R1-5 API 密钥：scope 强制/过期/吊销/哈希存储。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core import api_keys
from app.core.config import settings


@pytest.fixture
def keys_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    return tmp_path


def test_create_verify_roundtrip_and_plaintext_never_stored(keys_env, tmp_path):
    created = api_keys.create_api_key("etl-job", scope="readwrite", created_by="boss")
    raw = created["api_key"]
    assert raw.startswith("rk_")
    stored = (tmp_path / "api_keys.json").read_text(encoding="utf-8")
    assert raw not in stored, "plaintext key must never be persisted"
    identity = api_keys.verify_api_key(raw)
    assert identity == {"subject": "service:etl-job", "scope": "readwrite"}
    # last_used_at 更新
    listed = api_keys.list_api_keys()
    assert listed[0]["last_used_at"]


def test_revoked_and_expired_keys_rejected(keys_env):
    created = api_keys.create_api_key("temp", scope="readonly")
    assert api_keys.verify_api_key(created["api_key"]) is not None
    assert api_keys.revoke_api_key(created["key_id"]) is True
    assert api_keys.verify_api_key(created["api_key"]) is None
    # 过期
    expired = api_keys.create_api_key(
        "old", scope="readonly",
        expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
    )
    assert api_keys.verify_api_key(expired["api_key"]) is None


def test_invalid_inputs_rejected(keys_env):
    with pytest.raises(HTTPException):
        api_keys.create_api_key("", scope="readonly")
    with pytest.raises(HTTPException):
        api_keys.create_api_key("x", scope="admin")
    api_keys.create_api_key("dup", scope="readonly")
    with pytest.raises(HTTPException):
        api_keys.create_api_key("dup", scope="readonly")
    assert api_keys.verify_api_key("rk_nonexistent") is None
    assert api_keys.verify_api_key("Bearer abc") is None
    assert api_keys.verify_api_key(None) is None


def test_readonly_scope_blocks_mutation(keys_env, monkeypatch):
    """require_auth 层：readonly 密钥的非安全方法被 403。"""
    import asyncio

    from app.core.auth import require_auth

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    created = api_keys.create_api_key("reader", scope="readonly")

    class FakeRequest:
        def __init__(self, method):
            self.method = method
            self.headers = {"x-api-key": created["api_key"]}
            self.cookies = {}

    async def flow():
        subject = await require_auth(FakeRequest("GET"), None)
        assert subject == "service:reader"
        with pytest.raises(HTTPException) as exc:
            await require_auth(FakeRequest("POST"), None)
        assert exc.value.status_code == 403

    asyncio.run(flow())
