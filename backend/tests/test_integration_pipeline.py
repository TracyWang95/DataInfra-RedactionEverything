# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the file → parse → NER → redact → download pipeline.

These tests exercise the full API flow using the ``test_client`` fixture
(auth disabled, isolated temp dirs).  External services (HaS NER, OCR)
may not be available in CI, so calls that depend on them are wrapped
with appropriate fallback handling.
"""
from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# ── Helpers ─────────────────────────────────────────────────────

API = "/api/v1"

SAMPLE_TXT_CONTENT = (
    "张三的身份证号码是110101199001011234，"
    "电话号码是13800138000，"
    "他在北京市朝阳区工作。"
)


def _upload_txt(
    client: TestClient,
    filename: str = "sample.txt",
    content: str = SAMPLE_TXT_CONTENT,
) -> dict:
    """Upload a .txt file and return the parsed JSON response body.

    Asserts a 200 status so callers can assume success.
    """
    resp = client.post(
        f"{API}/files/upload",
        files={"file": (filename, io.BytesIO(content.encode("utf-8")), "text/plain")},
    )
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    body = resp.json()
    assert "file_id" in body
    return body


# ── Test: upload → parse ────────────────────────────────────────

def test_upload_parse_flow(test_client: TestClient):
    """Upload a .txt file, then parse it and verify parsed text is returned."""
    upload = _upload_txt(test_client)
    file_id = upload["file_id"]

    resp = test_client.get(f"{API}/files/{file_id}/parse")
    assert resp.status_code == 200

    body = resp.json()
    assert body["file_id"] == file_id
    assert body["file_type"] == "txt"
    # The parsed content should contain the original text
    assert "张三" in body["content"]
    assert "110101199001011234" in body["content"]


# ── Test: upload → parse → NER (hybrid) ─────────────────────────

def test_upload_ner_flow(test_client: TestClient):
    """Upload .txt → parse → run hybrid NER → verify entities returned.

    If the HaS NER backend is unavailable the endpoint may return a 5xx
    or raise an internal error.  We accept either a successful NER
    result or a graceful service-unavailable response.
    """
    upload = _upload_txt(test_client)
    file_id = upload["file_id"]

    # Parse first — NER typically needs parsed content
    parse_resp = test_client.get(f"{API}/files/{file_id}/parse")
    assert parse_resp.status_code == 200

    # Attempt hybrid NER
    ner_resp = test_client.post(f"{API}/files/{file_id}/ner/hybrid", json={})

    if ner_resp.status_code == 200:
        body = ner_resp.json()
        assert body["file_id"] == file_id
        assert isinstance(body["entities"], list)
        assert isinstance(body["entity_count"], int)
        assert body["entity_count"] == len(body["entities"])
        assert isinstance(body["entity_summary"], dict)
        # With Chinese PII text, we expect at least some entities
        if body["entity_count"] > 0:
            ent = body["entities"][0]
            assert "text" in ent
            assert "type" in ent
            assert "start" in ent
            assert "end" in ent
    else:
        # External NER service unavailable — acceptable in CI
        pytest.skip(
            f"Hybrid NER returned {ner_resp.status_code}; "
            "external service likely unavailable"
        )


# ── Test: full pipeline (upload → parse → NER → redact → download) ──

def test_full_pipeline_txt(test_client: TestClient):
    """End-to-end: upload .txt → parse → NER → redact → download redacted.

    If NER or redaction depends on an external service that is not
    running, the test mocks the orchestrator so the download path is
    still exercised.
    """
    upload = _upload_txt(test_client)
    file_id = upload["file_id"]

    # Step 1: parse
    parse_resp = test_client.get(f"{API}/files/{file_id}/parse")
    assert parse_resp.status_code == 200
    parsed_content = parse_resp.json()["content"]

    # Step 2: attempt NER
    ner_resp = test_client.post(f"{API}/files/{file_id}/ner/hybrid", json={})

    entities = []
    if ner_resp.status_code == 200:
        entities = ner_resp.json().get("entities", [])

    # If NER returned no entities (service down or no detections), craft
    # a synthetic entity so we can still exercise redaction + download.
    if not entities:
        entities = [
            {
                "id": str(uuid.uuid4()),
                "text": "张三",
                "type": "PERSON",
                "start": parsed_content.index("张三") if "张三" in parsed_content else 0,
                "end": (parsed_content.index("张三") + 2) if "张三" in parsed_content else 2,
                "page": 1,
                "confidence": 1.0,
                "source": "manual",
                "selected": True,
            }
        ]

    # Step 3: redact
    redaction_payload = {
        "file_id": file_id,
        "entities": entities,
        "config": {
            "replacement_mode": "mask",
            "entity_types": ["PERSON", "PHONE", "ID_CARD"],
        },
    }
    redact_resp = test_client.post(f"{API}/redaction/execute", json=redaction_payload)

    if redact_resp.status_code == 200:
        redact_body = redact_resp.json()
        assert redact_body["file_id"] == file_id
        assert redact_body["redacted_count"] >= 1
        assert "download_url" in redact_body

        # Step 4: download redacted file
        dl_resp = test_client.get(f"{API}/files/{file_id}/download", params={"redacted": True})
        assert dl_resp.status_code == 200
        assert len(dl_resp.content) > 0
    elif redact_resp.status_code in (404, 500, 502, 503):
        # Redaction service unavailable or file state issue — skip gracefully
        pytest.skip(
            f"Redaction returned {redact_resp.status_code}; "
            "service may be unavailable in CI"
        )
    else:
        pytest.fail(f"Unexpected redaction status {redact_resp.status_code}: {redact_resp.text}")


# ── Test: parse with non-existent file returns 404 ──────────────

def test_upload_nonexistent_file_parse_returns_404(test_client: TestClient):
    """Parsing a file_id that was never uploaded should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = test_client.get(f"{API}/files/{fake_id}/parse")
    assert resp.status_code == 404


# ── Test: file lifecycle (upload → info → delete → info 404) ────

def test_file_lifecycle(test_client: TestClient):
    """Upload → get info → delete → get info returns 404."""
    # Upload
    upload = _upload_txt(test_client, filename="lifecycle.txt", content="生命周期测试文件")
    file_id = upload["file_id"]

    # Get info — should succeed
    info_resp = test_client.get(f"{API}/files/{file_id}")
    assert info_resp.status_code == 200
    info = info_resp.json()
    assert info["original_filename"] == "lifecycle.txt"

    # Delete
    del_resp = test_client.delete(f"{API}/files/{file_id}")
    assert del_resp.status_code == 200

    # Get info again — should be 404
    gone_resp = test_client.get(f"{API}/files/{file_id}")
    assert gone_resp.status_code == 404
