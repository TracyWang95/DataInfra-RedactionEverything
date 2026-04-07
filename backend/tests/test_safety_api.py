"""Safety / storage-info API tests."""
from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient


# ── Storage info endpoint ────────────────────────────────────

def test_storage_info_returns_paths_and_sizes(test_client: TestClient, tmp_data_dir: str):
    resp = test_client.get("/api/v1/safety/storage-info")
    assert resp.status_code == 200
    body = resp.json()
    assert "upload_dir" in body
    assert "output_dir" in body
    assert "db_path" in body
    assert body["upload_size_bytes"] >= 0
    assert body["output_size_bytes"] >= 0
    assert body["total_size_bytes"] == body["upload_size_bytes"] + body["output_size_bytes"]


def test_storage_info_reflects_uploaded_file(test_client: TestClient, tmp_data_dir: str):
    """After writing a file to the upload dir, storage info should report non-zero size."""
    import io

    # Invalidate the safety module's dir-size cache so fresh data is returned
    from app.api.safety import invalidate_dir_size_cache
    invalidate_dir_size_cache()

    # Upload a .txt file via the API so it lands in the temp upload dir
    content = b"probe content for size test " * 10
    test_client.post(
        "/api/v1/files/upload",
        files={"file": ("probe.txt", io.BytesIO(content), "text/plain")},
    )

    # Invalidate again to force re-scan
    invalidate_dir_size_cache()

    resp = test_client.get("/api/v1/safety/storage-info")
    assert resp.status_code == 200
    assert resp.json()["upload_size_bytes"] > 0


# ── Caching behaviour ────────────────────────────────────────

def test_storage_info_caching_returns_same_value_within_ttl(
    test_client: TestClient, tmp_data_dir: str
):
    """Two rapid calls should return the same cached sizes."""
    from app.api.safety import invalidate_dir_size_cache
    invalidate_dir_size_cache()

    resp1 = test_client.get("/api/v1/safety/storage-info")
    resp2 = test_client.get("/api/v1/safety/storage-info")
    assert resp1.json()["upload_size_bytes"] == resp2.json()["upload_size_bytes"]
    assert resp1.json()["output_size_bytes"] == resp2.json()["output_size_bytes"]


def test_dir_size_cache_returns_stale_until_invalidated(tmp_data_dir: str):
    """Directly test _get_dir_size_cached honours the TTL / invalidation."""
    from app.api.safety import _get_dir_size_cached, invalidate_dir_size_cache

    upload_dir = os.path.join(tmp_data_dir, "uploads")
    invalidate_dir_size_cache()

    size_before = _get_dir_size_cached(upload_dir)

    # Write a file directly on disk
    with open(os.path.join(upload_dir, "dummy.bin"), "wb") as f:
        f.write(os.urandom(512))

    # Cached — should still return old value
    size_cached = _get_dir_size_cached(upload_dir)
    assert size_cached == size_before

    # After explicit invalidation, new value is picked up
    invalidate_dir_size_cache()
    size_after = _get_dir_size_cached(upload_dir)
    assert size_after > size_before
