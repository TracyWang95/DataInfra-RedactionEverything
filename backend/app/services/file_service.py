"""
文件管理业务逻辑 — 从 api/files.py 提取。

将文件上传验证、类型检测、魔术字节校验等业务逻辑与 API 路由解耦，
便于单元测试和复用。
"""
from __future__ import annotations

import os
import re
from typing import Optional

from app.core.config import settings
from app.models.schemas import FileType

_BATCH_GROUP_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")

# 文本类扩展名（无固定魔术字节）
_TEXT_EXTENSIONS = frozenset({'.txt', '.md', '.rtf', '.html', '.htm'})

MAGIC_BYTES = {
    b'%PDF': {'.pdf'},
    b'PK\x03\x04': {'.docx', '.doc'},
    b'\xff\xd8\xff': {'.jpg', '.jpeg'},
    b'\x89PNG': {'.png'},
    b'GIF8': {'.gif'},
    b'BM': {'.bmp'},
    b'RIFF': {'.webp'},
    b'\xd0\xcf\x11\xe0': {'.doc', '.rtf'},
    b'II\x2a\x00': {'.tif', '.tiff'},
    b'MM\x00\x2a': {'.tif', '.tiff'},
    b'{\\rtf': {'.rtf'},
}


def get_file_type(filename: str) -> FileType:
    """根据文件扩展名判断文件类型"""
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
    else:
        raise ValueError(f"不支持的文件类型: {ext}")


def validate_magic_bytes(file_path: str, ext: str) -> bool:
    """Validate file magic bytes match extension. Reject unknown binary signatures."""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(8)
        for magic, exts in MAGIC_BYTES.items():
            if header.startswith(magic):
                return ext in exts
        if ext in _TEXT_EXTENSIONS:
            return True
        return False
    except OSError:
        return False


def validate_extension(ext: str) -> bool:
    """检查扩展名是否在允许列表中"""
    return ext in settings.ALLOWED_EXTENSIONS


def sanitize_job_id(raw: Optional[str]) -> Optional[str]:
    """任务中心 Job UUID 合法性校验"""
    import uuid
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    try:
        uuid.UUID(s)
    except (ValueError, TypeError):
        return None
    return s


def sanitize_upload_source(raw: Optional[str]) -> Optional[str]:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip().lower()
    if s in ("playground", "batch"):
        return s
    return None


def sanitize_batch_group_id(raw: Optional[str]) -> Optional[str]:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if len(s) > 80:
        s = s[:80]
    if not _BATCH_GROUP_ID_RE.match(s):
        return None
    return s


def safe_path_in_dir(file_path: str, allowed_dir: str) -> bool:
    """路径遍历保护：验证文件路径在允许目录内"""
    real_file = os.path.realpath(file_path)
    real_dir = os.path.realpath(allowed_dir)
    return real_file == real_dir or real_file.startswith(real_dir + os.sep)
