# Copyright 2026 DataInfra-RedactionEverything Contributors
"""Capture real-product screenshots for the operations manual (docs/manual/)."""
from __future__ import annotations

from pathlib import Path

from common import BASE_URL, login, run

OUT = Path(__file__).resolve().parents[1] / "docs" / "manual"

SHOTS = [
    ("start", "/", 1200),
    ("single", "/single", 1500),
    ("batch-hub", "/batch", 1500),
    ("batch-step1", "/batch/smart", 2000),
    ("structured-files", "/structured/files", 1500),
    ("structured-policy", "/structured/datasets", 1800),
    ("structured-delivery", "/structured/delivery", 1500),
    ("history", "/history", 1500),
    ("settings", "/settings", 1800),
]


def capture_manual(page) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # 登录页先截（未登录态）
    page.goto(f"{BASE_URL}/auth", wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT / "login.png"))
    print("  [shot] login")

    login(page)
    for name, route, settle_ms in SHOTS:
        page.goto(f"{BASE_URL}{route}", wait_until="domcontentloaded")
        page.wait_for_timeout(settle_ms)
        page.screenshot(path=str(OUT / f"{name}.png"))
        print(f"  [shot] {name}")


if __name__ == "__main__":
    run(capture_manual)
