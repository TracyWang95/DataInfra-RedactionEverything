# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Rate limiter unit tests."""
from __future__ import annotations

import time
from unittest.mock import patch

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

    # Exhaust ip_a
    for _ in range(20):
        upload_limiter.check(ip_a)
    assert upload_limiter.check(ip_a) is False

    # ip_b should still be allowed
    assert upload_limiter.check(ip_b) is True

    # Clean up
    with upload_limiter._lock:
        upload_limiter._hits.pop(ip_a, None)
        upload_limiter._hits.pop(ip_b, None)
