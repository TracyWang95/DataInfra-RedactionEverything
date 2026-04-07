# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
文件校验工具 — 魔术字节验证、扩展名检查、文件类型推断、路径安全校验。

从 services/file_management_service.py 和 services/file_service.py 合并提取，
作为唯一权威来源 (single source of truth)。
"""
from __future__ import annotations

import os
from typing import Optional

from app.core.config import settings
from app.models.schemas import FileType

# ---------------------------------------------------------------------------
# Magic-byte signatures → allowed extensions
# ---------------------------------------------------------------------------
MAGIC_BYTES: dict[bytes, set[str]] = {
    b"%PDF": {".pdf"},
    b"PK\x03\x04": {".docx", ".doc"},
    b"\xff\xd8\xff": {".jpg", ".jpeg"},
    b"\x89PNG": {".png"},
    b"GIF8": {".gif"},
    b"BM": {".bmp"},
    b"RIFF": {".webp"},
    b"\xd0\xcf\x11\xe0": {".doc", ".rtf"},
    b"II\x2a\x00": {".tif", ".tiff"},
    b"MM\x00\x2a": {".tif", ".tiff"},
    b"{\\rtf": {".rtf"},
}

# Text-like extensions that have no fixed magic bytes
TEXT_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".rtf", ".html", ".htm"})


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_magic_bytes(file_path: str, ext: str) -> bool:
    """Validate file magic bytes match *ext*. Reject unknown binary signatures.

    Returns ``True`` when the file header matches the extension, or when the
    extension is a known text type (text files have no fixed magic bytes).
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(8)
        for magic, exts in MAGIC_BYTES.items():
            if header.startswith(magic):
                return ext in exts
        # No known magic-byte match — only allow text extensions through
        if ext in TEXT_EXTENSIONS:
            return True
        # Non-text extension with no matching signature → reject
        return False
    except OSError:
        return False


def validate_extension(ext: str) -> bool:
    """Check whether *ext* is in the server's allowed-extension list."""
    return ext in settings.ALLOWED_EXTENSIONS


def get_file_type(filename: str) -> Optional[FileType]:
    """Infer :class:`FileType` from file extension. Returns ``None`` for
    unsupported types (caller should raise an appropriate error)."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".doc":
        return FileType.DOC
    elif ext == ".docx":
        return FileType.DOCX
    elif ext in (".txt", ".md", ".rtf", ".html", ".htm"):
        return FileType.TXT
    elif ext == ".pdf":
        return FileType.PDF
    elif ext in (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"):
        return FileType.IMAGE
    return None


def safe_path_in_dir(file_path: str, allowed_dir: str) -> bool:
    """Path-traversal guard: ensure *file_path* is inside *allowed_dir*."""
    real_file = os.path.realpath(file_path)
    real_dir = os.path.realpath(allowed_dir)
    return real_file == real_dir or real_file.startswith(real_dir + os.sep)
