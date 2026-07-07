# Copyright 2026 DataInfra-RedactionEverything Contributors
"""万级恢复验证/取证：5000 items 任务点「继续审阅」——网络计数+步骤高亮。"""
from __future__ import annotations

import time
from collections import Counter

from common import BASE_URL, login, run

JOB_ID = "c7e53319-80f0-44e3-8769-68f2a51eb411"


def scenario(page) -> None:
    req_counter: Counter[str] = Counter()
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(f"pageerror: {str(err)[:400]}"))
    page.on(
        "console",
        lambda m: errors.append(f"console.error: {m.text[:400]}") if m.type == "error" else None,
    )

    def on_request(req):
        url = req.url
        if "/api/" in url:
            path = url.split("/api/v1/")[-1].split("?")[0]
            # 归并 id 段
            parts = [p if len(p) < 30 else "{id}" for p in path.split("/")]
            req_counter["/".join(parts)] += 1

    page.on("request", on_request)

    login(page)
    page.goto(f"{BASE_URL}/jobs", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    req_counter.clear()

    row = page.locator(f'[data-testid="job-row-{JOB_ID}"]')
    arrow = row.locator("a").first
    t0 = time.time()
    arrow.click()

    for _ in range(30):
        page.wait_for_timeout(2000)
        elapsed = time.time() - t0
        body = page.inner_text("body")
        review_ready = "快捷键" in body and "确认匿名化" in body and "/5000" in body
        if review_ready:
            print(f"  [ok] review ready in {elapsed:.1f}s")
            break
        if int(elapsed) in (6, 20, 40, 58):
            top = req_counter.most_common(5)
            print(f"  [t+{elapsed:.0f}s] top requests: {top}")
    else:
        print("  [FAIL] not ready after 60s")
        # 步骤条当前态：抓每个步骤指示器的 class/文本
        try:
            steps = page.evaluate(
                "() => [...document.querySelectorAll('[data-testid^=\"wizard-step\"], [class*=\"step\"]')]"
                ".slice(0,12).map(n => n.textContent?.slice(0,12))"
            )
            print(f"  step indicators: {steps}")
        except Exception:
            pass
        page.screenshot(path=".artifacts/bigjob_fail.png", full_page=False)

    for e in errors[:10]:
        print(f"  [console] {e}")
    print("\n  request totals since click:")
    for path, n in req_counter.most_common(8):
        print(f"    {n:6d}  {path}")


run(scenario)
