# Copyright 2026 DataInfra-RedactionEverything Contributors
"""复现 PM 问题：任务中心点「继续审阅」落在第 1 步。

API 造 awaiting_review 任务 → headed 从 /jobs 点箭头 → 取证落地 URL/步骤/console。
"""
from __future__ import annotations

import io
import time

import httpx

from common import BASE_URL, PASSWORD, USERNAME, login, run

JOB_TITLE = "repro-continue-review"


def make_awaiting_job() -> str:
    with httpx.Client(base_url=BASE_URL, timeout=120.0, trust_env=False) as h:
        r = h.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
        if r.status_code == 429:
            time.sleep(65)
            r = h.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
        assert r.status_code == 200, r.text[:200]
        h.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

        job = h.post("/api/v1/jobs", json={"job_type": "smart_batch", "title": JOB_TITLE})
        assert job.status_code == 200, job.text[:300]
        job_id = job.json()["id"]

        for i in range(2):
            up = h.post(
                "/api/v1/files/upload",
                data={"job_id": job_id},
                files={"file": (f"rcr_{i}.txt", io.BytesIO(f"张三 电话 1380000111{i}".encode()), "text/plain")},
            )
            assert up.status_code == 200, up.text[:300]

        sub = h.post(f"/api/v1/jobs/{job_id}/submit", json={})
        assert sub.status_code == 200, sub.text[:300]

        for _ in range(60):
            time.sleep(3)
            d = h.get(f"/api/v1/jobs/{job_id}?performance=false").json()
            if d.get("status") == "awaiting_review":
                return job_id
        raise AssertionError(f"job never reached awaiting_review: {d.get('status')}")


def scenario(page) -> None:
    job_id = make_awaiting_job()
    print(f"  [setup] awaiting job {job_id[:8]}")

    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(f"pageerror: {str(err)[:300]}"))
    page.on(
        "console",
        lambda m: errors.append(f"console.error: {m.text[:300]}") if m.type == "error" else None,
    )

    login(page)
    page.goto(f"{BASE_URL}/jobs", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    row = page.locator(f'[data-testid="job-row-{job_id}"]')
    assert row.count() > 0, "job row not found on /jobs"
    arrow = row.locator("a").first
    href = arrow.get_attribute("href")
    print(f"  [evidence] arrow href = {href}")
    arrow.click()
    page.wait_for_timeout(6000)

    final_url = page.url
    print(f"  [evidence] landed URL = {final_url}")
    # 步骤指示器：找当前高亮步（向导步骤条），粗取页面可见文本判定
    body = page.inner_text("body")[:400]
    on_review = page.locator('[data-testid="review-queue-status"]').count() > 0 or "审阅确认" in body
    step1_banner = "配置清单已转为只读" in page.inner_text("body")
    print(f"  [evidence] review surface visible={on_review} step1_locked_banner={step1_banner}")
    for e in errors[:8]:
        print(f"  [console] {e}")

    if "step=4" in (href or "") and not final_url.endswith(href or "@@"):
        print(f"  [evidence] URL CHANGED after navigation: {href} -> {final_url}")
    assert on_review and not step1_banner, "REPRODUCED: landed on step-1 instead of review"
    print("  [ok] continue-review lands on step 4")


run(scenario)
