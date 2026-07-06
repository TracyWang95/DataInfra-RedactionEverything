"""Phase 1a 角色矩阵：normalize_role 扩展 + RoleEnforcementMiddleware 表驱动。

viewer=只读；operator=不可做审核决定；reviewer/user=既有语义；细粒度门
（require_super_admin/require_bulk_confirm）在中间件之后仍然生效。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core import auth
from app.core.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "_AUTH_FILE", str(tmp_path / "auth.json"))
    yield


def _headers(role: str) -> dict[str, str]:
    username = f"u_{role}"
    auth.create_user(username, "Passw0rd!", role=role)
    return {"Authorization": f"Bearer {auth.create_token(username)}"}


def test_normalize_role_accepts_matrix_and_rejects_junk():
    assert auth.normalize_role("admin") == "super_admin"
    for role in ("super_admin", "user", "reviewer", "operator", "viewer"):
        assert auth.normalize_role(role) == role
    with pytest.raises(HTTPException):
        auth.normalize_role("root")


# (role, method, path, expect_403)
MATRIX = [
    # viewer: any mutation on /api is denied, reads and auth self-service pass
    ("viewer", "POST", "/api/v1/files/upload", True),
    ("viewer", "DELETE", "/api/v1/files/some-id", True),
    ("viewer", "POST", "/api/v1/jobs", True),
    ("viewer", "GET", "/api/v1/files", False),
    ("viewer", "GET", "/api/v1/jobs", False),
    # operator: review decisions denied, other mutations pass the middleware
    ("operator", "POST", "/api/v1/jobs/j1/items/i1/review/commit", True),
    ("operator", "POST", "/api/v1/jobs/j1/items/i1/review/approve", True),
    ("operator", "POST", "/api/v1/jobs/j1/items/i1/review/reject", True),
    ("operator", "POST", "/api/v1/jobs/j1/review/commit-all", True),
    ("operator", "POST", "/api/v1/files/batch/export/estimate", False),
    ("operator", "POST", "/api/v1/jobs", False),
    # reviewer / legacy user: middleware never blocks
    ("reviewer", "POST", "/api/v1/jobs/j1/items/i1/review/commit", False),
    ("user", "POST", "/api/v1/jobs/j1/items/i1/review/commit", False),
    ("user", "POST", "/api/v1/jobs", False),
]


@pytest.mark.parametrize("role,method,path,expect_403", MATRIX)
def test_role_enforcement_matrix(role, method, path, expect_403):
    resp = client.request(method, path, headers=_headers(role), json={})
    if expect_403:
        assert resp.status_code == 403, f"{role} {method} {path}: {resp.status_code}"
    else:
        assert resp.status_code != 403, f"{role} {method} {path} wrongly denied: {resp.text[:120]}"


def test_fine_grained_gates_still_apply_after_middleware():
    # GET passes the middleware for a viewer, but the admin-only endpoint gate
    # must still 403 (layering: middleware never *grants* access).
    resp = client.get("/api/v1/auth/users", headers=_headers("viewer"))
    assert resp.status_code == 403
    resp = client.get("/api/v1/auth/users", headers=_headers("super_admin"))
    assert resp.status_code == 200


def test_viewer_can_still_change_own_password():
    headers = _headers("viewer")
    resp = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"old_password": "Wrong0ne!", "new_password": "NewPassw0rd!"},
    )
    # 401 wrong-old-password proves the request reached the endpoint (not 403).
    assert resp.status_code == 401


def test_commit_all_still_requires_bulk_permission_for_reviewer():
    resp = client.post("/api/v1/jobs/j1/review/commit-all", headers=_headers("reviewer"))
    # reviewer passes the role middleware but lacks the bulk_confirm grant
    assert resp.status_code == 403


def test_ner_backend_config_requires_super_admin():
    # Rewriting the global NER backend URL steers every tenant's text through
    # the configured host (SSRF + cross-tenant leak + silent under-redaction),
    # so it must be super_admin only — same gate as model_config.
    body = {"backend": "llamacpp", "llamacpp_base_url": "http://127.0.0.1:8080/v1"}
    for role in ("user", "operator", "reviewer"):
        resp = client.put("/api/v1/ner-backend", headers=_headers(role), json=body)
        assert resp.status_code == 403, f"{role} PUT ner-backend: {resp.status_code}"
    resp = client.put("/api/v1/ner-backend", headers=_headers("super_admin"), json=body)
    assert resp.status_code != 403, f"super_admin wrongly denied: {resp.text[:120]}"
