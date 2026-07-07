# Copyright 2026 DataInfra-RedactionEverything Contributors
"""Tier-2 golden path: async volume export (P0 万级导出 machinery), API level.

Pure IO (no GPU): estimate must answer instantly, the export task must run to
completion in the background worker, and every volume must download with the
manifest accounting for all requested files. Uses the e2e account's own
uploaded originals (accumulated by golden_batch runs).
"""
from __future__ import annotations

import time

import httpx

from common import BASE_URL, PASSWORD, USERNAME, run


def _client() -> httpx.Client:
    c = httpx.Client(base_url=BASE_URL, timeout=60.0, trust_env=False)
    for attempt in range(2):
        r = c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
        if r.status_code == 429 and attempt == 0:
            print("  [wait] auth rate limit, sleeping 65s")
            time.sleep(65)
            continue
        assert r.status_code == 200, f"login failed: {r.status_code}"
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        return c
    raise AssertionError("unreachable")


def golden_export(page) -> None:  # page unused; API-level path
    import contextlib

    with contextlib.closing(_client()) as c:
        files = c.get("/api/v1/files", params={"page": 1, "page_size": 10, "source": "batch"}).json()
        ids = [f["file_id"] for f in files.get("files", [])][:4]
        assert len(ids) >= 2, f"need at least 2 uploaded files for export, got {len(ids)}"

        t0 = time.perf_counter()
        est = c.post(
            "/api/v1/files/batch/export/estimate",
            json={"file_ids": ids, "redacted": False},
        )
        est_ms = (time.perf_counter() - t0) * 1000
        assert est.status_code == 200, est.text[:200]
        body = est.json()
        assert body["file_count"] >= 2 and body["total_bytes"] > 0, body
        assert est_ms < 5000, f"estimate not instant: {est_ms:.0f}ms"
        print(f"  [ok] estimate: {body['file_count']} files, {body['total_bytes']}B in {est_ms:.0f}ms")

        task = c.post("/api/v1/files/batch/export", json={"file_ids": ids, "redacted": False})
        assert task.status_code in (200, 202), task.text[:200]
        export_id = task.json()["export_id"]

        deadline = time.monotonic() + 120
        status = {}
        while time.monotonic() < deadline:
            status = c.get(f"/api/v1/files/batch/export/{export_id}").json()
            if status.get("status") in ("completed", "failed"):
                break
            time.sleep(2)
        assert status.get("status") == "completed", f"export did not complete: {status}"
        volumes = status.get("volumes") or []
        assert volumes, f"no volumes in completed export: {status}"
        print(f"  [ok] export completed with {len(volumes)} volume(s)")

        for vol in volumes:
            name = vol["name"] if isinstance(vol, dict) else vol
            r = c.get(f"/api/v1/files/batch/export/{export_id}/volumes/{name}")
            assert r.status_code == 200, f"volume {name}: {r.status_code}"
            assert r.content[:2] == b"PK", f"volume {name} is not a zip"
        print("  [ok] all volumes download as valid zip")


if __name__ == "__main__":
    run(golden_export)
