# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Password complexity validation tests (P0-4)."""
from __future__ import annotations

import os
from typing import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def auth_client(tmp_data_dir: str) -> Generator[TestClient, None, None]:
    """TestClient with AUTH_ENABLED=true."""
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


# ── P0-4: Password complexity beyond just length ─────────────


def test_password_no_uppercase_rejected(auth_client: TestClient):
    """Password without uppercase letter should be rejected."""
    resp = auth_client.post(
        "/api/v1/auth/setup",
        json={"password": "alllowercase1!"},
    )
    assert resp.status_code == 400
    assert "大写" in resp.json()["message"] or "uppercase" in resp.json()["message"].lower()


def test_password_no_lowercase_rejected(auth_client: TestClient):
    """Password without lowercase letter should be rejected."""
    resp = auth_client.post(
        "/api/v1/auth/setup",
        json={"password": "ALLUPPERCASE1!"},
    )
    assert resp.status_code == 400


def test_password_no_digit_rejected(auth_client: TestClient):
    """Password without digit should be rejected."""
    resp = auth_client.post(
        "/api/v1/auth/setup",
        json={"password": "NoDigitsHere!!"},
    )
    assert resp.status_code == 400


def test_password_no_special_rejected(auth_client: TestClient):
    """Password without special character should be rejected."""
    resp = auth_client.post(
        "/api/v1/auth/setup",
        json={"password": "NoSpecialChar1"},
    )
    assert resp.status_code == 400


def test_password_all_requirements_met_succeeds(auth_client: TestClient):
    """Password meeting all requirements should succeed."""
    resp = auth_client.post(
        "/api/v1/auth/setup",
        json={"password": "Str0ng!Pass#99"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_change_password_complexity_enforced(auth_client: TestClient):
    """Password complexity should also be enforced on change-password."""
    # Setup with valid password
    setup = auth_client.post(
        "/api/v1/auth/setup",
        json={"password": "Str0ng!Pass#99"},
    )
    token = setup.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Try to change to weak password (no special char)
    resp = auth_client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "Str0ng!Pass#99", "new_password": "WeakNewPass12"},
        headers=headers,
    )
    assert resp.status_code == 400


# ── Unit tests for validate_password_strength ────────────────


def test_validate_password_strength_function():
    """Direct unit test for the validation function."""
    from app.core.auth import validate_password_strength

    # Too short
    errors = validate_password_strength("Ab1!")
    assert len(errors) > 0

    # Missing uppercase
    errors = validate_password_strength("alllowercase1!")
    assert len(errors) > 0

    # Missing lowercase
    errors = validate_password_strength("ALLUPPERCASE1!")
    assert len(errors) > 0

    # Missing digit
    errors = validate_password_strength("NoDigitsHere!!")
    assert len(errors) > 0

    # Missing special
    errors = validate_password_strength("NoSpecialChar1")
    assert len(errors) > 0

    # All valid
    errors = validate_password_strength("Str0ng!Pass#99")
    assert len(errors) == 0
