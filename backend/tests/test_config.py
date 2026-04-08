# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Configuration module tests."""
from __future__ import annotations

import os

from app.core.config import _resolve_local_path, BACKEND_DIR


class TestResolveLocalPath:
    def test_empty_string(self):
        assert _resolve_local_path("") == ""

    def test_absolute_path(self):
        if os.name == "nt":
            result = _resolve_local_path("C:\\Users\\test")
            assert os.path.isabs(result)
        else:
            result = _resolve_local_path("/tmp/test")
            assert result == "/tmp/test"

    def test_relative_path_resolved_against_base(self):
        result = _resolve_local_path("./data")
        expected = str((BACKEND_DIR / "data").resolve())
        assert result == expected

    def test_whitespace_stripped(self):
        result = _resolve_local_path("  ./data  ")
        expected = str((BACKEND_DIR / "data").resolve())
        assert result == expected


class TestSettingsDefaults:
    def test_settings_has_required_fields(self):
        from app.core.config import settings
        assert hasattr(settings, "UPLOAD_DIR")
        assert hasattr(settings, "OUTPUT_DIR")
        assert hasattr(settings, "DATA_DIR")
        assert hasattr(settings, "MAX_FILE_SIZE")
        assert hasattr(settings, "JWT_SECRET_KEY")
        assert len(settings.JWT_SECRET_KEY) > 0

    def test_max_file_size_is_50mb(self):
        from app.core.config import settings
        assert settings.MAX_FILE_SIZE == 50 * 1024 * 1024

    def test_jwt_algorithm_default(self):
        from app.core.config import settings
        assert settings.JWT_ALGORITHM == "HS256"

    def test_default_replacement_mode(self):
        from app.core.config import settings
        assert settings.DEFAULT_REPLACEMENT_MODE in ("smart", "mask", "custom")
