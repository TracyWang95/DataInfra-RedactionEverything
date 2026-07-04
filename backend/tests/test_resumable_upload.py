"""断点续传（分块上传）端点：init/chunk/status/complete 的会话与偏移语义。

complete 的注册路径 mock 掉 process_upload/register_file_with_job——磁盘校验/
病毒扫描/任务挂接是既有整包上传路径的行为，这里只验证分块机制与接线。
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

import app.api.files as files_api
from app.core.config import settings
from app.main import app
from app.models.schemas import FileUploadResponse

client = TestClient(app)


@pytest.fixture(autouse=True)
def _scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    yield


def _init(filename="doc.png", size=12):
    return client.post(
        "/api/v1/files/upload/resumable/init",
        json={"filename": filename, "file_size": size},
    )


def test_init_rejects_bad_extension_and_size():
    assert _init(filename="evil.exe").status_code == 400
    assert _init(size=0).status_code == 400
    assert _init(size=settings.MAX_FILE_SIZE + 1).status_code == 400


def test_chunk_sequential_and_status():
    upload_id = _init(size=10).json()["upload_id"]
    r = client.put(
        f"/api/v1/files/upload/resumable/{upload_id}/chunk",
        params={"offset": 0},
        content=b"12345",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 200 and r.json()["received_bytes"] == 5
    r = client.put(
        f"/api/v1/files/upload/resumable/{upload_id}/chunk",
        params={"offset": 5},
        content=b"67890",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 200 and r.json()["received_bytes"] == 10
    s = client.get(f"/api/v1/files/upload/resumable/{upload_id}").json()
    assert s["received_bytes"] == 10 and s["file_size"] == 10


def test_chunk_gap_conflicts_and_replay_is_idempotent():
    upload_id = _init(size=10).json()["upload_id"]
    client.put(
        f"/api/v1/files/upload/resumable/{upload_id}/chunk",
        params={"offset": 0},
        content=b"12345",
    )
    # 偏移跳空 → 409 + 已收字节
    r = client.put(
        f"/api/v1/files/upload/resumable/{upload_id}/chunk",
        params={"offset": 8},
        content=b"xx",
    )
    assert r.status_code == 409
    assert r.json()["detail"]["received_bytes"] == 5
    # 重放已收过的偏移 → 幂等返回当前进度，不重复写
    r = client.put(
        f"/api/v1/files/upload/resumable/{upload_id}/chunk",
        params={"offset": 0},
        content=b"12345",
    )
    assert r.status_code == 200
    assert r.json()["received_bytes"] == 5 and r.json().get("replayed") is True


def test_chunk_over_declared_size_rejected_and_truncated():
    upload_id = _init(size=4).json()["upload_id"]
    r = client.put(
        f"/api/v1/files/upload/resumable/{upload_id}/chunk",
        params={"offset": 0},
        content=b"123456",
    )
    assert r.status_code == 400
    # 超限被拒后 partial 回滚到原大小，后续可正常续传
    s = client.get(f"/api/v1/files/upload/resumable/{upload_id}").json()
    assert s["received_bytes"] == 0


def test_unknown_or_malformed_session_404():
    assert client.get("/api/v1/files/upload/resumable/deadbeef" + "0" * 24).status_code == 404
    assert client.get("/api/v1/files/upload/resumable/../etc/passwd").status_code == 404


def test_complete_requires_full_file():
    upload_id = _init(size=10).json()["upload_id"]
    client.put(
        f"/api/v1/files/upload/resumable/{upload_id}/chunk",
        params={"offset": 0},
        content=b"12345",
    )
    r = client.post(f"/api/v1/files/upload/resumable/{upload_id}/complete")
    assert r.status_code == 400
    assert r.json()["detail"]["received_bytes"] == 5


def test_complete_moves_file_and_registers(monkeypatch, tmp_path):
    calls: dict = {}

    async def fake_process_upload(**kwargs):
        calls.update(kwargs)
        return (
            FileUploadResponse(
                file_id="fid-1", filename=kwargs["filename"], file_type="image", file_size=kwargs["file_size"],
            ),
            "job-1",
        )

    registered: list = []
    monkeypatch.setattr(files_api._fms, "process_upload", fake_process_upload)
    monkeypatch.setattr(
        files_api._fms,
        "register_file_with_job",
        lambda jid, fid, owner_id: registered.append((jid, fid, owner_id)),
    )

    upload_id = _init(filename="scan.png", size=10).json()["upload_id"]
    client.put(
        f"/api/v1/files/upload/resumable/{upload_id}/chunk",
        params={"offset": 0},
        content=b"0123456789",
    )
    r = client.post(f"/api/v1/files/upload/resumable/{upload_id}/complete")
    assert r.status_code == 200, r.text
    assert r.json()["file_id"] == "fid-1"
    # 文件已从 partial 移入 UPLOAD_DIR，partial 会话已清理
    assert calls["filename"] == "scan.png" and calls["file_size"] == 10
    assert os.path.exists(calls["file_path"])
    assert os.path.dirname(calls["file_path"]) == os.path.realpath(str(tmp_path))
    assert registered == [("job-1", "fid-1", "anonymous")]
    partial_dir = os.path.join(str(tmp_path), "partial", "anonymous")
    assert not any(name.startswith(upload_id) for name in os.listdir(partial_dir))
    # 会话已消费，重复 complete → 404（带幂等键的重试由 idempotency 缓存兜底）
    assert client.post(f"/api/v1/files/upload/resumable/{upload_id}/complete").status_code == 404
