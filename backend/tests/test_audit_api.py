"""Phase 1b 审计日志查询 API：过滤/倒序/上限/权限门/CSV 导出。"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from app.core import auth
from app.core.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(auth, "_AUTH_FILE", str(tmp_path / "auth.json"))
    os.makedirs(tmp_path / "audit", exist_ok=True)
    lines = []
    for i in range(30):
        lines.append(
            json.dumps(
                {
                    "timestamp": f"2026-07-04T10:{i:02d}:00+00:00",
                    "action": "upload" if i % 2 == 0 else "commit_all",
                    "resource_type": "file" if i % 2 == 0 else "job",
                    "resource_id": f"r{i}",
                    "user": "alice" if i % 3 == 0 else "bob",
                    "detail": {"i": i, "名称": f"文件{i}.docx"},
                },
                ensure_ascii=False,
            )
        )
    (tmp_path / "audit" / "audit.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    yield


def _admin_headers() -> dict[str, str]:
    auth.create_user("boss", "Passw0rd!", role="super_admin")
    return {"Authorization": f"Bearer {auth.create_token('boss')}"}


def test_query_newest_first_with_limit():
    r = client.get("/api/v1/audit/logs", headers=_admin_headers(), params={"limit": 5})
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 5
    assert entries[0]["resource_id"] == "r29"  # newest first


def test_query_filters_combine():
    h = _admin_headers()
    r = client.get("/api/v1/audit/logs", headers=h, params={"user": "alice", "action": "upload"})
    entries = r.json()["entries"]
    assert entries and all(
        e["user"] == "alice" and e["action"] == "upload" for e in entries
    )
    r = client.get("/api/v1/audit/logs", headers=h, params={"q": "文件12"})
    assert [e["resource_id"] for e in r.json()["entries"]] == ["r12"]


def test_requires_super_admin():
    auth.create_user("emp", "Passw0rd!", role="user")
    headers = {"Authorization": f"Bearer {auth.create_token('emp')}"}
    assert client.get("/api/v1/audit/logs", headers=headers).status_code == 403


def test_csv_export_excel_friendly():
    r = client.get("/api/v1/audit/logs/export", headers=_admin_headers(), params={"user": "alice"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    assert body.splitlines()[0] == "timestamp,user,action,resource_type,resource_id,detail"
    data_lines = [line for line in body.splitlines()[1:] if line]
    assert data_lines and all(line.split(",")[1] == "alice" for line in data_lines)


def test_missing_log_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "empty"))
    r = client.get("/api/v1/audit/logs", headers=_admin_headers())
    assert r.status_code == 200 and r.json()["entries"] == []
