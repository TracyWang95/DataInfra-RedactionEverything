# Copyright 2026 DataInfra-RedactionEverything Contributors
"""Tier-2 golden path: structured (库表) pipeline end to end.

Tiny 3-row CSV (CPU-only redaction, no GPU) — safe against production.
Upload -> dataset auto-registered with a recommended policy -> confirm policy
-> delivery creates an export job -> download appears.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from common import BASE_URL, login, run

CSV = (
    "姓名,电话,身份证号,备注\n"
    "张三,13800001111,110101199001012345,普通客户\n"
    "李四,13900002222,110101198501015678,VIP客户\n"
    "王五,13700003333,,潜在客户\n"
)


def golden_structured(page) -> None:
    login(page)
    page.goto(f"{BASE_URL}/structured/files", wait_until="domcontentloaded")
    page.wait_for_selector("#structured-upload", state="attached", timeout=30_000)

    sample = Path(tempfile.gettempdir()) / "e2e_structured.csv"
    sample.write_text(CSV, encoding="utf-8-sig")
    page.locator("#structured-upload").set_input_files(str(sample))

    # Upload auto-navigates to the datasets/policy page. The canvas is a
    # 5-step flow: generate field policy -> review rows -> confirm -> save.
    page.wait_for_url(lambda url: "/structured/datasets" in url, timeout=60_000)
    page.wait_for_selector('[data-testid="structured-policy-canvas"]', timeout=60_000)

    generate = page.get_by_role("button").filter(has_text="生成字段策略")
    generate.first.wait_for(state="visible", timeout=30_000)
    generate.first.click()

    page.wait_for_selector('[data-testid="policy-row"]', timeout=60_000)
    rows = page.locator('[data-testid="policy-row"]').count()
    assert rows >= 3, f"expected policy rows for the CSV columns, got {rows}"
    print(f"  [ok] policy generated, canvas shows {rows} fields")

    # Confirm every page of fields (single page for this CSV): the save step
    # stays disabled until each page is explicitly confirmed.
    confirm_page = page.get_by_role("button").filter(has_text="确认第")
    while confirm_page.count() > 0 and confirm_page.first.is_visible():
        confirm_page.first.click()
        page.wait_for_timeout(800)
        confirm_page = page.get_by_role("button").filter(has_text="确认第")
    print("  [ok] field pages confirmed")

    # CTA reads 「保存并生成预览」 (or 「保存策略」 in older copy) — match on 保存.
    save = page.get_by_role("button").filter(has_text="保存")
    save.first.wait_for(state="visible", timeout=30_000)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not save.first.is_enabled():
        page.wait_for_timeout(500)
    assert save.first.is_enabled(), "save-policy button never became enabled after page confirm"
    save.first.click()
    page.wait_for_timeout(2500)
    print("  [ok] policy saved")

    # Delivery: only saved datasets are deliverable — 全选可交付 picks exactly
    # those (unsaved duplicates from earlier runs stay excluded).
    page.goto(f"{BASE_URL}/structured/delivery", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="delivery-dataset-row"]', timeout=30_000)
    select_all = page.get_by_role("button").filter(has_text="全选可交付")
    select_all.first.wait_for(state="visible", timeout=15_000)
    select_all.first.click()
    page.wait_for_timeout(500)

    create = page.locator('[data-testid="delivery-create-job"]')
    create.first.wait_for(state="visible", timeout=30_000)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not create.first.is_enabled():
        page.wait_for_timeout(500)
    assert create.first.is_enabled(), "create-delivery stayed disabled (no deliverable dataset?)"
    create.first.click()
    print("  [ok] delivery job created")

    page.wait_for_selector('[data-testid="delivery-download-job"]', timeout=180_000)
    print("  [ok] export completed, download available")

    # 逐数据集删除（PM 需求）：删掉一个本轮登记的数据集并断言其从列表消失。
    page.goto(f"{BASE_URL}/structured/files", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid^="delete-dataset-"]', timeout=30_000)
    first = page.locator('[data-testid^="delete-dataset-"]').first
    target_testid = first.get_attribute("data-testid")
    first.click()
    page.locator('div[role="dialog"] button').filter(has_text="确认").first.click()
    page.wait_for_timeout(2000)
    assert page.locator(f'[data-testid="{target_testid}"]').count() == 0, (
        "deleted dataset still present in the registry"
    )
    print("  [ok] per-dataset delete removes the entry")


if __name__ == "__main__":
    run(golden_structured)
