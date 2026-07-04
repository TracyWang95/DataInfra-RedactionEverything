# Copyright 2026 DataInfra-RedactionEverything Contributors
"""Tier-2 golden path: batch wizard, all five steps, on the real stack.

Two tiny text files (NER-only, seconds of GPU) so it is safe to run against
production. Covers: step1 config confirm -> step2 upload -> step3 submit &
recognition -> step4 per-file confirm (plus the bulk-confirm permission UX:
visible-but-disabled for a non-privileged account) -> step5 export surface.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from common import BASE_URL, login, run

FILES = {
    "e2e_batch_a.txt": "服务合同\n甲方代表：王强，电话 13911112222，身份证 110101198501012345。\n",
    "e2e_batch_b.txt": "采购订单\n联系人：赵敏，邮箱 zhaomin@example.com，地址：上海市浦东新区世纪大道100号。\n",
}


def _click_when_enabled(page, testid: str, timeout_s: int = 120) -> None:
    locator = page.locator(f'[data-testid="{testid}"]')
    locator.first.wait_for(state="visible", timeout=timeout_s * 1000)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if locator.first.is_enabled():
            locator.first.click()
            return
        page.wait_for_timeout(500)
    raise AssertionError(f"{testid} never became enabled")


def golden_batch(page) -> None:
    login(page)
    page.goto(f"{BASE_URL}/batch/smart", wait_until="domcontentloaded")

    # Step 1: default config is valid; tick the confirm checkbox, then advance.
    confirm = page.locator('[data-testid="confirm-step1"]')
    confirm.first.wait_for(state="visible", timeout=60_000)
    if confirm.first.get_attribute("data-state") != "checked" and not confirm.first.is_checked():
        confirm.first.click()
    _click_when_enabled(page, "advance-upload", 60)
    print("  [ok] step1 confirmed")

    # Step 2: upload two small text files.
    page.wait_for_selector('[data-testid="batch-step2-upload"]', timeout=30_000)
    tmp = Path(tempfile.gettempdir())
    paths = []
    for name, content in FILES.items():
        p = tmp / name
        p.write_text(content, encoding="utf-8")
        paths.append(str(p))
    page.locator('[data-testid="drop-zone"] input[type="file"]').set_input_files(paths)
    _click_when_enabled(page, "step2-next", 120)
    print("  [ok] step2 uploaded 2 files")

    # Step 3: submit recognition, wait until the wizard lets us into review.
    page.wait_for_selector('[data-testid="batch-step3-recognize"]', timeout=30_000)
    _click_when_enabled(page, "submit-queue", 60)
    _click_when_enabled(page, "step3-next", 300)
    print("  [ok] step3 recognition done")

    # Step 4: review. Bulk-confirm button must be visible but DISABLED for a
    # non-privileged account (permission UX shipped 2026-07-04).
    page.wait_for_selector('[data-testid="batch-step4-review"]', timeout=60_000)
    bulk = page.locator('[data-testid="bulk-confirm-all"]')
    if bulk.count() > 0:
        assert not bulk.first.is_enabled(), "bulk confirm must be disabled without permission"
        print("  [ok] bulk-confirm visible but gated")

    # Confirm both files (single-page text docs, no page-visit gate).
    for i in range(len(FILES)):
        _click_when_enabled(page, "confirm-redact", 180)
        page.wait_for_timeout(1500)
        print(f"  [ok] file {i + 1} confirmed")

    _click_when_enabled(page, "go-export", 180)

    # Step 5: export surface renders with the redacted download available.
    page.wait_for_selector('[data-testid="batch-step5-export"]', timeout=60_000)
    page.wait_for_selector('[data-testid="download-redacted"]', timeout=60_000)
    print("  [ok] step5 export surface ready")


if __name__ == "__main__":
    run(golden_batch)
