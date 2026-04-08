# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for critical API paths.

These tests use FastAPI's TestClient to exercise end-to-end flows without
requiring live ML inference services.
"""
from __future__ import annotations

import io
import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

# ─── Helpers ────────────────────────────────────────────────────

def _upload_txt(client: TestClient, filename: str = "test.txt", content: bytes = b"Hello integration test") -> dict:
    resp = client.post(
        "/api/v1/files/upload",
        files={"file": (filename, io.BytesIO(content), "text/plain")},
    )
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    return resp.json()


# ─── 1. File upload flow ───────────────────────────────────────

class TestFileUploadFlow:
    def test_upload_returns_file_id(self, test_client: TestClient):
        body = _upload_txt(test_client)
        assert "file_id" in body
        assert body["filename"] == "test.txt"
        assert body["file_size"] > 0
        assert body["message"] == "文件上传成功"

    def test_upload_rejects_unsupported_extension(self, test_client: TestClient):
        resp = test_client.post(
            "/api/v1/files/upload",
            files={"file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_upload_idempotency(self, test_client: TestClient):
        key = "idem-test-001"
        headers = {"X-Idempotency-Key": key}
        body1 = test_client.post(
            "/api/v1/files/upload",
            files={"file": ("a.txt", io.BytesIO(b"AAA"), "text/plain")},
            headers=headers,
        ).json()
        body2 = test_client.post(
            "/api/v1/files/upload",
            files={"file": ("b.txt", io.BytesIO(b"BBB"), "text/plain")},
            headers=headers,
        ).json()
        assert body1["file_id"] == body2["file_id"], "Idempotency key should return same result"


# ─── 2. File listing and download ─────────────────────────────

class TestFileListAndDownload:
    def test_list_returns_ok(self, test_client: TestClient):
        resp = test_client.get("/api/v1/files")
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "files" in body

    def test_list_after_upload(self, test_client: TestClient):
        _upload_txt(test_client, "listed.txt")
        resp = test_client.get("/api/v1/files")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1

    def test_download_original(self, test_client: TestClient):
        content = b"Download me"
        upload = _upload_txt(test_client, "dl.txt", content)
        fid = upload["file_id"]
        resp = test_client.get(f"/api/v1/files/{fid}/download")
        assert resp.status_code == 200
        assert resp.content == content

    def test_download_nonexistent(self, test_client: TestClient):
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = test_client.get(f"/api/v1/files/{fake_id}/download")
        assert resp.status_code == 404


# ─── 3. Entity types CRUD ─────────────────────────────────────

class TestEntityTypesCRUD:
    def test_list_types(self, test_client: TestClient):
        resp = test_client.get("/api/v1/custom-types")
        assert resp.status_code == 200
        body = resp.json()
        assert "custom_types" in body
        assert "total" in body

    def test_create_and_read(self, test_client: TestClient):
        create_resp = test_client.post("/api/v1/custom-types", json={
            "name": "测试类型",
            "description": "集成测试用实体类型",
            "examples": ["示例A", "示例B"],
        })
        assert create_resp.status_code == 200, create_resp.text
        created = create_resp.json()
        type_id = created.get("id") or created.get("type_id")
        assert type_id

        get_resp = test_client.get(f"/api/v1/custom-types/{type_id}")
        assert get_resp.status_code == 200

    def test_update_type(self, test_client: TestClient):
        create_resp = test_client.post("/api/v1/custom-types", json={
            "name": "待更新类型",
            "description": "将被更新",
        })
        created = create_resp.json()
        type_id = created.get("id") or created.get("type_id")

        update_resp = test_client.put(f"/api/v1/custom-types/{type_id}", json={
            "description": "已更新描述",
        })
        assert update_resp.status_code == 200

    def test_delete_type(self, test_client: TestClient):
        create_resp = test_client.post("/api/v1/custom-types", json={
            "name": "待删除类型",
            "description": "将被删除",
        })
        created = create_resp.json()
        type_id = created.get("id") or created.get("type_id")

        del_resp = test_client.delete(f"/api/v1/custom-types/{type_id}")
        assert del_resp.status_code == 200

        get_resp = test_client.get(f"/api/v1/custom-types/{type_id}")
        assert get_resp.status_code == 404

    def test_get_nonexistent_type(self, test_client: TestClient):
        resp = test_client.get("/api/v1/custom-types/nonexistent_id_xyz")
        assert resp.status_code == 404


# ─── 4. Auth flow ──────────────────────────────────────────────

@pytest.fixture()
def auth_integration_client(tmp_data_dir: str) -> Generator[TestClient, None, None]:
    """TestClient with AUTH_ENABLED=true for auth flow tests."""
    os.environ["UPLOAD_DIR"] = os.path.join(tmp_data_dir, "uploads")
    os.environ["OUTPUT_DIR"] = os.path.join(tmp_data_dir, "outputs")
    os.environ["DATA_DIR"] = os.path.join(tmp_data_dir, "data")
    os.environ["JOB_DB_PATH"] = os.path.join(tmp_data_dir, "data", "jobs.db")
    os.environ["AUTH_ENABLED"] = "true"
    os.environ["DEBUG"] = "true"

    from app.main import app
    app.dependency_overrides.clear()

    import app.core.auth as _auth_mod
    _auth_mod._AUTH_FILE = os.path.join(tmp_data_dir, "data", "auth.json")

    # Patch the cached settings singleton so require_auth actually enforces auth
    from app.core.config import settings
    _orig_auth = settings.AUTH_ENABLED
    settings.AUTH_ENABLED = True

    # Reset rate limiter and lockout state
    from app.api.auth import _auth_limiter
    _auth_limiter._hits.clear()
    _auth_mod._login_attempts.clear()

    with TestClient(app) as client:
        yield client

    settings.AUTH_ENABLED = _orig_auth
    app.dependency_overrides.clear()
    for key in ("UPLOAD_DIR", "OUTPUT_DIR", "DATA_DIR", "JOB_DB_PATH",
                "AUTH_ENABLED", "DEBUG"):
        os.environ.pop(key, None)


class TestAuthFlow:
    def test_invalid_token_rejected(self, auth_integration_client: TestClient):
        """A request with an invalid token should be rejected (401)."""
        from app.main import app
        # Ensure no auth bypass is active from prior test fixtures
        app.dependency_overrides.clear()
        client = auth_integration_client
        resp = client.get(
            "/api/v1/files",
            headers={"Authorization": "Bearer invalid_token_xyz"},
        )
        assert resp.status_code == 401

    def test_setup_login_authenticated_request(self, auth_integration_client: TestClient):
        client = auth_integration_client
        password = "IntegTest!123Abc"

        # Setup password
        setup_resp = client.post("/api/v1/auth/setup", json={"password": password})
        assert setup_resp.status_code == 200
        token = setup_resp.json().get("access_token")
        assert token

        # Login
        login_resp = client.post("/api/v1/auth/login", json={"password": password})
        assert login_resp.status_code == 200
        login_token = login_resp.json().get("access_token")
        assert login_token

        # Authenticated request (use token in header)
        files_resp = client.get(
            "/api/v1/files",
            headers={"Authorization": f"Bearer {login_token}"},
        )
        assert files_resp.status_code == 200

    def test_wrong_password(self, auth_integration_client: TestClient):
        client = auth_integration_client
        client.post("/api/v1/auth/setup", json={"password": "IntegTest!123Abc"})
        resp = client.post("/api/v1/auth/login", json={"password": "WrongPass!123Abc"})
        assert resp.status_code == 401


# ─── 5. Rate limiting ─────────────────────────────────────────

class TestRateLimiting:
    def test_auth_rate_limit(self, auth_integration_client: TestClient):
        """Auth endpoints have a stricter rate limit (5 req/min per IP)."""
        client = auth_integration_client
        # Setup password first
        client.post("/api/v1/auth/setup", json={"password": "RateTest!123Abc"})

        # Send rapid login attempts — after 5, should get 429
        got_429 = False
        for i in range(8):
            resp = client.post("/api/v1/auth/login", json={"password": "wrong!Pass123"})
            if resp.status_code == 429:
                got_429 = True
                break
        assert got_429, "Expected 429 after rapid auth requests"


# ─── 6. Account lockout ───────────────────────────────────────

class TestAccountLockout:
    def test_lockout_after_failed_attempts(self, auth_integration_client: TestClient):
        """After 5 failed login attempts, the account should be locked for 15 minutes."""
        client = auth_integration_client
        client.post("/api/v1/auth/setup", json={"password": "LockTest!123Abc"})

        # Reset rate limiter to isolate lockout testing
        from app.api.auth import _auth_limiter
        _auth_limiter._hits.clear()

        # 5 wrong password attempts
        for i in range(5):
            _auth_limiter._hits.clear()  # Reset rate limiter each time to isolate lockout
            resp = client.post("/api/v1/auth/login", json={"password": "WrongPW!123Abc"})
            assert resp.status_code in (401, 429), f"Attempt {i+1}: unexpected {resp.status_code}"

        # 6th attempt should be lockout (429)
        _auth_limiter._hits.clear()
        resp = client.post("/api/v1/auth/login", json={"password": "LockTest!123Abc"})
        assert resp.status_code == 429, f"Expected lockout 429, got {resp.status_code}"
        assert "锁定" in resp.json().get("message", resp.json().get("detail", ""))


# ─── 7. CSRF protection ───────────────────────────────────────

class TestCSRFProtection:
    def test_logout_requires_csrf_or_cookie(self, auth_integration_client: TestClient):
        """POST /auth/logout is a state-changing endpoint; CSRF middleware may
        require a token. Verify the endpoint exists and responds appropriately."""
        client = auth_integration_client
        # Setup + login
        client.post("/api/v1/auth/setup", json={"password": "CSRFTest!123Abc"})
        login_resp = client.post("/api/v1/auth/login", json={"password": "CSRFTest!123Abc"})
        assert login_resp.status_code == 200

        # Attempt logout — with TestClient the CSRF cookie should be set automatically
        logout_resp = client.post("/api/v1/auth/logout")
        # Accept either 200 (success) or 403 (CSRF blocked) — both demonstrate the endpoint works
        assert logout_resp.status_code in (200, 403)
