"""W2 LDAP/AD 登录：env 门控、目录 bind、组→角色映射、break-glass 与锁定语义。

FakeConnector 注入 LdapAuthenticator（不依赖 ldap3 包）；HTTP 用例复用
test_role_matrix 的 client/_AUTH_FILE 模式。
"""
from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.core import auth, ldap_auth
from app.core.config import settings
from app.core.rate_limit import RateLimiter
from app.main import app

client = TestClient(app)

ADMINS_DN = "CN=redaction-admins,DC=example,DC=com"
REVIEWERS_DN = "CN=redaction-reviewers,DC=example,DC=com"
GROUP_ROLE_MAP = f'{{"{ADMINS_DN}": "admin", "{REVIEWERS_DN}": "reviewer"}}'

BOB = {
    "password": "S3cret!pw",
    "dn": "cn=bob,ou=staff,dc=example,dc=com",
    "groups": [REVIEWERS_DN],
}


class FakeDirectory:
    """username -> {password, dn, groups}；mode 控制 ok / badcreds / unreachable。"""

    def __init__(self, users: dict[str, dict] | None = None, mode: str = "ok"):
        self.users = users if users is not None else {}
        self.mode = mode
        self.calls: list[tuple] = []
        self.search_filters: list[str] = []

    @property
    def called(self) -> bool:
        return bool(self.calls)


class FakeConnector:
    def __init__(self, directory: FakeDirectory):
        self._dir = directory

    def _check_reachable(self) -> None:
        if self._dir.mode == "unreachable":
            raise ldap_auth.LdapUnavailable("directory unreachable (fake)")

    def search(self, search_base: str, search_filter: str) -> list[dict]:
        self._dir.calls.append(("search", search_base, search_filter))
        self._dir.search_filters.append(search_filter)
        self._check_reachable()
        for username, record in self._dir.users.items():
            if ldap_auth.escape_filter_value(username) in search_filter:
                return [{"dn": record["dn"], "groups": list(record.get("groups", []))}]
        return []

    def bind(self, dn: str, password: str) -> bool:
        self._dir.calls.append(("bind", dn))
        self._check_reachable()
        if self._dir.mode == "badcreds":
            return False
        for record in self._dir.users.values():
            if record["dn"] == dn:
                return record["password"] == password
        return False


@pytest.fixture(autouse=True)
def _scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "_AUTH_FILE", str(tmp_path / "auth.json"))
    # 登录端点限速 5/min 会挡住多次尝试的用例；测试内放宽
    monkeypatch.setattr(auth_api, "_auth_limiter", RateLimiter(max_requests=10_000, window_seconds=60))
    auth._login_attempts.clear()
    # is_password_set 门槛 + break-glass 用例都需要一个本地 super_admin
    auth.create_user("bootadmin", "Passw0rd!", role="super_admin")
    yield
    auth._login_attempts.clear()


def _enable_ldap(monkeypatch, **overrides) -> None:
    values = {
        "LDAP_ENABLED": True,
        "LDAP_SERVER_URL": "ldaps://ad.example.com:636",
        "LDAP_SEARCH_BASE": "dc=example,dc=com",
        "LDAP_SERVICE_BIND_DN": "cn=svc,dc=example,dc=com",
        "LDAP_SERVICE_BIND_PASSWORD": "svc-secret",
        "LDAP_USER_FILTER": "(sAMAccountName={username})",
        "LDAP_GROUP_ROLE_MAP": GROUP_ROLE_MAP,
        "LDAP_DEFAULT_ROLE": "viewer",
        "LDAP_TIMEOUT_SECONDS": 5.0,
        "LDAP_TLS_REQUIRED": True,
        "LDAP_ROLE_SYNC": True,
        **overrides,
    }
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)


def _install_fake(monkeypatch, users: dict[str, dict] | None = None, mode: str = "ok") -> FakeDirectory:
    directory = FakeDirectory(users=users, mode=mode)
    connector = FakeConnector(directory)
    monkeypatch.setattr(
        ldap_auth,
        "_authenticator",
        ldap_auth.LdapAuthenticator(connector_factory=lambda: connector),
    )
    return directory


def _login(username: str, password: str):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def _token_role(resp) -> str:
    token = resp.json()["access_token"]
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])["role"]


# ─── (1) 门控关闭：本地登录路径原样工作，目录从不被触碰 ───


def test_ldap_disabled_local_login_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "LDAP_ENABLED", False)
    directory = _install_fake(monkeypatch, users={"bob": dict(BOB)})
    resp = _login("bootadmin", "Passw0rd!")
    assert resp.status_code == 200
    assert _token_role(resp) == "super_admin"
    assert not directory.called


# ─── (2)(3) bind 成功：组映射角色 / 未命中回落默认角色 ───


def test_ldap_bind_ok_mapped_group_role(monkeypatch):
    _enable_ldap(monkeypatch)
    directory = _install_fake(monkeypatch, users={"bob": dict(BOB)})
    resp = _login("bob", BOB["password"])
    assert resp.status_code == 200
    assert _token_role(resp) == "reviewer"
    assert directory.called
    user = auth.get_user("bob")
    assert user["auth_source"] == "ldap"
    assert not user.get("password_hash")


def test_ldap_unmapped_groups_fall_back_to_default_role(monkeypatch):
    _enable_ldap(monkeypatch, LDAP_DEFAULT_ROLE="viewer")
    carol = {"password": "C4rol!pw", "dn": "cn=carol,dc=example,dc=com", "groups": ["CN=random,DC=example,DC=com"]}
    _install_fake(monkeypatch, users={"carol": carol})
    resp = _login("carol", carol["password"])
    assert resp.status_code == 200
    assert _token_role(resp) == "viewer"


# ─── (4) 密码错误：401 且失败计数照常累加到锁定 ───


def test_ldap_wrong_password_401_and_lockout_still_works(monkeypatch):
    _enable_ldap(monkeypatch)
    _install_fake(monkeypatch, users={"bob": dict(BOB)})
    for _ in range(4):
        assert _login("bob", "Wrong!pass").status_code == 401
    # 第 5 次失败触发锁定
    assert _login("bob", "Wrong!pass").status_code == 429
    # 锁定后连正确密码也进不来
    assert _login("bob", BOB["password"]).status_code == 429


# ─── (5) 目录不可达：503、不计入锁定 ───


def test_ldap_unreachable_503_and_not_counted_toward_lockout(monkeypatch):
    _enable_ldap(monkeypatch)
    directory = _install_fake(monkeypatch, users={"bob": dict(BOB)}, mode="unreachable")
    for _ in range(6):
        resp = _login("bob", BOB["password"])
        assert resp.status_code == 503
        body = resp.json()
        assert body["error_code"] == "LDAP_UNAVAILABLE"
        assert body["message"] == "目录服务不可用，请联系管理员或使用管理员本地登录"
    # 若 503 计入锁定，上面 6 次早已 429；目录恢复后应立即可登录
    directory.mode = "ok"
    assert _login("bob", BOB["password"]).status_code == 200


# ─── (6) 不劫持本地账号 ───


def test_ldap_provision_refuses_to_hijack_local_user(monkeypatch):
    _enable_ldap(monkeypatch)
    auth.create_user("dave", "Loc4l!pass", role="user")
    dave_dir = {"password": "DirPass1!", "dn": "cn=dave,dc=example,dc=com", "groups": [REVIEWERS_DN]}
    _install_fake(monkeypatch, users={"dave": dave_dir})
    resp = _login("dave", dave_dir["password"])
    assert resp.status_code == 409
    # 本地记录原样保留：仍有密码哈希，未被打上 ldap 来源
    user = auth.get_user("dave")
    assert user["password_hash"]
    assert user.get("auth_source") != "ldap"
    assert user["role"] == "user"


# ─── (7) break-glass：本地 super_admin 在目录挂掉时仍可本地登录 ───


def test_ldap_break_glass_super_admin_logs_in_locally(monkeypatch):
    _enable_ldap(monkeypatch)
    directory = _install_fake(monkeypatch, users={}, mode="unreachable")
    resp = _login("bootadmin", "Passw0rd!")
    assert resp.status_code == 200
    assert _token_role(resp) == "super_admin"
    assert not directory.called


# ─── (8) 空密码：401 且目录从不被调用 ───


def test_ldap_empty_password_401_without_directory_call(monkeypatch):
    _enable_ldap(monkeypatch)
    directory = _install_fake(monkeypatch, users={"bob": dict(BOB)})
    assert _login("bob", "").status_code == 401
    assert _login("bob", "   ").status_code == 401
    assert not directory.called


# ─── (9) 角色重同步：组变化按 LDAP_ROLE_SYNC 决定是否落库 ───


def test_ldap_role_resync_follows_group_changes(monkeypatch):
    _enable_ldap(monkeypatch, LDAP_ROLE_SYNC=True)
    directory = _install_fake(monkeypatch, users={"bob": dict(BOB)})
    assert _token_role(_login("bob", BOB["password"])) == "reviewer"
    directory.users["bob"]["groups"] = [ADMINS_DN]
    assert _token_role(_login("bob", BOB["password"])) == "super_admin"
    assert auth.get_user("bob")["role"] == "super_admin"
    # 关掉同步后组再变，已存角色保持不动
    monkeypatch.setattr(settings, "LDAP_ROLE_SYNC", False)
    directory.users["bob"]["groups"] = [REVIEWERS_DN]
    assert _token_role(_login("bob", BOB["password"])) == "super_admin"
    assert auth.get_user("bob")["role"] == "super_admin"


# ─── (10) LDAP 用户无本地密码：门控关闭后本地路径登不进 ───


def test_ldap_user_cannot_use_local_path_when_ldap_disabled(monkeypatch):
    _enable_ldap(monkeypatch)
    _install_fake(monkeypatch, users={"bob": dict(BOB)})
    assert _login("bob", BOB["password"]).status_code == 200
    monkeypatch.setattr(settings, "LDAP_ENABLED", False)
    assert _login("bob", BOB["password"]).status_code == 401


# ─── (11) 过滤器注入：用户名按 RFC4515 转义，401 而非 500 ───


def test_ldap_filter_injection_username_is_escaped(monkeypatch):
    _enable_ldap(monkeypatch)
    directory = _install_fake(monkeypatch, users={"bob": dict(BOB)})
    resp = _login("*)(uid=*", "Whatever1!")
    assert resp.status_code == 401
    assert directory.search_filters == ["(sAMAccountName=\\2a\\29\\28uid=\\2a)"]


# ─── ldap_auth 单元用例：转义 / 映射顺序 / 直接绑定 / TLS 门槛 ───


def test_escape_filter_value_covers_rfc4515_specials():
    assert ldap_auth.escape_filter_value("*()\\\x00") == "\\2a\\28\\29\\5c\\00"
    assert ldap_auth.escape_filter_value("plain.user") == "plain.user"


def test_resolve_role_first_map_entry_wins_in_declaration_order(monkeypatch):
    _enable_ldap(
        monkeypatch,
        LDAP_GROUP_ROLE_MAP='{"g-admin": "admin", "g-view": "viewer"}',
        LDAP_DEFAULT_ROLE="user",
    )
    # 用户组顺序无关：映射声明顺序里 g-admin 在前，即使组列表先给 g-view
    assert ldap_auth.resolve_role(["g-view", "g-admin"]) == "super_admin"
    assert ldap_auth.resolve_role(["g-view"]) == "viewer"
    assert ldap_auth.resolve_role(["g-unknown"]) == "user"


def test_direct_bind_mode_uses_template_without_groups(monkeypatch):
    _enable_ldap(
        monkeypatch,
        LDAP_SEARCH_BASE="",
        LDAP_BIND_DN_TEMPLATE="uid={username},ou=people,dc=example,dc=com",
    )
    erin = {"password": "Er1n!pass", "dn": "uid=erin,ou=people,dc=example,dc=com", "groups": [ADMINS_DN]}
    directory = FakeDirectory(users={"erin": erin})
    authenticator = ldap_auth.LdapAuthenticator(connector_factory=lambda: FakeConnector(directory))
    identity = authenticator.authenticate("erin", erin["password"])
    assert identity.dn == erin["dn"]
    assert identity.groups == []  # 直接绑定模式没有搜索通道，拿不到组
    assert [c[0] for c in directory.calls] == ["bind"]


def test_tls_required_rejects_plaintext_url_before_connecting(monkeypatch):
    _enable_ldap(monkeypatch, LDAP_SERVER_URL="ldap://ad.example.com:389")
    directory = FakeDirectory(users={"bob": dict(BOB)})
    authenticator = ldap_auth.LdapAuthenticator(connector_factory=lambda: FakeConnector(directory))
    with pytest.raises(ldap_auth.LdapUnavailable):
        authenticator.authenticate("bob", BOB["password"])
    assert not directory.called
