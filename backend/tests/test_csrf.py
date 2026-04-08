# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""CSRF middleware tests (P0-1: secure flag, P0-2: token rotation)."""
from __future__ import annotations

import os
from typing import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def csrf_client(tmp_data_dir: str) -> Generator[TestClient, None, None]:
    """TestClient with AUTH_ENABLED=true and DEBUG=false (production-like)."""
    os.environ["UPLOAD_DIR"] = os.path.join(tmp_data_dir, "uploads")
    os.environ["OUTPUT_DIR"] = os.path.join(tmp_data_dir, "outputs")
    os.environ["DATA_DIR"] = os.path.join(tmp_data_dir, "data")
    os.environ["JOB_DB_PATH"] = os.path.join(tmp_data_dir, "data", "jobs.db")
    os.environ["AUTH_ENABLED"] = "true"
    os.environ["DEBUG"] = "false"

    from app.main import app

    app.dependency_overrides.clear()

    import app.core.auth as _auth_mod
    _auth_mod._AUTH_FILE = os.path.join(tmp_data_dir, "data", "auth.json")

    from app.api.auth import _auth_limiter
    _auth_limiter._hits.clear()

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    for key in ("UPLOAD_DIR", "OUTPUT_DIR", "DATA_DIR", "JOB_DB_PATH",
                "AUTH_ENABLED", "DEBUG"):
        os.environ.pop(key, None)


@pytest.fixture()
def csrf_debug_client(tmp_data_dir: str) -> Generator[TestClient, None, None]:
    """TestClient with AUTH_ENABLED=true and DEBUG=true."""
    os.environ["UPLOAD_DIR"] = os.path.join(tmp_data_dir, "uploads")
    os.environ["OUTPUT_DIR"] = os.path.join(tmp_data_dir, "outputs")
    os.environ["DATA_DIR"] = os.path.join(tmp_data_dir, "data")
    os.environ["JOB_DB_PATH"] = os.path.join(tmp_data_dir, "data", "jobs.db")
    os.environ["AUTH_ENABLED"] = "true"
    os.environ["DEBUG"] = "true"

    from app.main import app

    app.dependency_overrides.clear()

    import app.core.auth as _auth_mod
    _auth_mod._AUTH_FILE = os.path.join(tmp_data_dir, "data", "auth.json")

    from app.api.auth import _auth_limiter
    _auth_limiter._hits.clear()

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    for key in ("UPLOAD_DIR", "OUTPUT_DIR", "DATA_DIR", "JOB_DB_PATH",
                "AUTH_ENABLED", "DEBUG"):
        os.environ.pop(key, None)


# ── P0-1: CSRF cookie secure flag follows DEBUG setting ──────


def test_csrf_cookie_secure_when_not_debug(csrf_client: TestClient):
    """In production (DEBUG=false), CSRF cookie MUST have Secure flag."""
    resp = csrf_client.get("/api/v1/auth/status")
    assert resp.status_code == 200
    csrf_cookie = resp.cookies.get("csrf_token")
    assert csrf_cookie is not None, "CSRF cookie should be set on first request"
    # Check the Set-Cookie header for Secure flag
    set_cookie_header = resp.headers.get("set-cookie", "")
    assert "csrf_token=" in set_cookie_header
    assert "Secure" in set_cookie_header, (
        "CSRF cookie must have Secure flag when DEBUG=false"
    )


def test_csrf_cookie_no_secure_when_debug(csrf_debug_client: TestClient):
    """In development (DEBUG=true), CSRF cookie should NOT require Secure flag."""
    resp = csrf_debug_client.get("/api/v1/auth/status")
    assert resp.status_code == 200
    csrf_cookie = resp.cookies.get("csrf_token")
    assert csrf_cookie is not None, "CSRF cookie should be set on first request"
    set_cookie_header = resp.headers.get("set-cookie", "")
    assert "csrf_token=" in set_cookie_header
    # Secure should NOT be present in dev mode
    assert "Secure" not in set_cookie_header, (
        "CSRF cookie should NOT have Secure flag when DEBUG=true"
    )


# ── P0-2: CSRF token rotation on auth state changes ─────────


def _setup_and_login(client: TestClient) -> tuple[str, str]:
    """Helper: setup password + login, return (token, csrf_cookie)."""
    password = "Str0ng!Pass#99"
    client.post("/api/v1/auth/setup", json={"password": password})
    resp = client.post("/api/v1/auth/login", json={"password": password})
    token = resp.json()["access_token"]
    csrf = resp.cookies.get("csrf_token", "")
    return token, csrf


def test_csrf_token_rotates_after_login(csrf_debug_client: TestClient):
    """CSRF token MUST change after login (prevents session fixation)."""
    # Get initial CSRF token
    initial_resp = csrf_debug_client.get("/api/v1/auth/status")
    initial_csrf = initial_resp.cookies.get("csrf_token")
    assert initial_csrf, "Should get CSRF cookie on first request"

    # Setup password and login
    password = "Str0ng!Pass#99"
    csrf_debug_client.post("/api/v1/auth/setup", json={"password": password})
    login_resp = csrf_debug_client.post(
        "/api/v1/auth/login", json={"password": password}
    )
    assert login_resp.status_code == 200
    login_csrf = login_resp.cookies.get("csrf_token")
    assert login_csrf, "Should get new CSRF cookie after login"
    assert login_csrf != initial_csrf, (
        "CSRF token must rotate after login to prevent session fixation"
    )


def test_csrf_token_rotates_after_logout(csrf_debug_client: TestClient):
    """CSRF token MUST change after logout."""
    # Setup and login
    token, login_csrf = _setup_and_login(csrf_debug_client)
    assert login_csrf, "Should have CSRF cookie after login"

    # Logout
    logout_resp = csrf_debug_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout_resp.status_code == 200
    logout_csrf = logout_resp.cookies.get("csrf_token")
    assert logout_csrf, "Should get new CSRF cookie after logout"
    assert logout_csrf != login_csrf, (
        "CSRF token must rotate after logout"
    )


def test_csrf_token_rotates_after_setup(csrf_debug_client: TestClient):
    """CSRF token MUST change after initial password setup."""
    # Get initial CSRF token
    initial_resp = csrf_debug_client.get("/api/v1/auth/status")
    initial_csrf = initial_resp.cookies.get("csrf_token")
    assert initial_csrf, "Should get CSRF cookie on first request"

    # Setup password
    setup_resp = csrf_debug_client.post(
        "/api/v1/auth/setup", json={"password": "Str0ng!Pass#99"}
    )
    assert setup_resp.status_code == 200
    setup_csrf = setup_resp.cookies.get("csrf_token")
    assert setup_csrf, "Should get new CSRF cookie after setup"
    assert setup_csrf != initial_csrf, (
        "CSRF token must rotate after password setup"
    )
