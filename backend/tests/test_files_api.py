"""文件列表与批量 ZIP 下载 API 测试。

仅挂载 files 路由，避免在测试环境导入完整 app（需 PyMuPDF 等可选依赖）。
"""
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import files as files_mod
from app.core.config import settings

app = FastAPI()
app.include_router(files_mod.router, prefix=settings.API_PREFIX)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_file_store():
    """每个用例使用独立内存中的 file_store。"""
    backup = dict(files_mod.file_store)
    files_mod.file_store.clear()
    yield
    files_mod.file_store.clear()
    files_mod.file_store.update(backup)


def test_list_files_empty(client):
    r = client.get("/api/v1/files")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["files"] == []
    assert data["page"] == 1
    assert data["page_size"] == 20


def test_list_files_one_row(client, tmp_path):
    p = tmp_path / "sample.docx"
    p.write_bytes(b"fake docx content")
    fid = "test-file-id-1"
    files_mod.file_store[fid] = {
        "id": fid,
        "original_filename": "sample.docx",
        "stored_filename": "sample.docx",
        "file_path": str(p),
        "file_type": "docx",
        "file_size": 20,
        "created_at": "2025-03-01T12:00:00+00:00",
        "entities": [],
    }
    r = client.get("/api/v1/files")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert len(data["files"]) == 1
    assert data["files"][0]["file_id"] == fid
    assert data["files"][0]["has_output"] is False
    assert data["files"][0]["entity_count"] == 0


def test_list_files_uses_redacted_count_when_present(client, tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(b"\x89PNG")
    fid = "done-1"
    files_mod.file_store[fid] = {
        "id": fid,
        "original_filename": "x.png",
        "file_path": str(p),
        "file_type": "image",
        "file_size": 4,
        "created_at": "2025-03-01T12:00:00+00:00",
        "output_path": str(tmp_path / "out.png"),
        "entities": [],
        "bounding_boxes": {},
        "redacted_count": 17,
    }
    r = client.get("/api/v1/files")
    assert r.status_code == 200
    assert r.json()["files"][0]["entity_count"] == 17


def test_list_files_entity_count_includes_image_boxes(client, tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(b"\x89PNG")
    fid = "img-1"
    files_mod.file_store[fid] = {
        "id": fid,
        "original_filename": "a.png",
        "file_path": str(p),
        "file_type": "image",
        "file_size": 4,
        "created_at": "2025-03-01T12:00:00+00:00",
        "entities": [],
        "bounding_boxes": {
            1: [
                {"id": "b1", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2, "type": "NAME", "selected": True},
                {"id": "b2", "x": 0.3, "y": 0.3, "width": 0.1, "height": 0.1, "type": "ID", "selected": True},
            ],
        },
    }
    r = client.get("/api/v1/files")
    assert r.status_code == 200
    assert r.json()["files"][0]["entity_count"] == 2


def test_list_files_pagination(client, tmp_path):
    for i in range(5):
        p = tmp_path / f"f{i}.docx"
        p.write_bytes(b"x")
        fid = f"id-{i}"
        files_mod.file_store[fid] = {
            "id": fid,
            "original_filename": f"f{i}.docx",
            "file_path": str(p),
            "file_type": "docx",
            "file_size": 1,
            "created_at": f"2025-03-0{i+1}T12:00:00+00:00",
        }
    r = client.get("/api/v1/files?page=1&page_size=2")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 5
    assert len(data["files"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2
    r2 = client.get("/api/v1/files?page=3&page_size=2")
    assert len(r2.json()["files"]) == 1


def test_batch_download_original_zip(client, tmp_path):
    p = tmp_path / "a.docx"
    p.write_bytes(b"hello")
    fid = "id-a"
    files_mod.file_store[fid] = {
        "id": fid,
        "original_filename": "a.docx",
        "file_path": str(p),
        "file_type": "docx",
        "file_size": 5,
    }
    r = client.post(
        "/api/v1/files/batch/download",
        json={"file_ids": [fid], "redacted": False},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "a.docx" in names
    assert zf.read("a.docx") == b"hello"


def test_batch_download_missing_id_returns_400(client):
    r = client.post(
        "/api/v1/files/batch/download",
        json={"file_ids": ["no-such-id"], "redacted": False},
    )
    assert r.status_code == 400
    body = r.json()
    assert "missing" in body.get("detail", {})


def test_batch_redacted_requires_output(client, tmp_path):
    p = tmp_path / "b.docx"
    p.write_bytes(b"x")
    fid = "id-b"
    files_mod.file_store[fid] = {
        "id": fid,
        "original_filename": "b.docx",
        "file_path": str(p),
        "file_type": "docx",
        "file_size": 1,
    }
    r = client.post(
        "/api/v1/files/batch/download",
        json={"file_ids": [fid], "redacted": True},
    )
    assert r.status_code == 400


def test_batch_redacted_zip(client, tmp_path):
    orig = tmp_path / "orig.docx"
    out = tmp_path / "out.docx"
    orig.write_bytes(b"orig")
    out.write_bytes(b"redacted")
    fid = "id-c"
    files_mod.file_store[fid] = {
        "id": fid,
        "original_filename": "orig.docx",
        "file_path": str(orig),
        "output_path": str(out),
        "file_type": "docx",
        "file_size": 4,
    }
    r = client.post(
        "/api/v1/files/batch/download",
        json={"file_ids": [fid], "redacted": True},
    )
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert any(n.startswith("redacted_") for n in zf.namelist())
    data = zf.read(zf.namelist()[0])
    assert data == b"redacted"
