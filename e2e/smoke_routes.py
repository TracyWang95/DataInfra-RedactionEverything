# Copyright 2026 DataInfra-RedactionEverything Contributors
"""Tier-1 smoke: login, every top-level route renders without an error screen.

Cheap (no GPU work) — safe to run against the production tunnel at any time.
"""
from __future__ import annotations

from common import BASE_URL, login, run

ROUTES = [
    "/",
    "/single",
    "/batch",
    "/structured",
    "/structured/files",
    "/structured/datasets",
    "/structured/delivery",
    "/history",
    "/jobs",
    "/settings",
    "/settings/system",
    "/settings/redaction",
    "/model-settings/text",
    "/model-settings/vision",
]


def smoke_routes(page) -> None:
    login(page)
    # Version stamp (sidebar footer) must render on every build.
    page.wait_for_selector('[data-testid="app-version"]', timeout=15_000)
    print(f"  [ok] version stamp: {page.locator('[data-testid=\"app-version\"]').inner_text()}")
    failures: list[str] = []
    for route in ROUTES:
        page.goto(f"{BASE_URL}{route}", wait_until="domcontentloaded")
        page.wait_for_timeout(900)
        body = page.locator("body").inner_text()
        if not body.strip():
            # 隧道下懒加载 chunk 可能超过 900ms（曾误报 /settings/redaction）
            page.wait_for_timeout(5000)
            body = page.locator("body").inner_text()
        if not body.strip():
            failures.append(f"{route}: empty body")
            continue
        for marker in ("Application error", "组件渲染出错", "ErrorBoundary"):
            if marker in body:
                failures.append(f"{route}: error screen ({marker})")
                break
        print(f"  [ok] {route}")
    if failures:
        raise AssertionError("route smoke failures:\n" + "\n".join(failures))


if __name__ == "__main__":
    run(smoke_routes)
