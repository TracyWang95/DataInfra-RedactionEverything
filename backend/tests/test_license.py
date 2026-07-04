"""W2 离线 License：Ed25519 校验状态机 + 中间件 403 + 席位闸 + 上传/续期。

表驱动覆盖：valid / expiring_soon 边界 / grace_readonly / blocked / invalid
（缺失、篡改、错误密钥、坏 schema、坏 JSON）/ 默认关闭 = unlicensed 零行为变化。
"""
from __future__ import annotations

import base64
import json
import os
from datetime import date, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core import auth
from app.core import license as license_mod
from app.core import license_pubkey
from app.core.config import settings
from app.core.license import canonical_payload_bytes
from app.main import app

client = TestClient(app)

# CSRF middleware skips Bearer-token requests; a bogus token is enough to reach
# the license middleware (which runs before endpoint auth).
_BOGUS_BEARER = {"Authorization": "Bearer not-a-real-token"}


def _pub_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()


def _make_doc(
    key: Ed25519PrivateKey,
    *,
    expires: date,
    max_users: int = 5,
    industries: tuple[str, ...] = ("legal",),
    tamper: bool = False,
    **overrides,
) -> dict:
    payload = {
        "schema": 1,
        "license_id": "lic-test-001",
        "customer": "测试客户",
        "issued_at": "2026-01-01",
        "expires_at": expires.isoformat(),
        "max_users": max_users,
        "edition": "enterprise",
        "features": {"industries": list(industries)},
    }
    payload.update(overrides)
    signature = base64.b64encode(key.sign(canonical_payload_bytes(payload))).decode("ascii")
    if tamper:
        payload["max_users"] = 999  # mutate AFTER signing
    return {"payload": payload, "signature": signature}


class _Env:
    def __init__(self, key: Ed25519PrivateKey, path):
        self.key = key
        self.path = path

    def write(self, doc: dict) -> None:
        self.path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def write_license(self, **kwargs) -> dict:
        doc = _make_doc(self.key, **kwargs)
        self.write(doc)
        return doc


@pytest.fixture()
def lic(monkeypatch, tmp_path) -> _Env:
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(license_pubkey, "PUBLIC_KEY_HEX", _pub_hex(key))
    monkeypatch.setattr(settings, "LICENSE_ENFORCEMENT_ENABLED", True)
    monkeypatch.setattr(settings, "LICENSE_FILE_PATH", str(tmp_path / "license.json"))
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "_AUTH_FILE", str(tmp_path / "auth.json"))
    license_mod.invalidate_license_cache()
    yield _Env(key, tmp_path / "license.json")
    license_mod.invalidate_license_cache()


def _admin_headers() -> dict[str, str]:
    auth.create_user("boss", "Passw0rd!", role="super_admin")
    return {"Authorization": f"Bearer {auth.create_token('boss')}"}


# ---------------------------------------------------------------------------
# 状态机（表驱动）
# ---------------------------------------------------------------------------

_STATE_MATRIX = [
    # (offset_kind, expected state)
    ("far_future", license_mod.STATE_VALID),
    ("warn_plus_one", license_mod.STATE_VALID),
    ("warn_boundary", license_mod.STATE_EXPIRING_SOON),
    ("today", license_mod.STATE_EXPIRING_SOON),
    ("yesterday", license_mod.STATE_GRACE_READONLY),
    ("grace_boundary", license_mod.STATE_GRACE_READONLY),
    ("beyond_grace", license_mod.STATE_BLOCKED),
]


def _offset_days(kind: str) -> int:
    warn = settings.LICENSE_EXPIRY_WARN_DAYS
    grace = settings.LICENSE_GRACE_DAYS
    return {
        "far_future": 200,
        "warn_plus_one": warn + 1,
        "warn_boundary": warn,
        "today": 0,
        "yesterday": -1,
        "grace_boundary": -grace,
        "beyond_grace": -(grace + 1),
    }[kind]


@pytest.mark.parametrize("offset_kind,expected", _STATE_MATRIX)
def test_state_matrix(lic, offset_kind, expected):
    lic.write_license(expires=date.today() + timedelta(days=_offset_days(offset_kind)))
    state = license_mod.get_license_state()
    assert state.state == expected, f"{offset_kind}: {state.state} ({state.reason})"


def test_valid_license_parses_fields_and_feature_flags(lic):
    lic.write_license(expires=date.today() + timedelta(days=365), industries=("legal", "medical"))
    state = license_mod.get_license_state()
    assert state.state == license_mod.STATE_VALID
    assert state.customer == "测试客户"
    assert state.edition == "enterprise"
    assert state.max_users == 5
    assert state.features == {"industries": ["legal", "medical"]}
    assert license_mod.license_feature_enabled("legal") is True
    assert license_mod.license_feature_enabled("finance") is False


_INVALID_CASES = [
    ("missing_file", None),
    ("malformed_json", "not-json{{{"),
    ("not_an_object", "[1,2,3]"),
    ("missing_signature", '{"payload": {"schema": 1}}'),
]


@pytest.mark.parametrize("kind,content", _INVALID_CASES)
def test_invalid_inputs_do_not_crash(lic, kind, content):
    if content is not None:
        lic.path.write_text(content, encoding="utf-8")
    state = license_mod.get_license_state()
    assert state.state == license_mod.STATE_INVALID
    assert state.reason


def test_tampered_payload_is_invalid(lic):
    lic.write(_make_doc(lic.key, expires=date.today() + timedelta(days=365), tamper=True))
    assert license_mod.get_license_state().state == license_mod.STATE_INVALID


def test_wrong_signing_key_is_invalid(lic):
    other_key = Ed25519PrivateKey.generate()
    lic.write(_make_doc(other_key, expires=date.today() + timedelta(days=365)))
    assert license_mod.get_license_state().state == license_mod.STATE_INVALID


def test_bad_schema_is_invalid(lic):
    lic.write_license(expires=date.today() + timedelta(days=365), schema=2)
    assert license_mod.get_license_state().state == license_mod.STATE_INVALID


def test_renewal_file_swap_picked_up_via_mtime(lic):
    lic.write_license(expires=date.today() - timedelta(days=1))
    assert license_mod.get_license_state().state == license_mod.STATE_GRACE_READONLY

    lic.write_license(expires=date.today() + timedelta(days=365))
    # NTFS mtime 粒度可能不足以区分两次快速写入；显式推后 2 秒
    bumped = os.path.getmtime(lic.path) + 2
    os.utime(lic.path, (bumped, bumped))
    assert license_mod.get_license_state().state == license_mod.STATE_VALID


# ---------------------------------------------------------------------------
# 默认关闭 = 零行为变化（回归保护）
# ---------------------------------------------------------------------------

def test_enforcement_off_is_unlicensed_and_everything_passes(lic, monkeypatch):
    monkeypatch.setattr(settings, "LICENSE_ENFORCEMENT_ENABLED", False)
    state = license_mod.get_license_state()
    assert state.state == license_mod.STATE_UNLICENSED
    assert license_mod.license_feature_enabled("anything") is True
    assert license_mod.license_seat_limit() is None
    # 无 License 文件也不拦截任何请求（404/405/401 都行，唯独不能是 403）
    resp = client.post("/api/v1/anything", headers=_BOGUS_BEARER, json={})
    assert resp.status_code != 403
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["license"]["state"] == "unlicensed"


# ---------------------------------------------------------------------------
# 中间件（grace/blocked/invalid 拦写放读，白名单前缀不拦）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "expires_offset,expected_state",
    [
        (-1, license_mod.STATE_GRACE_READONLY),
        (-1000, license_mod.STATE_BLOCKED),
    ],
)
def test_middleware_blocks_mutations_allows_reads(lic, expires_offset, expected_state):
    lic.write_license(expires=date.today() + timedelta(days=expires_offset))
    resp = client.post("/api/v1/anything", headers=_BOGUS_BEARER, json={})
    assert resp.status_code == 403
    assert resp.json()["license"]["state"] == expected_state
    # GET 放行（下游 401/404 均可，只要不是 License 403）
    resp = client.get("/api/v1/jobs", headers=_BOGUS_BEARER)
    assert resp.status_code != 403
    # auth 白名单：登录请求要能到达端点（错密码 → 401，而非 403）
    resp = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code != 403


def test_middleware_blocks_when_license_missing(lic):
    assert license_mod.get_license_state().state == license_mod.STATE_INVALID
    resp = client.post("/api/v1/anything", headers=_BOGUS_BEARER, json={})
    assert resp.status_code == 403
    assert resp.json()["license"]["state"] == license_mod.STATE_INVALID


def test_middleware_passes_mutations_when_valid(lic):
    lic.write_license(expires=date.today() + timedelta(days=365))
    resp = client.post("/api/v1/anything", headers=_BOGUS_BEARER, json={})
    assert resp.status_code != 403


# ---------------------------------------------------------------------------
# 席位闸（create_user）
# ---------------------------------------------------------------------------

def test_seat_gate_blocks_at_max_users(lic):
    lic.write_license(expires=date.today() + timedelta(days=365), max_users=2)
    auth.create_user("u1", "Passw0rd!")
    auth.create_user("u2", "Passw0rd!")  # 未达上限，放行
    with pytest.raises(HTTPException) as excinfo:
        auth.create_user("u3", "Passw0rd!")
    assert excinfo.value.status_code == 409
    assert "seat limit" in str(excinfo.value.detail)


def test_seat_gate_inactive_when_license_invalid(lic):
    # invalid/缺失时不启用席位闸（中间件已经拦截写操作，创建用户走 auth 白名单）
    auth.create_user("u1", "Passw0rd!")
    assert auth.get_user("u1") is not None


# ---------------------------------------------------------------------------
# /license/status + /license/upload + /health
# ---------------------------------------------------------------------------

def test_status_endpoint_is_public(lic):
    lic.write_license(expires=date.today() + timedelta(days=365))
    auth.create_user("u1", "Passw0rd!")
    resp = client.get("/api/v1/license/status")  # 无任何鉴权头
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == license_mod.STATE_VALID
    assert body["customer"] == "测试客户"
    assert body["edition"] == "enterprise"
    assert body["max_users"] == 5
    assert body["seats_used"] == 1
    assert body["features"] == {"industries": ["legal"]}
    assert body["days_left"] >= 300


def test_upload_requires_super_admin(lic):
    auth.create_user("u1", "Passw0rd!")
    headers = {"Authorization": f"Bearer {auth.create_token('u1')}"}
    doc = _make_doc(lic.key, expires=date.today() + timedelta(days=365))
    resp = client.post("/api/v1/license/upload", headers=headers, json=doc)
    assert resp.status_code == 403


def test_upload_valid_license_installs_and_activates(lic):
    headers = _admin_headers()  # 状态 invalid（无文件）时上传必须可用（白名单）
    doc = _make_doc(lic.key, expires=date.today() + timedelta(days=365))
    resp = client.post("/api/v1/license/upload", headers=headers, json=doc)
    assert resp.status_code == 200
    assert resp.json()["state"] == license_mod.STATE_VALID
    assert lic.path.exists()
    assert json.loads(lic.path.read_text(encoding="utf-8")) == doc
    assert license_mod.get_license_state().state == license_mod.STATE_VALID


def test_upload_rejects_invalid_license_without_writing(lic):
    headers = _admin_headers()
    doc = _make_doc(lic.key, expires=date.today() + timedelta(days=365), tamper=True)
    resp = client.post("/api/v1/license/upload", headers=headers, json=doc)
    assert resp.status_code == 400
    assert not lic.path.exists()


def test_upload_rejects_expired_license(lic):
    headers = _admin_headers()
    doc = _make_doc(lic.key, expires=date.today() - timedelta(days=1))
    resp = client.post("/api/v1/license/upload", headers=headers, json=doc)
    assert resp.status_code == 400
    assert not lic.path.exists()


def test_health_reports_license_state(lic):
    lic.write_license(expires=date.today() + timedelta(days=365))
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()["license"]
    assert body["state"] == license_mod.STATE_VALID
    assert body["expires_at"] == (date.today() + timedelta(days=365)).isoformat()
    assert isinstance(body["days_left"], int)
