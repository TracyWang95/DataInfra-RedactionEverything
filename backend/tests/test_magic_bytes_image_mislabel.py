"""图片扩展名错标的魔术字节校验 (19合同.webp上传失败根因).

用户的 19合同.webp 内容其实是 JPEG(另存/改名而来),旧逻辑要求扩展名精确
匹配内容签名 → validate_magic_bytes 返回 False → register_file 抛 → 400 Bad
Request。但下游全部用 PIL.Image.open 按内容解码,扩展名对不对无所谓,所以任意
受支持的图片内容都应在任意图片扩展名下放行;非图片二进制(PDF/docx/脚本)伪装成
图片仍必须被拒(安全意图不变)。
"""
import os
import tempfile

import pytest

from app.core.file_validation import validate_magic_bytes

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
REAL_WEBP = b"RIFF\x28\x55\x00\x00WEBPVP8 " + b"\x00" * 20
TIFF = b"II\x2a\x00" + b"\x00" * 20
PDF = b"%PDF-1.7" + b"\x00" * 20
DOCX = b"PK\x03\x04" + b"\x00" * 20
RUBBISH = b"\x01\x02\x03\x04rubbish" + b"\x00" * 20


def _write(data: bytes, name: str) -> str:
    path = os.path.join(tempfile.mkdtemp(), name)
    with open(path, "wb") as f:
        f.write(data)
    return path


@pytest.mark.parametrize(
    "data, ext",
    [
        (JPEG, ".webp"),   # 19合同.webp 的真实情形
        (PNG, ".webp"),
        (REAL_WEBP, ".webp"),
        (TIFF, ".jpg"),
        (PNG, ".jpg"),
        (JPEG, ".png"),
    ],
)
def test_image_content_accepted_under_any_image_extension(data, ext):
    assert validate_magic_bytes(_write(data, f"x{ext}"), ext) is True


@pytest.mark.parametrize(
    "data, ext",
    [
        (PDF, ".webp"),    # PDF 伪装成图片
        (DOCX, ".png"),    # zip/docx 伪装成图片
        (RUBBISH, ".webp"),  # 未知二进制
    ],
)
def test_non_image_disguised_as_image_still_rejected(data, ext):
    assert validate_magic_bytes(_write(data, f"x{ext}"), ext) is False


@pytest.mark.parametrize(
    "data, ext, expected",
    [
        (JPEG, ".jpg", True),
        (PDF, ".pdf", True),
        (DOCX, ".docx", True),
        (b"hello world", ".txt", True),
        (RUBBISH, ".pdf", False),
    ],
)
def test_matching_extension_unchanged(data, ext, expected):
    assert validate_magic_bytes(_write(data, f"x{ext}"), ext) is expected
