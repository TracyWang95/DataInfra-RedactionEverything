"""第五段方案一：内网落地目录导入。"""
from __future__ import annotations

import asyncio
import os

import pytest

from app.core.config import settings
from app.services import file_management_service as fms


@pytest.fixture
def inbox_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "IMPORT_INBOX_DIR", str(tmp_path / "inbox"))
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    return tmp_path


def _put(owner: str, name: str, payload: bytes = b"hello world") -> str:
    d = fms.import_inbox_dir(owner)
    path = os.path.join(d, name)
    with open(path, "wb") as fh:
        fh.write(payload)
    return path


def test_list_scoped_to_owner_and_supported_ext(inbox_env):
    _put("alice", "a.txt")
    _put("alice", "ignored.exe")
    _put("bob", "b.txt")
    result = fms.list_import_inbox("alice")
    names = [i["name"] for i in result["items"]]
    assert names == ["a.txt"], names
    assert "alice" in result["path"]


def test_import_registers_and_clears_inbox(inbox_env):
    src = _put("alice", "doc1.txt", "合同编号 HT-1，张三 13800001111".encode())

    async def flow():
        result = await fms.import_inbox_files("alice", ["doc1.txt"])
        assert result["failed"] == [], result
        assert len(result["imported"]) == 1
        fid = result["imported"][0]["file_id"]
        # inbox 已清空（move 语义）
        assert not os.path.exists(src)
        # 已登记且归属正确
        info = fms.file_store.get(fid)
        assert info and info.get("original_filename") == "doc1.txt"
        assert fms.file_owner_id(info) == "alice"
        fms.file_store.pop(fid, None)

    asyncio.run(flow())


def test_path_traversal_and_missing_rejected(inbox_env):
    _put("alice", "ok.txt")

    async def flow():
        result = await fms.import_inbox_files(
            "alice", ["../../etc/passwd", "..\\\\secrets.txt", "nope.txt"]
        )
        assert len(result["failed"]) == 3
        assert result["imported"] == []

    asyncio.run(flow())


def test_forged_extension_returns_to_inbox(inbox_env):
    # PNG 扩展名但内容是文本 → magic bytes 校验拒绝 → 移回 inbox 继续
    src = _put("alice", "fake.png", b"this is not a png at all")
    good = _put("alice", "real.txt", b"some text")

    async def flow():
        result = await fms.import_inbox_files("alice", ["fake.png", "real.txt"])
        assert [f["name"] for f in result["failed"]] == ["fake.png"]
        assert [i["name"] for i in result["imported"]] == ["real.txt"]
        assert os.path.exists(src), "rejected file must return to inbox"
        assert not os.path.exists(good)
        for item in result["imported"]:
            fms.file_store.pop(item["file_id"], None)

    asyncio.run(flow())
