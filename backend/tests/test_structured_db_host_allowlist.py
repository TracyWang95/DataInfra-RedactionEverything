"""STRUCTURED_DB_HOST_ALLOWLIST three-state behaviour (SSRF guard)."""
import pytest

from app.services import structured_service

_PAYLOAD = {
    "engine": "postgres",
    "host": "192.168.1.50",
    "port": 5432,
    "username": "u",
    "password": "p",
    "database": "d",
}


def test_unset_allowlist_allows_any_host(monkeypatch):
    monkeypatch.setattr(structured_service.settings, "STRUCTURED_DB_HOST_ALLOWLIST", None)
    url = structured_service.build_sqlalchemy_url(_PAYLOAD)
    assert "192.168.1.50" in url


def test_host_matching_allowlist_is_allowed(monkeypatch):
    monkeypatch.setattr(
        structured_service.settings,
        "STRUCTURED_DB_HOST_ALLOWLIST",
        ["192.168.1.0/24", "db.internal"],
    )
    # CIDR match
    assert "192.168.1.50" in structured_service.build_sqlalchemy_url(_PAYLOAD)
    # exact hostname match
    assert "db.internal" in structured_service.build_sqlalchemy_url({**_PAYLOAD, "host": "db.internal"})


def test_host_outside_allowlist_is_rejected(monkeypatch):
    monkeypatch.setattr(
        structured_service.settings,
        "STRUCTURED_DB_HOST_ALLOWLIST",
        ["10.0.0.0/8", "db.internal"],
    )
    with pytest.raises(ValueError, match="STRUCTURED_DB_HOST_ALLOWLIST"):
        structured_service.build_sqlalchemy_url(_PAYLOAD)
    # sqlite URLs have no network host and are never restricted
    assert structured_service.build_sqlalchemy_url(
        {"engine": "sqlite", "sqlite_path": "C:/tmp/example.db"}
    ).startswith("sqlite:///")
