# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Rate limiter unit tests."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.core.rate_limit import RateLimiter


def test_allows_requests_within_limit():
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        assert limiter.check("ip1") is True


def test_blocks_after_limit_exceeded():
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.check("ip1")
    assert limiter.check("ip1") is False


def test_different_keys_independent():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    limiter.check("ip1")
    limiter.check("ip1")
    assert limiter.check("ip1") is False
    assert limiter.check("ip2") is True


def test_expired_entries_cleared():
    limiter = RateLimiter(max_requests=2, window_seconds=1)
    limiter.check("ip1")
    limiter.check("ip1")
    assert limiter.check("ip1") is False
    time.sleep(1.1)
    assert limiter.check("ip1") is True


def test_lru_eviction_when_max_tracked():
    """When max IPs exceeded, oldest entry should be evicted."""
    with patch("app.core.rate_limit._MAX_TRACKED_IPS", 3):
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        limiter.check("ip1")
        limiter.check("ip2")
        limiter.check("ip3")
        # ip1 is the oldest, adding ip4 should evict ip1
        limiter.check("ip4")
        assert "ip1" not in limiter._hits
        assert "ip4" in limiter._hits


# ---------------------------------------------------------------------------
# Upload-specific rate limiter
# ---------------------------------------------------------------------------

def test_upload_limiter_blocks_after_limit():
    """Upload rate limiter should reject requests exceeding the limit within the window."""
    from app.core.rate_limit import upload_limiter

    # Use a unique IP to avoid cross-test pollution
    test_ip = "upload_test_192.0.2.99"

    # Reset any existing state for this IP
    with upload_limiter._lock:
        upload_limiter._hits.pop(test_ip, None)

    limit = upload_limiter.max_requests  # 120

    # All requests up to the limit should pass
    for i in range(limit):
        assert upload_limiter.check(test_ip) is True, f"Request {i+1} should be allowed"

    # Next request should be blocked
    assert upload_limiter.check(test_ip) is False, f"Request {limit+1} should be rate-limited"

    # Clean up
    with upload_limiter._lock:
        upload_limiter._hits.pop(test_ip, None)


def test_upload_limiter_allows_different_ips():
    """Upload rate limiter tracks IPs independently."""
    from app.core.rate_limit import upload_limiter

    ip_a = "upload_test_198.51.100.1"
    ip_b = "upload_test_198.51.100.2"

    # Clean up before test
    with upload_limiter._lock:
        upload_limiter._hits.pop(ip_a, None)
        upload_limiter._hits.pop(ip_b, None)

    # Exhaust ip_a up to its limit
    limit = upload_limiter.max_requests
    for _ in range(limit):
        upload_limiter.check(ip_a)
    assert upload_limiter.check(ip_a) is False

    # ip_b should still be allowed
    assert upload_limiter.check(ip_b) is True

    # Clean up
    with upload_limiter._lock:
        upload_limiter._hits.pop(ip_a, None)
        upload_limiter._hits.pop(ip_b, None)


# ---------------------------------------------------------------------------
# X-Forwarded-For header support (proxy-aware IP detection)
# ---------------------------------------------------------------------------

def test_get_client_ip_uses_x_forwarded_for(monkeypatch):
    """get_client_ip should prefer X-Forwarded-For header when behind a trusted proxy."""
    from app.core.rate_limit import get_client_ip
    from app.core.config import get_settings
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    # TestClient peer is "testclient" — add it to trusted proxies
    monkeypatch.setattr(get_settings(), "TRUSTED_PROXIES", ["127.0.0.1", "::1", "testclient"])

    async def echo_ip(request: Request):
        return JSONResponse({"ip": get_client_ip(request)})

    app = Starlette(routes=[Route("/ip", echo_ip)])
    client = TestClient(app)

    # With X-Forwarded-For header, should return the first (leftmost) IP
    resp = client.get("/ip", headers={"X-Forwarded-For": "203.0.113.50, 70.41.3.18"})
    assert resp.json()["ip"] == "203.0.113.50"


def test_get_client_ip_falls_back_to_client_host():
    """get_client_ip should fall back to request.client.host when no X-Forwarded-For."""
    from app.core.rate_limit import get_client_ip
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def echo_ip(request: Request):
        return JSONResponse({"ip": get_client_ip(request)})

    app = Starlette(routes=[Route("/ip", echo_ip)])
    client = TestClient(app)

    # Without X-Forwarded-For, should use client.host (testclient uses "testclient")
    resp = client.get("/ip")
    ip = resp.json()["ip"]
    # TestClient sets client to testclient or 127.0.0.1 -- just verify it's not empty
    assert ip and ip != "unknown"


def test_get_client_ip_ignores_empty_forwarded_for():
    """get_client_ip should ignore empty X-Forwarded-For header."""
    from app.core.rate_limit import get_client_ip
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def echo_ip(request: Request):
        return JSONResponse({"ip": get_client_ip(request)})

    app = Starlette(routes=[Route("/ip", echo_ip)])
    client = TestClient(app)

    resp = client.get("/ip", headers={"X-Forwarded-For": ""})
    ip = resp.json()["ip"]
    assert ip and ip != "unknown"


def test_rate_limit_middleware_uses_forwarded_ip(monkeypatch):
    """RateLimitMiddleware should rate-limit based on X-Forwarded-For IP when behind trusted proxy."""
    from app.core.rate_limit import RateLimitMiddleware
    from app.core.config import get_settings
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    # TestClient peer IP is "testclient" — add it to trusted proxies for this test
    monkeypatch.setattr(get_settings(), "TRUSTED_PROXIES", ["127.0.0.1", "::1", "testclient"])

    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", ok)])
    app.add_middleware(RateLimitMiddleware, max_requests=2, window_seconds=60)
    client = TestClient(app)

    real_ip = "198.51.100.77"
    headers = {"X-Forwarded-For": real_ip}

    # First 2 requests should pass
    assert client.get("/", headers=headers).status_code == 200
    assert client.get("/", headers=headers).status_code == 200
    # Third should be rate-limited
    assert client.get("/", headers=headers).status_code == 429

    # A different forwarded IP should still be allowed
    assert client.get("/", headers={"X-Forwarded-For": "198.51.100.88"}).status_code == 200


# ---------------------------------------------------------------------------
# Untrusted proxy: X-Forwarded-For should be IGNORED
# ---------------------------------------------------------------------------

def test_get_client_ip_ignores_xff_from_untrusted_peer(monkeypatch):
    """When the direct peer IP is NOT in TRUSTED_PROXIES, X-Forwarded-For must be ignored."""
    from app.core.rate_limit import get_client_ip
    from app.core.config import get_settings
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    # Only trust loopback — TestClient peer "testclient" is NOT in the list
    monkeypatch.setattr(get_settings(), "TRUSTED_PROXIES", ["127.0.0.1", "::1"])

    async def echo_ip(request: Request):
        return JSONResponse({"ip": get_client_ip(request)})

    app = Starlette(routes=[Route("/ip", echo_ip)])
    client = TestClient(app)

    # Even though X-Forwarded-For is sent, it should be ignored
    resp = client.get("/ip", headers={"X-Forwarded-For": "203.0.113.50, 70.41.3.18"})
    ip = resp.json()["ip"]
    # Should NOT be the spoofed 203.0.113.50 — should be the direct peer
    assert ip != "203.0.113.50"
    assert ip != "70.41.3.18"


def test_get_client_ip_trusts_xff_from_trusted_proxy(monkeypatch):
    """When the direct peer IS a trusted proxy, X-Forwarded-For should be respected."""
    from app.core.rate_limit import get_client_ip
    from app.core.config import get_settings
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    # TestClient peer is "testclient" — trust it
    monkeypatch.setattr(get_settings(), "TRUSTED_PROXIES", ["127.0.0.1", "::1", "testclient"])

    async def echo_ip(request: Request):
        return JSONResponse({"ip": get_client_ip(request)})

    app = Starlette(routes=[Route("/ip", echo_ip)])
    client = TestClient(app)

    resp = client.get("/ip", headers={"X-Forwarded-For": "203.0.113.50, 70.41.3.18"})
    assert resp.json()["ip"] == "203.0.113.50"
