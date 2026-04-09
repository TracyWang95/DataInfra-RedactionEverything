# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for POST /api/v1/jobs/batch-details — batch job detail retrieval.

This endpoint replaces the N+1 pattern where the frontend calls
GET /jobs/{id} once per expanded job.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient


def _create_job(client: TestClient, job_type: str = "text_batch", title: str = "test") -> str:
    """Helper: create a draft job, return its ID."""
    resp = client.post("/api/v1/jobs", json={"job_type": job_type, "title": title})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


class TestBatchDetailsEndpoint:
    """POST /api/v1/jobs/batch-details"""

    def test_returns_details_for_multiple_jobs(self, test_client: TestClient):
        id1 = _create_job(test_client, title="job-a")
        id2 = _create_job(test_client, title="job-b")

        resp = test_client.post("/api/v1/jobs/batch-details", json={"ids": [id1, id2]})
        assert resp.status_code == 200
        body = resp.json()
        assert "jobs" in body
        assert len(body["jobs"]) == 2
        returned_ids = {j["id"] for j in body["jobs"]}
        assert returned_ids == {id1, id2}

    def test_returns_items_in_each_detail(self, test_client: TestClient):
        jid = _create_job(test_client)
        # Add an item to the job
        upload = test_client.post(
            "/api/v1/files/upload",
            files={"file": ("t.txt", io.BytesIO(b"hi"), "text/plain")},
        )
        file_id = upload.json()["file_id"]
        test_client.post(f"/api/v1/jobs/{jid}/items", json={"file_id": file_id})

        resp = test_client.post("/api/v1/jobs/batch-details", json={"ids": [jid]})
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        assert len(jobs) == 1
        assert "items" in jobs[0]
        assert len(jobs[0]["items"]) == 1

    def test_skips_nonexistent_ids(self, test_client: TestClient):
        real_id = _create_job(test_client)
        resp = test_client.post(
            "/api/v1/jobs/batch-details",
            json={"ids": [real_id, "nonexistent-uuid-1234"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["jobs"]) == 1
        assert body["jobs"][0]["id"] == real_id

    def test_empty_ids_returns_empty_list(self, test_client: TestClient):
        resp = test_client.post("/api/v1/jobs/batch-details", json={"ids": []})
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []

    def test_deduplicates_ids(self, test_client: TestClient):
        jid = _create_job(test_client)
        resp = test_client.post(
            "/api/v1/jobs/batch-details",
            json={"ids": [jid, jid, jid]},
        )
        assert resp.status_code == 200
        assert len(resp.json()["jobs"]) == 1

    def test_rejects_too_many_ids(self, test_client: TestClient):
        fake_ids = [f"fake-{i}" for i in range(51)]
        resp = test_client.post("/api/v1/jobs/batch-details", json={"ids": fake_ids})
        assert resp.status_code == 422 or resp.status_code == 400

    def test_rejects_missing_ids_field(self, test_client: TestClient):
        resp = test_client.post("/api/v1/jobs/batch-details", json={})
        assert resp.status_code == 422
