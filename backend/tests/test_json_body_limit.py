# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for differentiated request body size limits (JSON vs multipart)."""
from __future__ import annotations


def test_large_json_body_returns_413(test_client):
    """A >1MB JSON body to a non-upload endpoint should return 413."""
    # Build a JSON payload just over 1 MB
    oversized_payload = {"data": "x" * (1024 * 1024 + 1)}
    resp = test_client.post(
        "/api/v1/redaction/preview-entity-map",
        json=oversized_payload,
    )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error_code"] == "BODY_TOO_LARGE"


def test_small_json_body_passes(test_client):
    """A small JSON body should not be rejected by size middleware."""
    # This endpoint may return 422 (validation) but NOT 413
    resp = test_client.post(
        "/api/v1/redaction/preview-entity-map",
        json={"entities": [], "config": {}},
    )
    assert resp.status_code != 413
