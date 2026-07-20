"""Enterprise LDAP / Active Directory authentication (optional, env-gated).

Single-purpose module; ``app/api/auth.py::login`` only enters it when
``settings.LDAP_ENABLED`` is true. Two directory modes:

  direct bind   LDAP_BIND_DN_TEMPLATE（如 "uid={username},ou=people,..."）
                直接用格式化后的 DN 绑定；没有搜索通道，拿不到组。
  search+bind   设置 LDAP_SEARCH_BASE 时优先：服务账号绑定后按
                LDAP_USER_FILTER 搜索（用户名经 RFC4515 转义），再用命中
                DN + 用户密码绑定；memberOf → groups。

ldap3 只在默认 connector 工厂内部懒加载：LDAP_ENABLED=false（默认）时
永远不 import；测试注入 FakeConnector。密码绝不写入日志。

Connector 契约（默认实现与测试 fake 共同遵守）：
  bind(dn, password) -> bool          凭据错误返回 False；传输故障抛 LdapUnavailable
  search(base, filter) -> list[dict]  每项 {"dn": str, "groups": list[str]}
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException

from app.core.auth import normalize_role
from app.core.config import settings

logger = logging.getLogger(__name__)


class LdapInvalidCredentials(Exception):
    """用户名/密码被目录拒绝（或目录中不存在该用户）。"""


class LdapUnavailable(Exception):
    """目录不可达或 LDAP 配置错误——不是凭据错误，不计入登录锁定。"""


@dataclass
class LdapIdentity:
    dn: str
    groups: list[str] = field(default_factory=list)


# RFC 4515 检索过滤器转义（最小集：\ ( ) * NUL）。逐字符替换，
# 反斜杠天然不会被二次转义。
_RFC4515_ESCAPES = {
    "\\": "\\5c",
    "*": "\\2a",
    "(": "\\28",
    ")": "\\29",
    "\x00": "\\00",
}


def escape_filter_value(value: str) -> str:
    """Escape *value* for safe embedding in an LDAP search filter (RFC 4515)."""
    return "".join(_RFC4515_ESCAPES.get(ch, ch) for ch in str(value))


def _parse_group_role_map() -> dict[str, str]:
    raw = (settings.LDAP_GROUP_ROLE_MAP or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LDAP_GROUP_ROLE_MAP 不是合法 JSON，组映射被忽略。")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("LDAP_GROUP_ROLE_MAP 必须是 JSON 对象，组映射被忽略。")
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


def resolve_role(groups: list[str]) -> str:
    """组→角色映射：按映射声明顺序第一个命中的组生效，否则回落 LDAP_DEFAULT_ROLE。

    组名比较大小写不敏感（AD 的 DN 语义）；映射值经 normalize_role 归一，
    非法角色值记警告并跳过该条目。
    """
    member_of = {str(group).strip().lower() for group in (groups or []) if str(group).strip()}
    for group_key, role_value in _parse_group_role_map().items():
        if str(group_key).strip().lower() not in member_of:
            continue
        try:
            return normalize_role(role_value)
        except HTTPException:
            logger.warning("LDAP_GROUP_ROLE_MAP 中组 %r 映射的角色 %r 非法，跳过。", group_key, role_value)
    return settings.LDAP_DEFAULT_ROLE


def _check_server_config() -> None:
    """配置硬门槛：URL 必须存在；要求 TLS 时必须 ldaps://；两种模式至少配一种。"""
    url = (settings.LDAP_SERVER_URL or "").strip()
    if not url:
        raise LdapUnavailable("LDAP 配置错误：LDAP_SERVER_URL 未设置。")
    if settings.LDAP_TLS_REQUIRED and not url.lower().startswith("ldaps://"):
        raise LdapUnavailable(
            "LDAP 配置错误：LDAP_TLS_REQUIRED=true 要求 ldaps:// 地址，"
            "请改用 ldaps:// 或显式设置 LDAP_TLS_REQUIRED=false。"
        )
    if not settings.LDAP_SEARCH_BASE.strip() and not settings.LDAP_BIND_DN_TEMPLATE.strip():
        raise LdapUnavailable(
            "LDAP 配置错误：需设置 LDAP_SEARCH_BASE（搜索+绑定）或 LDAP_BIND_DN_TEMPLATE（直接绑定）。"
        )


class _Ldap3Connector:
    """默认目录连接器。ldap3 在这里懒加载——只有 LDAP 真正启用并登录时才需要。"""

    def __init__(self) -> None:
        import ldap3
        from ldap3.core.exceptions import LDAPException

        self._ldap3 = ldap3
        self._ldap_error = LDAPException
        tls = None
        if settings.LDAP_CA_CERT_FILE:
            import ssl

            tls = ldap3.Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=settings.LDAP_CA_CERT_FILE)
        self._server = ldap3.Server(
            settings.LDAP_SERVER_URL,
            connect_timeout=settings.LDAP_TIMEOUT_SECONDS,
            tls=tls,
        )

    def _connection(self, user: str | None, password: str | None):
        return self._ldap3.Connection(
            self._server,
            user=user,
            password=password,
            receive_timeout=settings.LDAP_TIMEOUT_SECONDS,
        )

    def bind(self, dn: str, password: str) -> bool:
        try:
            conn = self._connection(dn, password)
            try:
                return bool(conn.bind())
            finally:
                conn.unbind()
        except self._ldap_error as exc:
            # 只透出异常类名，绝不带上凭据
            raise LdapUnavailable(f"目录服务连接失败：{exc.__class__.__name__}") from exc

    def search(self, search_base: str, search_filter: str) -> list[dict]:
        try:
            conn = self._connection(
                settings.LDAP_SERVICE_BIND_DN or None,
                settings.LDAP_SERVICE_BIND_PASSWORD or None,
            )
            try:
                if not conn.bind():
                    raise LdapUnavailable("目录服务账号绑定失败，请检查 LDAP_SERVICE_BIND_DN/PASSWORD。")
                conn.search(search_base, search_filter, attributes=["memberOf"])
                results: list[dict] = []
                for entry in conn.entries:
                    attrs = entry.entry_attributes_as_dict
                    groups = [str(group) for group in (attrs.get("memberOf") or [])]
                    results.append({"dn": str(entry.entry_dn), "groups": groups})
                return results
            finally:
                conn.unbind()
        except self._ldap_error as exc:
            raise LdapUnavailable(f"目录服务连接失败：{exc.__class__.__name__}") from exc


def _default_connector_factory() -> _Ldap3Connector:
    return _Ldap3Connector()


class LdapAuthenticator:
    """目录认证器：direct bind 或 search+bind，返回 LdapIdentity。"""

    def __init__(self, connector_factory: Callable[[], Any] | None = None) -> None:
        self._connector_factory = connector_factory or _default_connector_factory

    def authenticate(self, username: str, password: str) -> LdapIdentity:
        if not str(password or "").strip():
            # LDAP 语义下空密码是匿名 bind（会"成功"），绝不发往目录
            raise LdapInvalidCredentials("空密码不允许目录绑定。")
        _check_server_config()
        connector = self._connector_factory()
        if settings.LDAP_SEARCH_BASE.strip():
            return self._search_and_bind(connector, username, password)
        return self._direct_bind(connector, username, password)

    def _direct_bind(self, connector: Any, username: str, password: str) -> LdapIdentity:
        try:
            dn = settings.LDAP_BIND_DN_TEMPLATE.format(username=username)
        except (IndexError, KeyError) as exc:
            raise LdapUnavailable("LDAP 配置错误：LDAP_BIND_DN_TEMPLATE 必须含 {username} 占位符。") from exc
        if not connector.bind(dn, password):
            raise LdapInvalidCredentials("目录拒绝了该用户名/密码。")
        # 直接绑定模式没有搜索通道，组为空 → resolve_role 回落 LDAP_DEFAULT_ROLE
        return LdapIdentity(dn=dn, groups=[])

    def _search_and_bind(self, connector: Any, username: str, password: str) -> LdapIdentity:
        try:
            search_filter = settings.LDAP_USER_FILTER.format(username=escape_filter_value(username))
        except (IndexError, KeyError) as exc:
            raise LdapUnavailable("LDAP 配置错误：LDAP_USER_FILTER 必须含 {username} 占位符。") from exc
        entries = connector.search(settings.LDAP_SEARCH_BASE, search_filter)
        if not entries:
            raise LdapInvalidCredentials("目录中未找到该用户。")
        if len(entries) > 1:
            logger.warning("LDAP 搜索命中 %d 条记录（filter=%s），取第一条。", len(entries), search_filter)
        entry = entries[0]
        dn = str(entry.get("dn") or "")
        if not dn:
            raise LdapUnavailable("目录搜索结果缺少 DN。")
        if not connector.bind(dn, password):
            raise LdapInvalidCredentials("目录拒绝了该用户名/密码。")
        groups = [str(group) for group in (entry.get("groups") or [])]
        return LdapIdentity(dn=dn, groups=groups)


_authenticator: LdapAuthenticator | None = None


def get_ldap_authenticator() -> LdapAuthenticator:
    """进程级单例；测试通过 monkeypatch ``_authenticator`` 注入 fake connector。"""
    global _authenticator
    if _authenticator is None:
        _authenticator = LdapAuthenticator()
    return _authenticator
