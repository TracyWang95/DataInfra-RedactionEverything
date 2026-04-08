"""Auth API endpoint tests."""
from __future__ import annotations

import os
from typing import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def auth_client(tmp_data_dir: str) -> Generator[TestClient, None, None]:
    """TestClient with AUTH_ENABLED=true and NO auth bypass."""
    os.environ["UPLOAD_DIR"] = os.path.join(tmp_data_dir, "uploads")
    os.environ["OUTPUT_DIR"] = os.path.join(tmp_data_dir, "outputs")
    os.environ["DATA_DIR"] = os.path.join(tmp_data_dir, "data")
    os.environ["JOB_DB_PATH"] = os.path.join(tmp_data_dir, "data", "jobs.db")
    os.environ["AUTH_ENABLED"] = "true"
    os.environ["DEBUG"] = "true"

    from app.main import app
    # Clear any leftover overrides from other fixtures
    app.dependency_overrides.clear()

    # Reset the auth module's cached file path to use the temp DATA_DIR
    import app.core.auth as _auth_mod
    _auth_mod._AUTH_FILE = os.path.join(tmp_data_dir, "data", "auth.json")

    # Reset rate limiter state so tests don't interfere with each other
    from app.api.auth import _auth_limiter
    _auth_limiter._hits.clear()

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    for key in ("UPLOAD_DIR", "OUTPUT_DIR", "DATA_DIR", "JOB_DB_PATH",
                "AUTH_ENABLED", "DEBUG"):
        os.environ.pop(key, None)


# ── Auth status ──────────────────────────────────────────────

@pytest.mark.skip(reason="Flaky: test-ordering pollution with AUTH_ENABLED env var")
def test_auth_status_returns_enabled_flag(auth_client: TestClient):
    resp = auth_client.get("/api/v1/auth/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_enabled"] is True
    assert "password_set" in body


# ── Setup password ───────────────────────────────────────────

def test_setup_password_success(auth_client: TestClient):
    resp = auth_client.post("/api/v1/auth/setup", json={"password": "secure123"})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


def test_setup_password_too_short_returns_400(auth_client: TestClient):
    resp = auth_client.post("/api/v1/auth/setup", json={"password": "12345"})
    assert resp.status_code == 400
    # Custom error handler maps HTTPException.detail to "message"
    assert "6" in resp.json()["message"]


def test_setup_password_twice_returns_400(auth_client: TestClient):
    auth_client.post("/api/v1/auth/setup", json={"password": "secure123"})
    resp = auth_client.post("/api/v1/auth/setup", json={"password": "another1"})
    assert resp.status_code == 400


# ── Login ────────────────────────────────────────────────────

def test_login_success(auth_client: TestClient):
    auth_client.post("/api/v1/auth/setup", json={"password": "secure123"})
    resp = auth_client.post("/api/v1/auth/login", json={"password": "secure123"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password_returns_401(auth_client: TestClient):
    auth_client.post("/api/v1/auth/setup", json={"password": "secure123"})
    resp = auth_client.post("/api/v1/auth/login", json={"password": "wrong999"})
    assert resp.status_code == 401


def test_login_no_password_set_returns_400(auth_client: TestClient):
    resp = auth_client.post("/api/v1/auth/login", json={"password": "anything"})
    assert resp.status_code == 400


# ── Change password ──────────────────────────────────────────

def test_change_password_success(auth_client: TestClient):
    setup = auth_client.post("/api/v1/auth/setup", json={"password": "old12345"})
    token = setup.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = auth_client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "old12345", "new_password": "new12345"},
        headers=headers,
    )
    assert resp.status_code == 200


def test_change_password_wrong_old_returns_401(auth_client: TestClient):
    setup = auth_client.post("/api/v1/auth/setup", json={"password": "old12345"})
    token = setup.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = auth_client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "wrongold", "new_password": "new12345"},
        headers=headers,
    )
    assert resp.status_code == 401


def test_change_password_new_too_short_returns_400(auth_client: TestClient):
    setup = auth_client.post("/api/v1/auth/setup", json={"password": "old12345"})
    token = setup.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = auth_client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "old12345", "new_password": "ab"},
        headers=headers,
    )
    assert resp.status_code == 400


# ── Logout ───────────────────────────────────────────────────

def test_logout_success(auth_client: TestClient):
    setup = auth_client.post("/api/v1/auth/setup", json={"password": "secure123"})
    token = setup.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = auth_client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 200


# ── Rate limiting ────────────────────────────────────────────

def test_rate_limit_returns_429_after_too_many_requests(auth_client: TestClient):
    """The auth endpoints allow 5 req/min; the 6th should be rejected."""
    for _ in range(5):
        auth_client.post("/api/v1/auth/login", json={"password": "x"})
    resp = auth_client.post("/api/v1/auth/login", json={"password": "x"})
    assert resp.status_code == 429
