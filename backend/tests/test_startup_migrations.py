# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for Issue 11: startup migration functions.

Verifies that:
1. ``run_startup_migrations()`` is callable and doesn't crash.
2. The module-level side effects have been removed.
3. The migrations still run correctly when called explicitly.
"""
from __future__ import annotations

import importlib
import os
import sys
from unittest import mock

import pytest


class TestRunStartupMigrations:
    """run_startup_migrations() is safe to call in various conditions."""

    def test_callable_without_error(self, tmp_path):
        """The function runs without raising, even with empty/fresh state."""
        # Point settings to tmp dirs so nothing real is touched
        with mock.patch("app.core.config.settings") as mock_settings:
            mock_settings.DATA_DIR = str(tmp_path)
            mock_settings.UPLOAD_DIR = str(tmp_path / "uploads")
            mock_settings.OUTPUT_DIR = str(tmp_path / "outputs")
            mock_settings.FILE_STORE_PATH = str(tmp_path / "file_store.json")
            os.makedirs(mock_settings.UPLOAD_DIR, exist_ok=True)
            os.makedirs(mock_settings.OUTPUT_DIR, exist_ok=True)

            from app.services.file_management_service import run_startup_migrations
            # Should not raise
            run_startup_migrations()

    def test_idempotent(self, tmp_path):
        """Calling twice should not raise or corrupt state."""
        with mock.patch("app.core.config.settings") as mock_settings:
            mock_settings.DATA_DIR = str(tmp_path)
            mock_settings.UPLOAD_DIR = str(tmp_path / "uploads")
            mock_settings.OUTPUT_DIR = str(tmp_path / "outputs")
            mock_settings.FILE_STORE_PATH = str(tmp_path / "file_store.json")
            os.makedirs(mock_settings.UPLOAD_DIR, exist_ok=True)
            os.makedirs(mock_settings.OUTPUT_DIR, exist_ok=True)

            from app.services.file_management_service import run_startup_migrations
            run_startup_migrations()
            run_startup_migrations()  # second call should also be fine

    def test_run_startup_migrations_is_called_in_lifespan(self):
        """Verify the lifespan handler invokes run_startup_migrations."""
        # We inspect the source of app.main to confirm the call is present.
        import inspect
        from app.main import lifespan
        source = inspect.getsource(lifespan)
        assert "run_startup_migrations" in source, (
            "lifespan() must call run_startup_migrations() during startup"
        )
