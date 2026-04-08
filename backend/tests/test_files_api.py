"""File management API endpoint tests."""
from __future__ import annotations

import io
import os

import pytest
from fastapi.testclient import TestClient


def _upload_txt(client: TestClient, filename: str = "sample.txt", content: bytes = b"Hello world") -> tuple[dict, int]:
    """Helper: upload a .txt file and return (json_body, status_code)."""
    resp = client.post(
        "/api/v1/files/upload",
        files={"file": (filename, io.BytesIO(content), "text/plain")},
    )
    return resp.json(), resp.status_code


# ── List files ───────────────────────────────────────────────

def test_list_files_empty(test_client: TestClient):
    resp = test_client.get("/api/v1/files")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["files"] == []


def test_list_files_after_upload(test_client: TestClient):
    _upload_txt(test_client)
    resp = test_client.get("/api/v1/files")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert len(body["files"]) >= 1
    assert body["files"][0]["original_filename"] == "sample.txt"


# ── Upload file ──────────────────────────────────────────────

def test_upload_valid_file(test_client: TestClient):
    body, status = _upload_txt(test_client)
    assert status == 200
    assert "file_id" in body
    assert body["filename"] == "sample.txt"
    assert body["file_size"] > 0


def test_upload_invalid_type_returns_400(test_client: TestClient):
    content = b"not a real exe"
    resp = test_client.post(
        "/api/v1/files/upload",
        files={"file": ("malware.exe", io.BytesIO(content), "application/octet-stream")},
    )
    assert resp.status_code == 400
    body = resp.json()
    # Custom error handler puts HTTPException detail into "message"
    assert "不支持" in body.get("message", "") or "类型" in body.get("message", "")


def test_upload_oversized_file_returns_error(test_client: TestClient, tmp_data_dir: str):
    """A file exceeding MAX_FILE_SIZE should be rejected (400 or 413)."""
    from app.core.config import settings
    original = settings.MAX_FILE_SIZE
    settings.MAX_FILE_SIZE = 1024  # 1 KB
    try:
        content = os.urandom(2048)  # 2 KB > 1 KB limit
        resp = test_client.post(
            "/api/v1/files/upload",
            files={"file": ("big.txt", io.BytesIO(content), "text/plain")},
        )
        assert resp.status_code in (400, 413)
    finally:
        settings.MAX_FILE_SIZE = original


# ── Download file ────────────────────────────────────────────

def test_download_file_exists(test_client: TestClient):
    body, status = _upload_txt(test_client, content=b"download me")
    assert status == 200
    file_id = body["file_id"]
    resp = test_client.get(f"/api/v1/files/{file_id}/download")
    assert resp.status_code == 200
    assert len(resp.content) > 0


def test_download_file_not_found_returns_404(test_client: TestClient):
    resp = test_client.get("/api/v1/files/nonexistent-id/download")
    assert resp.status_code == 404


# ── Delete file ──────────────────────────────────────────────

def test_delete_file_success(test_client: TestClient):
    body, status = _upload_txt(test_client)
    assert status == 200
    file_id = body["file_id"]
    resp = test_client.delete(f"/api/v1/files/{file_id}")
    assert resp.status_code == 200
    # Verify it's gone
    resp2 = test_client.get(f"/api/v1/files/{file_id}")
    assert resp2.status_code == 404


def test_delete_file_not_found_returns_404(test_client: TestClient):
    resp = test_client.delete("/api/v1/files/nonexistent-id")
    assert resp.status_code == 404
