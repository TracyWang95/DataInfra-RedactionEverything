#!/usr/bin/env python3
"""Smoke-test API endpoints from docs/openapi.json against a running backend."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "docs" / "openapi.json"
DEFAULT_BASE_URL = "http://8.134.38.29:8081"
TIMEOUT = 60.0

# Endpoints that mutate global state or are unsafe for automated smoke runs.
SKIP_OPERATIONS = {
    ("POST", "/api/v1/auth/setup"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/change-password"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/revoke-all"),
    ("POST", "/api/v1/custom-types/reset"),
    ("POST", "/api/v1/vision-pipelines/reset"),
    ("POST", "/api/v1/model-config/reset"),
    ("POST", "/api/v1/presets/import"),
    ("POST", "/api/v1/safety/cleanup"),
}

# 破坏性 DELETE 使用占位 ID，避免删掉 smoke 流程依赖的真实 Job/File。
DELETE_USE_DUMMY_PATHS = (
    "/api/v1/files/{file_id}",
    "/api/v1/jobs/{job_id}",
    "/api/v1/presets/{preset_id}",
    "/api/v1/custom-types/{type_id}",
    "/api/v1/model-config/{config_id}",
    "/api/v1/jobs/{job_id}/items/{item_id}",
    "/api/v1/structured/connections/{connection_id}",
    "/api/v1/vision-pipelines/{mode}/types/{type_id}",
)

ROUTE_OK_STATUSES = set(range(200, 500)) - {500, 502, 503, 504}


@dataclass
class Context:
    base_url: str
    file_id: str | None = None
    job_id: str | None = None
    completed_job_id: str | None = None
    structured_job_id: str | None = None
    item_id: str | None = None
    preset_id: str | None = None
    type_id: str | None = None
    config_id: str | None = None
    mode: str | None = None
    dataset_id: str | None = None
    connection_id: str | None = None
    source_id: str | None = None
    task_type: str = "ocr"


@dataclass
class Result:
    method: str
    path: str
    url: str
    status: int | None
    ok: bool
    note: str = ""
    category: str = "route"


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    def add(self, result: Result) -> None:
        self.results.append(result)


def load_openapi() -> dict[str, Any]:
    return json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))


def substitute_path(path: str, ctx: Context) -> str:
    dummy = "00000000-0000-0000-0000-000000000001"
    draft_ops = ("/submit", "/cancel", "/requeue-failed")
    if any(path.endswith(suffix) for suffix in draft_ops):
        job_for_path = ctx.job_id or dummy
    elif "/structured/jobs/" in path:
        job_for_path = ctx.structured_job_id or dummy
    elif "/jobs/" in path:
        job_for_path = ctx.completed_job_id or ctx.job_id or dummy
    else:
        job_for_path = ctx.job_id or dummy
    mapping = {
        "file_id": ctx.file_id or dummy,
        "job_id": job_for_path,
        "item_id": ctx.item_id or dummy,
        "preset_id": ctx.preset_id or dummy,
        "type_id": ctx.type_id or dummy,
        "config_id": ctx.config_id or dummy,
        "mode": ctx.mode or "grounding",
        "dataset_id": ctx.dataset_id or dummy,
        "connection_id": ctx.connection_id or dummy,
        "source_id": ctx.source_id or dummy,
        "task_type": ctx.task_type,
    }
    out = path
    for key, value in mapping.items():
        out = out.replace("{" + key + "}", value)
    return out


def default_body(method: str, path: str) -> Any:
    if method not in {"POST", "PUT", "PATCH"}:
        return None
    if path.endswith("/auth/login"):
        return {"username": "admin", "password": "invalid-for-smoke-test"}
    if path.endswith("/files/upload"):
        return None
    if path.endswith("/structured/files"):
        return None
    if path.endswith("/ner/hybrid") or path.endswith("/ner"):
        return {"entity_type_ids": None}
    if path.endswith("/vision"):
        return {}
    if path.endswith("/preview-image"):
        return {"bounding_boxes": [], "config": {}}
    if path.endswith("/redaction/execute"):
        return {
            "file_id": "00000000-0000-0000-0000-000000000001",
            "entities": [],
            "bounding_boxes": [],
            "config": {"replacement_mode": "smart"},
        }
    if path.endswith("/redaction/preview-map"):
        return {"text": "test", "entities": [], "config": {"replacement_mode": "smart"}}
    if path.endswith("/jobs") and method == "POST":
        return {"title": "smoke-test", "job_type": "smart_batch", "config": {}}
    if "/jobs/" in path and path.endswith("/items") and method == "POST":
        return {"file_id": "00000000-0000-0000-0000-000000000001"}
    if path.endswith("/files/batch/download"):
        return {"file_ids": [], "redacted": True}
    if path.endswith("/custom-types/regex-test"):
        return {"pattern": r"\d+", "text": "123"}
    if path.endswith("/structured/connections/test"):
        return {"db_type": "sqlite", "database": ":memory:"}
    if path.endswith("/structured/jobs"):
        return {"dataset_id": "00000000-0000-0000-0000-000000000001", "output_format": "csv"}
    if path.endswith("/ner-backend/test"):
        return {}
    if "/model-config/test/" in path:
        return {}
    if path.endswith("/structured/connections") and method == "POST":
        return {"name": "smoke", "db_type": "sqlite", "database": ":memory:"}
    if "/policy" in path:
        return {"columns": []}
    if "/profile" in path:
        return {}
    if "/review-draft" in path and method == "PUT":
        return {"entities": [], "bounding_boxes": []}
    if "/review/commit" in path:
        return {
            "entities": [],
            "bounding_boxes": [],
            "config": {"replacement_mode": "smart"},
        }
    if "/review/approve" in path or "/review/reject" in path:
        return {}
    if path.endswith("/batch-details"):
        return {"job_ids": []}
    if path.endswith("/custom-types") and method == "POST":
        return {
            "name": "smoke-type",
            "label": "Smoke",
            "regex": r"\d+",
            "category": "custom",
        }
    if "/presets/" in path and method == "PUT":
        return {"name": "smoke-preset", "config": {}}
    if path.endswith("/model-config") and method == "POST":
        return {"name": "smoke-config", "task_type": "ocr", "config": {}}
    if "/toggle" in path:
        return {}
    if path.endswith("/submit") or path.endswith("/cancel") or path.endswith("/requeue-failed"):
        return {}
    return {}


def classify(status: int | None, error: str | None = None) -> tuple[bool, str, str]:
    if error:
        return False, error, "fail"
    if status is None:
        return False, "no status", "fail"
    if status in {200, 201, 204}:
        return True, "success", "ok"
    if status in ROUTE_OK_STATUSES:
        return True, f"reachable ({status})", "route"
    if status in {500, 502, 503, 504}:
        return False, f"server error ({status})", "fail"
    return False, f"unexpected ({status})", "fail"


def request_endpoint(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    json_body: Any = None,
    files: Any = None,
    stream: bool = False,
) -> tuple[int | None, str | None]:
    try:
        if stream:
            with client.stream(method, url, json=json_body, timeout=TIMEOUT) as resp:
                next(resp.iter_bytes(1024), b"")
                return resp.status_code, None
        if files is not None:
            resp = client.request(method, url, files=files, timeout=TIMEOUT)
        elif json_body is not None:
            resp = client.request(method, url, json=json_body, timeout=TIMEOUT)
        else:
            resp = client.request(method, url, timeout=TIMEOUT)
        return resp.status_code, None
    except httpx.RequestError as exc:
        return None, str(exc)


def seed_context(client: httpx.Client, ctx: Context, report: Report) -> None:
    """Run minimal flows to obtain real IDs for dependent endpoints."""

    def record(method: str, path: str, status: int | None, note: str, ok: bool) -> None:
        report.add(
            Result(
                method=method,
                path=path,
                url=f"{ctx.base_url}{path}",
                status=status,
                ok=ok,
                note=note,
                category="flow" if ok else "fail",
            )
        )

    # Health
    status, err = request_endpoint(client, "GET", f"{ctx.base_url}/health")
    ok, note, _ = classify(status, err)
    record("GET", "/health", status, note, ok)

    status, err = request_endpoint(client, "GET", f"{ctx.base_url}/health/services")
    ok, note, _ = classify(status, err)
    record("GET", "/health/services", status, note, ok)

    # Discover list IDs
    for path, key, extractor in [
        ("/api/v1/presets", "preset_id", lambda d: (d[0]["id"] if d else None)),
        ("/api/v1/custom-types", "type_id", lambda d: (d[0]["id"] if d else None)),
        ("/api/v1/model-config", "config_id", lambda d: (d[0]["id"] if d else None)),
        ("/api/v1/vision-pipelines", "mode", lambda d: (next(iter(d.keys())) if isinstance(d, dict) and d else None)),
        ("/api/v1/structured/datasets", "dataset_id", lambda d: (d[0]["id"] if d else None)),
        ("/api/v1/structured/sources", "source_id", lambda d: (d[0]["id"] if d else None)),
        ("/api/v1/structured/connections", "connection_id", lambda d: (d[0]["id"] if d else None)),
    ]:
        try:
            resp = client.get(f"{ctx.base_url}{path}", timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "items" in data:
                    data = data["items"]
                value = extractor(data)
                if value:
                    setattr(ctx, key, value)
        except Exception:
            pass

    try:
        resp = client.get(f"{ctx.base_url}/api/v1/jobs", timeout=TIMEOUT)
        if resp.status_code == 200:
            jobs = resp.json().get("jobs", resp.json() if isinstance(resp.json(), list) else [])
            for job in jobs:
                if job.get("status") == "completed" and job.get("job_type") == "smart_batch":
                    jid = job.get("id")
                    if not jid:
                        continue
                    detail = client.get(f"{ctx.base_url}/api/v1/jobs/{jid}", timeout=TIMEOUT)
                    if detail.status_code == 200:
                        ctx.completed_job_id = jid
                        break
            for job in jobs:
                if job.get("status") == "completed" and job.get("job_type") == "structured_batch":
                    jid = job.get("id")
                    if not jid:
                        continue
                    detail = client.get(f"{ctx.base_url}/api/v1/jobs/{jid}", timeout=TIMEOUT)
                    if detail.status_code == 200:
                        ctx.structured_job_id = jid
                        break
            if jobs and not ctx.job_id:
                ctx.job_id = jobs[0].get("id")
            if ctx.completed_job_id:
                detail = client.get(
                    f"{ctx.base_url}/api/v1/jobs/{ctx.completed_job_id}",
                    timeout=TIMEOUT,
                )
                if detail.status_code == 200:
                    items = detail.json().get("items") or []
                    if items:
                        ctx.item_id = items[0].get("id") or items[0].get("item_id")
    except Exception:
        pass

    # Upload a tiny text file for file-scoped routes
    sample = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    sample.write("张三的手机号是13800138000，邮箱test@example.com\n")
    sample.close()
    try:
        with open(sample.name, "rb") as fh:
            resp = client.post(
                f"{ctx.base_url}/api/v1/files/upload",
                files={"file": ("smoke.txt", fh, "text/plain")},
                data={"upload_source": "playground"},
                timeout=TIMEOUT,
            )
        status = resp.status_code
        ok, note, _ = classify(status)
        record("POST", "/api/v1/files/upload", status, note, ok)
        if status == 200:
            ctx.file_id = resp.json().get("file_id")
    finally:
        os.unlink(sample.name)

    if ctx.file_id:
        for method, path in [
            ("GET", f"/api/v1/files/{ctx.file_id}/parse"),
            ("POST", f"/api/v1/files/{ctx.file_id}/ner/hybrid"),
        ]:
            body = {"entity_type_ids": None} if method == "POST" else None
            status, err = request_endpoint(
                client,
                method,
                f"{ctx.base_url}{path}",
                json_body=body,
            )
            ok, note, _ = classify(status, err)
            record(method, path.replace(ctx.file_id, "{file_id}"), status, note, ok)

    # Create draft job only if none exists
    if not ctx.job_id:
        status, err = request_endpoint(
            client,
            "POST",
            f"{ctx.base_url}/api/v1/jobs",
            json_body={"title": "smoke-job", "job_type": "smart_batch", "config": {}},
        )
        ok, note, _ = classify(status, err)
        record("POST", "/api/v1/jobs", status, note, ok)
        if status in {200, 201}:
            try:
                resp = client.post(
                    f"{ctx.base_url}/api/v1/jobs",
                    json={"title": "smoke-job", "job_type": "smart_batch", "config": {}},
                    timeout=TIMEOUT,
                )
                if resp.status_code in {200, 201}:
                    ctx.job_id = resp.json().get("id")
            except Exception:
                pass


def run_openapi_smoke(client: httpx.Client, ctx: Context, report: Report) -> None:
    spec = load_openapi()
    paths: dict[str, Any] = spec.get("paths", {})

    for path, methods in sorted(paths.items()):
        for method, _detail in methods.items():
            method = method.upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            op = (method, path)
            if op in SKIP_OPERATIONS:
                report.add(
                    Result(method, path, "", None, True, "skipped (unsafe)", "skip")
                )
                continue

            if path == "/api/v1/structured/jobs/{job_id}/export" and not ctx.structured_job_id:
                report.add(
                    Result(method, path, "", None, True, "skipped (no structured job)", "skip")
                )
                continue

            resolved = substitute_path(path, ctx)
            if method == "DELETE" and path in DELETE_USE_DUMMY_PATHS:
                resolved = path
                for key, value in {
                    "file_id": "00000000-0000-0000-0000-000000000001",
                    "job_id": "00000000-0000-0000-0000-000000000001",
                    "preset_id": "00000000-0000-0000-0000-000000000001",
                    "type_id": "00000000-0000-0000-0000-000000000001",
                    "config_id": "00000000-0000-0000-0000-000000000001",
                    "item_id": "00000000-0000-0000-0000-000000000001",
                    "connection_id": "00000000-0000-0000-0000-000000000001",
                    "mode": "grounding",
                }.items():
                    resolved = resolved.replace("{" + key + "}", value)
            url = f"{ctx.base_url}{resolved}"
            body = default_body(method, path)
            files = None
            stream = path.endswith("/stream")

            if path.endswith("/files/upload") and method == "POST":
                tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
                tmp.write("smoke upload\n")
                tmp.close()
                try:
                    with open(tmp.name, "rb") as fh:
                        files = {
                            "file": ("smoke-openapi.txt", fh, "text/plain"),
                            "upload_source": (None, "playground"),
                        }
                        status, err = request_endpoint(client, method, url, files=files)
                finally:
                    os.unlink(tmp.name)
            elif path.endswith("/structured/files") and method == "POST":
                csv_tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
                csv_tmp.write("name,phone\nAlice,13800138000\n")
                csv_tmp.close()
                try:
                    with open(csv_tmp.name, "rb") as fh:
                        files = {"file": ("smoke.csv", fh, "text/csv")}
                        status, err = request_endpoint(client, method, url, files=files)
                        if status == 200:
                            try:
                                resp = client.post(url, files={"file": ("smoke.csv", open(csv_tmp.name, "rb"), "text/csv")}, timeout=TIMEOUT)
                                ctx.dataset_id = resp.json().get("dataset_id") or ctx.dataset_id
                            except Exception:
                                pass
                finally:
                    os.unlink(csv_tmp.name)
            else:
                status, err = request_endpoint(
                    client,
                    method,
                    url,
                    json_body=body,
                    stream=stream,
                )

            ok, note, category = classify(status, err)
            report.add(Result(method, path, url, status, ok, note, category))


def print_report(report: Report, ctx: Context) -> int:
    groups = {"ok": [], "route": [], "skip": [], "flow": [], "fail": []}
    for item in report.results:
        groups.setdefault(item.category, []).append(item)

    # Deduplicate openapi checks by method/path/status
    seen: set[tuple[str, str, int | None]] = set()
    unique_results: list[Result] = []
    for item in reversed(report.results):
        key = (item.method, item.path, item.status)
        if key in seen:
            continue
        seen.add(key)
        unique_results.append(item)
    unique_results.reverse()

    print(f"\n{'=' * 72}")
    print("API Smoke Test Report")
    print(f"{'=' * 72}")
    print(f"Total checks: {len(unique_results)}")
    print(f"  OK (2xx):     {len(groups.get('ok', []))}")
    print(f"  Route reachable (4xx etc.): {len(groups.get('route', []))}")
    print(f"  Flow seeded:  {len(groups.get('flow', []))}")
    print(f"  Skipped:      {len(groups.get('skip', []))}")
    print(f"  Failed:       {len(groups.get('fail', []))}")

    if groups.get("fail"):
        print(f"\n--- Failures ({len(groups['fail'])}) ---")
        shown: set[tuple[str, str]] = set()
        for item in groups["fail"]:
            key = (item.method, item.path)
            if key in shown:
                continue
            shown.add(key)
            print(f"  {item.method:6} {item.path:55} -> {item.status} {item.note}")

    print(f"\n--- Core flow ---")
    print(f"  health:          http://8.134.38.29:8081/health")
    print(f"  file_id:         {ctx.file_id or '-'}")
    print(f"  draft job_id:    {ctx.job_id or '-'}")
    print(f"  completed job:   {ctx.completed_job_id or '-'}")
    print(f"  structured job:  {ctx.structured_job_id or '-'}")

    print(f"\n{'=' * 72}")
    failed = len(groups.get("fail", []))
    if failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS (all endpoints reachable)")
    return 0


def main() -> int:
    base_url = os.environ.get("BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    ctx = Context(base_url=base_url)
    report = Report()

    print(f"Target: {base_url}")
    print(f"OpenAPI: {OPENAPI_PATH}")
    started = time.time()

    with httpx.Client(follow_redirects=True) as client:
        seed_context(client, ctx, report)
        run_openapi_smoke(client, ctx, report)

    print(f"Elapsed: {time.time() - started:.1f}s")
    if ctx.file_id:
        print(f"Seeded file_id: {ctx.file_id}")
    if ctx.job_id:
        print(f"Seeded job_id: {ctx.job_id}")
    if ctx.completed_job_id:
        print(f"Seeded completed_job_id: {ctx.completed_job_id}")
    if ctx.structured_job_id:
        print(f"Seeded structured_job_id: {ctx.structured_job_id}")
    return print_report(report, ctx)


if __name__ == "__main__":
    sys.exit(main())
