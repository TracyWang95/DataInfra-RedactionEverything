# -*- coding: utf-8 -*-
"""端到端吞吐基准：上传语料 → 建识别 job → 提交 → 轮询完成 → 汇总性能数据。

用法：
  python benchmark_throughput.py --backend http://127.0.0.1:8000 \
      --corpus-dir /path/to/corpus --label baseline --out bench_results \
      --username bench_user --password 'Passw0rd!'

依赖后端既有能力，零埋点：
  - 每 item 性能来自 GET /jobs/{id}（_enrich_job_detail_with_performance）
  - has_text_slot_wait_ms / has_text_model_ms 等分段指标由 ocr_pipeline 现成记录
输出 {out}/{label}.json 与 {out}/{label}.md。
"""

import argparse
import concurrent.futures
import json
import mimetypes
import os
import statistics
import time

import httpx

DEFAULT_VISUAL_TYPES = ["official_seal", "signature"]
POLL_INTERVAL_SEC = 5.0


def log(msg: str) -> None:
    print(f"[bench {time.strftime('%H:%M:%S')}] {msg}", flush=True)


class BenchClient:
    def __init__(self, base: str, username: str, password: str):
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=httpx.Timeout(300.0, connect=20.0))
        self.token = self._login(username, password)
        self.http.headers["Authorization"] = f"Bearer {self.token}"

    def _login(self, username: str, password: str) -> str:
        body = {"username": username, "password": password}
        r = self.http.post(f"{self.base}/api/v1/auth/login", json=body)
        if r.status_code != 200:
            r = self.http.post(f"{self.base}/api/v1/auth/register", json=body)
        r.raise_for_status()
        return r.json()["access_token"]

    def get(self, path: str, **kw):
        r = self.http.get(f"{self.base}/api/v1{path}", **kw)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, **kw):
        r = self.http.post(f"{self.base}/api/v1{path}", **kw)
        r.raise_for_status()
        return r.json()

    def default_type_ids(self) -> list[str]:
        data = self.get("/custom-types", params={"enabled_only": True})
        types = data.get("custom_types") or []
        ids = [t["id"] for t in types if t.get("default_enabled")]
        return ids or [t["id"] for t in types[:9]]

    def upload(self, path: str, job_id: str) -> str:
        name = os.path.basename(path)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            r = self.http.post(
                f"{self.base}/api/v1/files/upload",
                files={"file": (name, f, mime)},
                data={"job_id": job_id, "upload_source": "batch"},
            )
        r.raise_for_status()
        return r.json()["file_id"] if "file_id" in r.json() else r.json()["id"]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[k]


def collect_metrics(detail: dict) -> dict:
    items = detail.get("items") or []
    page_durations: list[float] = []
    slot_waits: list[float] = []
    model_ms: list[float] = []
    duplicate_waits: list[float] = []
    recognition_walls: list[float] = []
    statuses: dict[str, int] = {}
    for item in items:
        statuses[str(item.get("status"))] = statuses.get(str(item.get("status")), 0) + 1
        wall = item.get("recognition_wall_ms") or item.get("recognition_duration_ms")
        if isinstance(wall, (int, float)) and wall > 0:
            recognition_walls.append(float(wall))
        perf = item.get("performance") or {}
        recognition = perf.get("recognition") or {}
        pages = recognition.get("pages")
        page_entries = list(pages.values()) if isinstance(pages, dict) else (pages or [])
        for page in page_entries:
            if not isinstance(page, dict):
                continue
            if isinstance(page.get("duration_ms"), (int, float)):
                page_durations.append(float(page["duration_ms"]))
            # duration_breakdown_ms 键带管线前缀（如 ocr_has.has_text_slot_wait_ms）
            breakdown = page.get("duration_breakdown_ms")
            if isinstance(breakdown, dict):
                for suffix, bucket in (
                    ("has_text_slot_wait_ms", slot_waits),
                    ("has_text_model_ms", model_ms),
                    ("has_text_duplicate_wait_ms", duplicate_waits),
                ):
                    for key, value in breakdown.items():
                        if str(key).endswith(suffix) and isinstance(value, (int, float)) and value >= 0:
                            bucket.append(float(value))
    return {
        "item_statuses": statuses,
        "pages_measured": len(page_durations),
        "page_ms_p50": percentile(page_durations, 50),
        "page_ms_p95": percentile(page_durations, 95),
        "recognition_wall_ms_p50": percentile(recognition_walls, 50),
        "recognition_wall_ms_p95": percentile(recognition_walls, 95),
        "has_slot_wait_ms_total": sum(slot_waits),
        "has_slot_wait_ms_p95": percentile(slot_waits, 95),
        "has_model_ms_total": sum(model_ms),
        "has_duplicate_wait_ms_total": sum(duplicate_waits),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", default="bench_results")
    parser.add_argument("--username", default="bench_user")
    parser.add_argument("--password", required=True)
    parser.add_argument("--upload-workers", type=int, default=4)
    parser.add_argument("--timeout-min", type=float, default=120.0)
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    files = sorted(
        os.path.join(args.corpus_dir, name)
        for name in os.listdir(args.corpus_dir)
        if os.path.isfile(os.path.join(args.corpus_dir, name))
    )
    if not files:
        raise SystemExit(f"corpus dir is empty: {args.corpus_dir}")

    client = BenchClient(args.backend, args.username, args.password)
    type_ids = client.default_type_ids()
    log(f"logged in; {len(files)} corpus files; {len(type_ids)} default text types")

    job = client.post("/jobs", json={
        "job_type": "smart_batch",
        "title": f"bench-{args.label}",
        "config": {
            "entity_type_ids": type_ids,
            "ocr_has_types": type_ids,
            "visual_feature_types": DEFAULT_VISUAL_TYPES,
            "replacement_mode": "mask",
        },
        "skip_item_review": True,
    })
    job_id = job["id"]
    log(f"job created: {job_id}")

    upload_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.upload_workers) as pool:
        list(pool.map(lambda p: client.upload(p, job_id), files))
    upload_sec = time.perf_counter() - upload_start
    log(f"uploaded {len(files)} files in {upload_sec:.1f}s")

    client.post(f"/jobs/{job_id}/submit")
    run_start = time.perf_counter()
    deadline = run_start + args.timeout_min * 60

    terminal = {"completed", "failed", "cancelled", "awaiting_review", "review_approved"}
    while True:
        detail = client.get(f"/jobs/{job_id}")
        items = detail.get("items") or []
        done = [i for i in items if str(i.get("status")).lower() in terminal]
        log(f"progress {len(done)}/{len(items)} (job status={detail.get('status')})")
        if items and len(done) == len(items):
            break
        if time.perf_counter() > deadline:
            log("TIMEOUT waiting for job; collecting partial metrics")
            break
        time.sleep(POLL_INTERVAL_SEC)

    wall_sec = time.perf_counter() - run_start
    detail = client.get(f"/jobs/{job_id}")
    metrics = collect_metrics(detail)
    pages = metrics["pages_measured"]
    result = {
        "label": args.label,
        "job_id": job_id,
        "files": len(files),
        "upload_sec": round(upload_sec, 1),
        "upload_files_per_min": round(len(files) / upload_sec * 60, 1) if upload_sec else None,
        "recognition_wall_sec": round(wall_sec, 1),
        "files_per_min": round(len(files) / wall_sec * 60, 2) if wall_sec else None,
        "pages_per_min": round(pages / wall_sec * 60, 2) if wall_sec and pages else None,
        **metrics,
    }

    json_path = os.path.join(args.out, f"{args.label}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    md_lines = [
        f"# 吞吐基准 — {args.label}",
        "",
        "| 指标 | 值 |",
        "|---|---|",
    ]
    for key, value in result.items():
        if key == "item_statuses":
            value = json.dumps(value, ensure_ascii=False)
        md_lines.append(f"| {key} | {value} |")
    with open(os.path.join(args.out, f"{args.label}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    log(f"done. wall={wall_sec:.1f}s files/min={result['files_per_min']} "
        f"pages/min={result['pages_per_min']} slot_wait_total={metrics['has_slot_wait_ms_total']:.0f}ms")
    log(f"results -> {json_path}")


if __name__ == "__main__":
    main()
