# Copyright 2026 DataInfra-RedactionEverything Contributors
"""Tier-1 golden path: change-password round trip (no GPU).

UI: header button -> dialog -> submit -> success state.
API: the NEW password logs in; then revert to the original so the e2e
account stays stable for every other script.
"""
from __future__ import annotations

import time

import httpx

from common import BASE_URL, PASSWORD, USERNAME, login, run

NEW_PASSWORD = PASSWORD + "x"


def _login(c: httpx.Client, password: str) -> httpx.Response:
    for attempt in range(2):
        r = c.post("/api/v1/auth/login", json={"username": USERNAME, "password": password})
        if r.status_code == 429 and attempt == 0:
            print("  [wait] auth rate limit, sleeping 65s")
            time.sleep(65)
            continue
        return r
    return r


def _revert_password(current: str, back_to: str) -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30.0, trust_env=False) as c:
        r = _login(c, current)
        assert r.status_code == 200, f"login with changed password failed: {r.status_code}"
        token = r.json()["access_token"]
        r = c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={"old_password": current, "new_password": back_to},
        )
        assert r.status_code == 200, f"revert failed: {r.status_code} {r.text[:200]}"


def golden_password(page) -> None:
    login(page)
    page.locator('[data-testid="change-password-btn"]').click()
    page.wait_for_selector('[data-testid="change-password-dialog"]', timeout=15_000)
    page.locator("#cp-old").fill(PASSWORD)
    page.locator("#cp-new").fill(NEW_PASSWORD)
    page.locator("#cp-confirm").fill(NEW_PASSWORD)
    page.locator('[data-testid="change-password-submit"]').click()
    page.wait_for_selector('[data-testid="change-password-done"]', timeout=30_000)
    print("  [ok] UI change-password succeeded")

    try:
        _revert_password(NEW_PASSWORD, PASSWORD)
        print("  [ok] new password logs in; reverted to original")
    except AssertionError:
        # Never leave the shared e2e account in an unknown state.
        _revert_password(PASSWORD, PASSWORD)
        raise


if __name__ == "__main__":
    run(golden_password)
