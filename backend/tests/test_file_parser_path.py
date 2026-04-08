# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""File parser path traversal prevention tests (P0-6)."""
from __future__ import annotations

import asyncio
import os

import pytest

from app.core.file_validation import safe_path_in_dir


# ── P0-6: Path validation in file_parser ─────────────────────


class TestSafePathInDir:
    """Unit tests for the safe_path_in_dir utility."""

    def test_path_inside_dir(self, tmp_path):
        allowed = str(tmp_path)
        target = os.path.join(allowed, "file.txt")
        assert safe_path_in_dir(target, allowed) is True

    def test_path_outside_dir(self, tmp_path):
        allowed = str(tmp_path / "uploads")
        os.makedirs(allowed, exist_ok=True)
        target = str(tmp_path / "secrets" / "key.txt")
        assert safe_path_in_dir(target, allowed) is False

    def test_path_traversal_dotdot(self, tmp_path):
        allowed = str(tmp_path / "uploads")
        os.makedirs(allowed, exist_ok=True)
        target = os.path.join(allowed, "..", "secrets", "key.txt")
        assert safe_path_in_dir(target, allowed) is False

    def test_path_is_dir_itself(self, tmp_path):
        allowed = str(tmp_path)
        assert safe_path_in_dir(allowed, allowed) is True


class TestFileParserPathValidation:
    """The file parser must reject paths outside UPLOAD_DIR."""

    def test_convert_with_libreoffice_rejects_outside_path(self, tmp_path, monkeypatch):
        """_convert_with_libreoffice should reject paths outside UPLOAD_DIR."""
        upload_dir = str(tmp_path / "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        outside_path = str(tmp_path / "malicious.doc")
        with open(outside_path, "w") as f:
            f.write("fake doc")

        from app.core.config import settings
        monkeypatch.setattr(settings, "UPLOAD_DIR", upload_dir)

        from app.services.file_parser import FileParser
        parser = FileParser()
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                parser._convert_with_libreoffice(outside_path)
            )
            assert result is None
        finally:
            loop.close()

    def test_convert_doc_to_docx_rejects_outside_path(self, tmp_path, monkeypatch):
        """_convert_doc_to_docx should block path traversal attempts."""
        upload_dir = str(tmp_path / "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        outside_path = os.path.join(str(tmp_path), "..", "etc", "passwd")

        from app.core.config import settings
        monkeypatch.setattr(settings, "UPLOAD_DIR", upload_dir)

        from app.services.file_parser import FileParser
        parser = FileParser()
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                parser._convert_doc_to_docx(outside_path)
            )
            assert result is None
        finally:
            loop.close()

    def test_path_validation_allows_inside_path(self, tmp_path):
        """Paths inside UPLOAD_DIR should pass validation."""
        upload_dir = str(tmp_path / "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        inside_path = os.path.join(upload_dir, "valid.doc")
        with open(inside_path, "w") as f:
            f.write("fake doc")
        assert safe_path_in_dir(inside_path, upload_dir) is True
