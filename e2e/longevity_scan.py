# Copyright 2026 DataInfra-RedactionEverything Contributors
"""F2-2 长会话取证：20 轮全路由循环导航，JS 堆增长曲线。

判定：末轮堆 < 首轮×2 且绝对值 < 300MB 视为无泄漏迹象（SPA 常态波动内）。
"""
from __future__ import annotations

from common import BASE_URL, login, run

ROUTES = ["/", "/single", "/batch", "/structured/files", "/history", "/jobs", "/settings"]
LOOPS = 20


def heap_mb(page) -> float:
    return page.evaluate("() => (performance.memory?.usedJSHeapSize || 0) / 1048576")


def scenario(page) -> None:
    login(page)
    # CDP 强制 GC：不带 --expose-gc 时 window.gc 不存在，未 GC 堆会自然堆积造成假阳性
    cdp = page.context.new_cdp_session(page)
    samples: list[float] = []
    for i in range(LOOPS):
        for route in ROUTES:
            page.goto(f"{BASE_URL}{route}", wait_until="domcontentloaded")
            page.wait_for_timeout(350)
        cdp.send("HeapProfiler.collectGarbage")
        page.wait_for_timeout(300)
        mb = heap_mb(page)
        samples.append(mb)
        if i % 5 == 0 or i == LOOPS - 1:
            print(f"  [loop {i + 1:02d}] heap={mb:.1f}MB")
    first_avg = sum(samples[:3]) / 3
    last_avg = sum(samples[-3:]) / 3
    growth = last_avg / max(first_avg, 1)
    print(f"\n  first3={first_avg:.1f}MB last3={last_avg:.1f}MB growth×{growth:.2f}")
    assert last_avg < 300, f"absolute heap too high: {last_avg:.1f}MB"
    assert growth < 2.0, f"heap doubled over {LOOPS} loops: ×{growth:.2f} — leak suspected"
    print("  [ok] no leak signature over 140 navigations")


run(scenario)
