# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Auth status information leakage tests (P0-5)."""
from __future__ import annotations

import os
from typing import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def noauth_client(tmp_data_dir: str) -> Generator[TestClient, None, None]:
    """TestClient with AUTH_ENABLED=false."""
    os.environ["UPLOAD_DIR"] = os.path.join(tmp_data_dir, "uploads")
    os.environ["OUTPUT_DIR"] = os.path.join(tmp_data_dir, "outputs")
    os.environ["DATA_DIR"] = os.path.join(tmp_data_dir, "data")
    os.environ["JOB_DB_PATH"] = os.path.join(tmp_data_dir, "data", "jobs.db")
    os.environ["AUTH_ENABLED"] = "false"
    os.environ["DEBUG"] = "true"

    from app.core.config import settings
    from app.main import app

    app.dependency_overrides.clear()

    _prev_auth = settings.AUTH_ENABLED
    settings.AUTH_ENABLED = False

    with TestClient(app) as client:
        yield client

    settings.AUTH_ENABLED = _prev_auth
    app.dependency_overrides.clear()
    for key in ("UPLOAD_DIR", "OUTPUT_DIR", "DATA_DIR", "JOB_DB_PATH",
                "AUTH_ENABLED", "DEBUG"):
        os.environ.pop(key, None)


@pytest.fixture()
def auth_client(tmp_data_dir: str) -> Generator[TestClient, None, None]:
    """TestClient with AUTH_ENABLED=true."""
    os.environ["UPLOAD_DIR"] = os.path.join(tmp_data_dir, "uploads")
    os.environ["OUTPUT_DIR"] = os.path.join(tmp_data_dir, "outputs")
    os.environ["DATA_DIR"] = os.path.join(tmp_data_dir, "data")
    os.environ["JOB_DB_PATH"] = os.path.join(tmp_data_dir, "data", "jobs.db")
    os.environ["AUTH_ENABLED"] = "true"
    os.environ["DEBUG"] = "true"

    from app.core.config import settings
    from app.main import app

    app.dependency_overrides.clear()

    _prev_auth = settings.AUTH_ENABLED
    settings.AUTH_ENABLED = True

    import app.core.auth as _auth_mod
    _auth_mod._AUTH_FILE = os.path.join(tmp_data_dir, "data", "auth.json")

    from app.api.auth import _auth_limiter
    _auth_limiter._hits.clear()

    with TestClient(app) as client:
        yield client

    settings.AUTH_ENABLED = _prev_auth
    app.dependency_overrides.clear()
    for key in ("UPLOAD_DIR", "OUTPUT_DIR", "DATA_DIR", "JOB_DB_PATH",
                "AUTH_ENABLED", "DEBUG"):
        os.environ.pop(key, None)


# ── P0-5: Auth status should not leak password_set when auth disabled ──


def test_auth_status_no_password_set_when_auth_disabled(noauth_client: TestClient):
    """When AUTH_ENABLED=false, password_set should be null/absent."""
    resp = noauth_client.get("/api/v1/auth/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_enabled"] is False
    # password_set should NOT be returned (or should be None)
    assert body.get("password_set") is None, (
        "password_set should not be exposed when auth is disabled"
    )


def test_auth_status_shows_password_set_when_auth_enabled(auth_client: TestClient):
    """When AUTH_ENABLED=true, password_set should be returned normally."""
    resp = auth_client.get("/api/v1/auth/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_enabled"] is True
    assert "password_set" in body
    assert isinstance(body["password_set"], bool)
