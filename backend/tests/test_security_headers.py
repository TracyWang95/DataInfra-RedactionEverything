# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Security headers middleware tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_security_headers_present(test_client: TestClient):
    """All security headers should be present on responses."""
    resp = test_client.get("/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert resp.headers.get("X-XSS-Protection") == "0"
    assert "camera=()" in resp.headers.get("Permissions-Policy", "")


def test_security_headers_on_api_endpoints(test_client: TestClient):
    """Security headers should also appear on API responses."""
    resp = test_client.get("/api/v1/files")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
