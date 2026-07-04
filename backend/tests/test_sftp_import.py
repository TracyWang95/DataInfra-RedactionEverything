"""第五段方案二：SFTP 主动拉取（fake client 注入，无真实连接）。"""
from __future__ import annotations

import asyncio
import os
import stat as stat_mod
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.services import sftp_import
from app.services import file_management_service as fms


class FakeSftpClient:
    """假远端：/data 下两个文件一个子目录。get() 写出预设内容。"""

    def __init__(self, files: dict[str, bytes]):
        self.files = files  # remote path -> bytes
        self.closed = False

    def listdir_attr(self, path):
        entries = []
        seen_dirs = set()
        for remote, payload in self.files.items():
            if not remote.startswith(path.rstrip("/") + "/"):
                continue
            rest = remote[len(path.rstrip("/")) + 1 :]
            if "/" in rest:
                d = rest.split("/")[0]
                if d not in seen_dirs:
                    seen_dirs.add(d)
                    entries.append(SimpleNamespace(
                        filename=d, st_mode=stat_mod.S_IFDIR, st_size=0))
                continue
            entries.append(SimpleNamespace(
                filename=rest, st_mode=stat_mod.S_IFREG, st_size=len(payload)))
        return entries

    def get(self, remote, local):
        if remote not in self.files:
            raise FileNotFoundError(remote)
        with open(local, "wb") as fh:
            fh.write(self.files[remote])

    def close(self):
        self.closed = True


@pytest.fixture
def sftp_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "SFTP_HOST_ALLOWLIST", "")
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    fake = FakeSftpClient({
        "/data/a.txt": "合同甲方张三".encode(),
        "/data/big.txt": b"x",
        "/data/sub/nested.txt": b"nested",
    })
    monkeypatch.setattr(sftp_import, "_client_factory", lambda src: fake)
    yield fake
    monkeypatch.setattr(sftp_import, "_client_factory", None)


def _mk_source(owner="alice", root="/data"):
    return sftp_import.create_source(
        owner, name="srv-b", host="10.0.0.8", username="ops",
        password="pw", root_path=root,
    )["source_id"]


def test_source_credentials_encrypted_at_rest(sftp_env, tmp_path):
    _mk_source()
    raw = (tmp_path / "data" / "sftp_sources.json").read_text(encoding="utf-8")
    assert "pw" not in raw.split('"encrypted"')[0], "plaintext password must not persist"
    assert '"encrypted"' in raw
    # 列表不回凭据
    listed = sftp_import.list_sources("alice")
    assert "credential" not in listed[0] and "password" not in str(listed[0])


def test_browse_scoped_and_filtered(sftp_env):
    sid = _mk_source()
    result = sftp_import.browse("alice", sid, "")
    assert [f["name"] for f in result["files"]] == ["a.txt", "big.txt"]
    assert result["dirs"] == ["sub"]
    with pytest.raises(HTTPException):
        sftp_import.browse("alice", sid, "../../etc")
    with pytest.raises(HTTPException):
        sftp_import.browse("bob", sid, "")  # 他人源不可见


def test_pull_registers_and_partial_failure(sftp_env):
    sid = _mk_source()

    async def flow():
        result = await sftp_import.pull_files(
            "alice", sid, ["a.txt", "missing.txt", "../evil.txt"], path="",
        )
        assert [i["name"] for i in result["imported"]] == ["a.txt"]
        reasons = {f["name"] for f in result["failed"]}
        assert reasons == {"missing.txt", "../evil.txt"}
        fid = result["imported"][0]["file_id"]
        info = fms.file_store.get(fid)
        assert info and info.get("original_filename") == "a.txt"
        assert not any(f.startswith(".pulling_") for f in os.listdir(settings.UPLOAD_DIR))
        fms.file_store.pop(fid, None)

    asyncio.run(flow())


def test_host_allowlist_enforced(sftp_env, monkeypatch):
    monkeypatch.setattr(settings, "SFTP_HOST_ALLOWLIST", "192.168.1.5")
    with pytest.raises(HTTPException) as exc:
        _mk_source()
    assert exc.value.status_code == 400
