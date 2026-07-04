# Copyright 2026 DataInfra-RedactionEverything Contributors
"""Tier-1 permission matrix (regular-user side; cheap, no GPU).

Asserts the enforcement chain for a non-admin account:
  - admin-only APIs return 403 (users list, permissions grant, concurrency)
  - bulk confirm API is gated by the bulk_confirm permission (403)
  - /settings/system UI shows the access-denied notice, not the admin panels
"""
from __future__ import annotations

import time

import httpx

from common import BASE_URL, PASSWORD, USERNAME, login, run


def _login_token(c: httpx.Client) -> str:
    """Login with one retry after the 5/min auth rate-limit window."""
    for attempt in range(2):
        r = c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
        if r.status_code == 429 and attempt == 0:
            print("  [wait] auth rate limit, sleeping 65s")
            time.sleep(65)
            continue
        assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
        return r.json()["access_token"]
    raise AssertionError("unreachable")


def api_matrix() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30.0, trust_env=False) as c:
        token = _login_token(c)
        h = {"Authorization": f"Bearer {token}"}

        status = c.get("/api/v1/auth/status", headers=h).json()
        assert status["is_super_admin"] is False, status
        assert status["can_bulk_confirm"] is False, status

        assert c.get("/api/v1/auth/users", headers=h).status_code == 403
        assert (
            c.put(
                f"/api/v1/auth/users/{USERNAME}/permissions",
                headers=h,
                json={"bulk_confirm": True},
            ).status_code
            == 403
        )
        assert c.get("/api/v1/auth/concurrency", headers=h).status_code == 403
        assert c.get("/api/v1/audit/logs", headers=h).status_code == 403
        assert (
            c.post("/api/v1/jobs/nonexistent/review/commit-all", headers=h).status_code == 403
        )
    print("  [ok] api matrix (403s in place)")


def perm_matrix(page) -> None:
    api_matrix()
    login(page)
    page.goto(f"{BASE_URL}/settings/system", wait_until="domcontentloaded")
    # Lazy route chunk can load slowly over the tunnel — wait for the actual
    # notice instead of a fixed sleep.
    page.wait_for_selector("text=需要管理员权限", timeout=30_000)
    body = page.locator("body").inner_text()
    assert "创建用户" not in body, "admin panel leaked to regular user"
    print("  [ok] settings/system gated in UI")


if __name__ == "__main__":
    run(perm_matrix)
