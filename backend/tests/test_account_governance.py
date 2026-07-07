"""R1-2 账号治理：禁用/启用 + 护栏 + JWT 即刻失效。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core import auth as auth_core
from app.core.config import settings


@pytest.fixture
def auth_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_core, "_AUTH_FILE", str(tmp_path / "auth.json"), raising=False)
    # 部分实现用函数解析路径——保险起见清缓存
    if hasattr(auth_core, "_auth_doc_cache"):
        try:
            auth_core._auth_doc_cache.clear()  # type: ignore[attr-defined]
        except Exception:
            pass
    auth_core.create_user("boss", "Str0ng!Pass", role="super_admin")
    auth_core.create_user("worker", "Str0ng!Pass", role="user")
    return tmp_path


def test_disable_blocks_login_and_enable_restores(auth_env):
    assert auth_core.check_password("Str0ng!Pass", username="worker") == "worker"
    auth_core.set_user_disabled("boss", "worker", True)
    assert auth_core.check_password("Str0ng!Pass", username="worker") is None
    assert auth_core.is_user_disabled("worker") is True
    auth_core.set_user_disabled("boss", "worker", False)
    assert auth_core.check_password("Str0ng!Pass", username="worker") == "worker"


def test_cannot_disable_self(auth_env):
    with pytest.raises(HTTPException) as exc:
        auth_core.set_user_disabled("boss", "boss", True)
    assert exc.value.status_code == 400


def test_cannot_disable_last_super_admin(auth_env):
    auth_core.create_user("boss2", "Str0ng!Pass", role="super_admin")
    # 有两个超管时可以禁一个
    auth_core.set_user_disabled("boss2", "boss", True)
    # 只剩一个可用超管，另一个超管操作者也不能禁它
    with pytest.raises(HTTPException) as exc:
        auth_core.set_user_disabled("boss", "boss2", True)
    assert exc.value.status_code == 400


def test_list_users_reports_disabled(auth_env):
    auth_core.set_user_disabled("boss", "worker", True)
    users = {u["username"]: u for u in auth_core.list_users()}
    assert users["worker"]["disabled"] is True
    assert users["boss"]["disabled"] is False
