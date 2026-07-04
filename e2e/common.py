# Copyright 2026 DataInfra-RedactionEverything Contributors
"""E2E harness shared helpers.

House rules: ALWAYS headed real Chrome (never headless/bundled Chromium).
Target selected by env:
  E2E_BASE_URL   default http://localhost:8000  (tunnelled 5090 or local stack)
  E2E_USERNAME / E2E_PASSWORD   a regular (non-admin) account; created via
                                /auth/register on first run if missing.
"""
from __future__ import annotations

import os

from playwright.sync_api import Page, sync_playwright

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000").rstrip("/")
USERNAME = os.environ.get("E2E_USERNAME", "e2e_user")
PASSWORD = os.environ.get("E2E_PASSWORD", "E2eUser!2026")
SLOW_MO = int(os.environ.get("E2E_SLOWMO_MS", "0"))


def launch(p):
    return p.chromium.launch(channel="chrome", headless=False, slow_mo=SLOW_MO)


def ensure_account() -> None:
    """Register the E2E account if it does not exist yet (idempotent)."""
    import httpx

    # trust_env=False：否则 httpx 读 Windows 注册表系统代理（Mihomo）把
    # localhost 请求塞进代理返回空 502（老坑，见部署记忆）。
    with httpx.Client(base_url=BASE_URL, timeout=30.0, trust_env=False) as c:
        r = c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
        if r.status_code == 200:
            return
        r = c.post("/api/v1/auth/register", json={"username": USERNAME, "password": PASSWORD})
        if r.status_code != 200:
            raise RuntimeError(f"cannot login or register e2e account: {r.status_code} {r.text[:200]}")


def login(page: Page) -> None:
    page.goto(f"{BASE_URL}/auth")
    page.locator('input[autocomplete="username"]').fill(USERNAME)
    page.locator('input[type="password"]').first.fill(PASSWORD)
    page.locator('button[type="submit"]').first.click()
    page.wait_for_url(lambda url: "/auth" not in url, timeout=20_000)


def run(scenario) -> None:
    """Boilerplate: headed Chrome, one context, scenario(page), banner result."""
    ensure_account()
    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        try:
            scenario(page)
            print(f"E2E_PASS {scenario.__name__}")
        finally:
            browser.close()
