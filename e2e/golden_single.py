# Copyright 2026 DataInfra-RedactionEverything Contributors
"""Tier-2 golden path: single text file end-to-end on the playground.

Text-only pipeline (HaS NER, seconds of GPU) — cheap enough to run against
production between batches. Upload -> recognition -> entities -> redact ->
result rendered with the raw PII gone from the redacted preview.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from common import BASE_URL, login, run

PII_TEXT = (
    "合作备忘录\n甲方联系人：张伟，联系电话 13812345678，"
    "身份证号 110101199001011234，通讯地址：北京市朝阳区幸福路1号院。\n"
    "乙方联系人：李芳，电子邮箱 lifang@example.com。\n"
)


def golden_single(page) -> None:
    login(page)
    page.goto(f"{BASE_URL}/single", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="playground-dropzone"]', timeout=20_000)

    # No TemporaryDirectory context: Chrome still holds the file handle during
    # upload and Windows then refuses the cleanup (WinError 32).
    sample = Path(tempfile.gettempdir()) / "e2e_golden_single.txt"
    sample.write_text(PII_TEXT, encoding="utf-8")
    page.locator('[data-testid="playground-dropzone"] input[type="file"]').set_input_files(
        str(sample)
    )

    # Recognition runs after upload; the entity panel appears when done.
    page.wait_for_selector('[data-testid="playground-entity-panel"]', timeout=180_000)
    panel_text = page.locator('[data-testid="playground-entity-panel"]').inner_text()
    assert "13812345678" in panel_text or "张伟" in panel_text, (
        "entity panel does not show the expected PII hits:\n" + panel_text[:500]
    )
    print("  [ok] recognition produced entities")

    redact = page.locator('[data-testid="playground-redact-btn"]')
    redact.wait_for(state="visible", timeout=30_000)
    page.wait_for_timeout(500)
    redact.click()

    page.wait_for_selector('[data-testid="playground-result"]', timeout=180_000)
    # The result view is an original|redacted side-by-side compare — scope the
    # PII assertions to the redacted pane only. testid ships with newer builds;
    # fall back to anchoring on the pane heading for older deployments.
    pane = page.locator('[data-testid="playground-redacted-pane"]')
    if pane.count() == 0:
        pane = page.locator(
            'xpath=//span[contains(text(),"匿名化结果") or contains(text(),"Redacted")]'
            "/ancestor::div[contains(@class,'flex-col')][1]"
        )
    pane.first.wait_for(state="visible", timeout=30_000)
    result_text = pane.first.inner_text()
    assert result_text.strip(), "redacted pane is empty"
    assert "13812345678" not in result_text, "raw phone number leaked into the redacted result"
    assert "110101199001011234" not in result_text, "raw ID number leaked into the redacted result"
    print("  [ok] redacted result rendered, raw PII absent from redacted pane")


if __name__ == "__main__":
    run(golden_single)
