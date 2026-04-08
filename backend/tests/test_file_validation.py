# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""File validation utility tests."""
from __future__ import annotations

import os

import pytest

from app.core.file_validation import (
    get_file_type,
    safe_path_in_dir,
    validate_extension,
    validate_magic_bytes,
)
from app.models.schemas import FileType


# ── validate_extension ───────────────────────────────────────


class TestValidateExtension:
    def test_allowed_extensions(self):
        for ext in (".docx", ".pdf", ".txt", ".jpg", ".png"):
            assert validate_extension(ext) is True, f"{ext} should be allowed"

    def test_disallowed_extensions(self):
        for ext in (".exe", ".sh", ".py", ".bat", ".dll"):
            assert validate_extension(ext) is False, f"{ext} should be rejected"

    def test_doc_extension_allowed(self):
        assert validate_extension(".doc") is True


# ── get_file_type ────────────────────────────────────────────


class TestGetFileType:
    def test_docx(self):
        assert get_file_type("report.docx") == FileType.DOCX

    def test_doc(self):
        assert get_file_type("legacy.doc") == FileType.DOC

    def test_pdf(self):
        assert get_file_type("document.pdf") == FileType.PDF

    def test_txt(self):
        assert get_file_type("readme.txt") == FileType.TXT

    def test_markdown(self):
        assert get_file_type("notes.md") == FileType.TXT

    def test_html(self):
        assert get_file_type("page.html") == FileType.TXT

    def test_images(self):
        for ext in (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"):
            assert get_file_type(f"photo{ext}") == FileType.IMAGE

    def test_unsupported(self):
        assert get_file_type("script.py") is None
        assert get_file_type("binary.exe") is None


# ── validate_magic_bytes ─────────────────────────────────────


class TestValidateMagicBytes:
    def test_pdf_magic(self, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_bytes(b"%PDF-1.4 rest of content")
        assert validate_magic_bytes(str(f), ".pdf") is True

    def test_pdf_magic_wrong_ext(self, tmp_path):
        f = tmp_path / "test.docx"
        f.write_bytes(b"%PDF-1.4 rest of content")
        assert validate_magic_bytes(str(f), ".docx") is False

    def test_png_magic(self, tmp_path):
        f = tmp_path / "test.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n rest")
        assert validate_magic_bytes(str(f), ".png") is True

    def test_jpeg_magic(self, tmp_path):
        f = tmp_path / "test.jpg"
        f.write_bytes(b"\xff\xd8\xff\xe0 rest")
        assert validate_magic_bytes(str(f), ".jpg") is True

    def test_text_no_magic(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello world", encoding="utf-8")
        assert validate_magic_bytes(str(f), ".txt") is True

    def test_unknown_binary_rejected(self, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_bytes(b"\x00\x00\x00\x00\x00\x00\x00\x00")
        assert validate_magic_bytes(str(f), ".xyz") is False

    def test_missing_file(self):
        assert validate_magic_bytes("/nonexistent/file.pdf", ".pdf") is False

    def test_docx_pkzip_magic(self, tmp_path):
        f = tmp_path / "test.docx"
        f.write_bytes(b"PK\x03\x04 rest of content")
        assert validate_magic_bytes(str(f), ".docx") is True


# ── safe_path_in_dir (extended) ──────────────────────────────


class TestSafePathInDirExtended:
    def test_nested_subdirectory(self, tmp_path):
        allowed = str(tmp_path / "root")
        target = os.path.join(allowed, "sub", "deep", "file.txt")
        assert safe_path_in_dir(target, allowed) is True

    def test_sibling_directory(self, tmp_path):
        allowed = str(tmp_path / "uploads")
        target = str(tmp_path / "outputs" / "file.txt")
        assert safe_path_in_dir(target, allowed) is False

    def test_prefix_attack(self, tmp_path):
        """'uploads_evil' should NOT be inside 'uploads'."""
        allowed = str(tmp_path / "uploads")
        os.makedirs(allowed, exist_ok=True)
        evil = str(tmp_path / "uploads_evil" / "file.txt")
        assert safe_path_in_dir(evil, allowed) is False
