"""Shared pytest fixtures for the backend test suite."""
from __future__ import annotations

import os
from typing import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def tmp_data_dir(tmp_path) -> str:
    """Return a temporary directory for test data (uploads, outputs, db, etc.)."""
    for sub in ("uploads", "outputs", "data"):
        os.makedirs(os.path.join(str(tmp_path), sub), exist_ok=True)
    return str(tmp_path)


@pytest.fixture()
def test_client(tmp_data_dir: str) -> Generator[TestClient, None, None]:
    """Create a FastAPI ``TestClient`` with isolated data directories.

    All file / DB paths are redirected to *tmp_data_dir* so tests never
    touch production data.  Auth is disabled to simplify most tests; if you
    need auth-enabled tests, create a separate fixture that sets
    ``AUTH_ENABLED=true``.
    """
    # Override settings BEFORE importing the app so validators resolve paths
    # against the temp directory.
    os.environ["UPLOAD_DIR"] = os.path.join(tmp_data_dir, "uploads")
    os.environ["OUTPUT_DIR"] = os.path.join(tmp_data_dir, "outputs")
    os.environ["DATA_DIR"] = os.path.join(tmp_data_dir, "data")
    os.environ["JOB_DB_PATH"] = os.path.join(tmp_data_dir, "data", "jobs.db")
    os.environ["AUTH_ENABLED"] = "false"
    os.environ["DEBUG"] = "true"

    # Import app lazily so env overrides take effect
    from app.core.config import settings
    from app.main import app
    from app.core.auth import require_auth
    from app.services.file_management_service import file_store

    # The settings singleton is cached at first app import. If an earlier
    # fixture (e.g. auth_client) flipped AUTH_ENABLED=True, that leaks into
    # later tests and causes CSRFMiddleware to reject POST/DELETE with 403.
    # Force it off for this fixture and restore on teardown.
    _prev_auth_enabled = settings.AUTH_ENABLED
    settings.AUTH_ENABLED = False

    # Module-level singletons (file_store, token_blacklist, etc.) are cached on
    # first import and won't re-bind to the current test's tmp dir. Clear
    # file_store rows so each test starts with an empty upload history.
    file_store.clear()

    # Bypass auth for convenience — individual tests can remove this override
    app.dependency_overrides[require_auth] = lambda: "test_user"

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    file_store.clear()
    settings.AUTH_ENABLED = _prev_auth_enabled

    # Clean up env overrides
    for key in ("UPLOAD_DIR", "OUTPUT_DIR", "DATA_DIR", "JOB_DB_PATH",
                "AUTH_ENABLED", "DEBUG"):
        os.environ.pop(key, None)
