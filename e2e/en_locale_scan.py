# Copyright 2026 DataInfra-RedactionEverything Contributors
"""F2-1 EN 模式漏中文自动扫：切 EN 后全路由抓可见文本，CJK 正则取证。

机器判定 i18n 完整度；输出 e2e/.artifacts/en_leak_report.md。
豁免：用户数据（文件名/任务名含中文属正常）——按容器 testid 粗过滤。
"""
from __future__ import annotations

import re
from pathlib import Path

from common import BASE_URL, login, run

ROUTES = [
    "/", "/single", "/batch", "/structured", "/structured/files",
    "/structured/datasets", "/structured/delivery", "/history", "/jobs",
    "/settings", "/settings/redaction", "/model-settings/text", "/model-settings/vision",
]
CJK = re.compile(r"[一-鿿]")
# 用户数据容器：其中的中文是数据不是 UI 文案
DATA_CONTAINER_HINTS = ("history-row", "job-row", "recent-jobs", "trash-row", "dataset")


def scenario(page) -> None:
    login(page)
    # 切换英文（右上角切换按钮 aria/文案：切换英文 → Switch to Chinese）
    try:
        page.locator('[data-testid="lang-toggle"]').click()
        page.wait_for_timeout(1500)
    except Exception:
        print("  [warn] language toggle not found; assuming EN already")

    leaks: list[tuple[str, str]] = []
    for route in ROUTES:
        page.goto(f"{BASE_URL}{route}", wait_until="domcontentloaded")
        page.wait_for_timeout(1800)
        seen: set[str] = set()
        for el in page.locator("body *:not(script):not(style)").all()[:2500]:
            try:
                if el.locator("*").count() > 0:
                    continue  # 只取叶子节点
                text = (el.inner_text() or "").strip()
            except Exception:
                continue
            if not text or not CJK.search(text) or text in seen:
                continue
            seen.add(text)
            tid = ""
            try:
                tid = el.evaluate(
                    "n => n.closest('[data-testid]')?.getAttribute('data-testid') || ''"
                )
            except Exception:
                pass
            if any(h in tid for h in DATA_CONTAINER_HINTS):
                continue
            leaks.append((route, text[:80]))
        print(f"  [scan] {route}: {sum(1 for r, _ in leaks if r == route)} leak(s)")

    report = Path(__file__).parent / ".artifacts" / "en_leak_report.md"
    report.parent.mkdir(exist_ok=True)
    lines = ["# EN 模式中文泄漏报告\n"]
    for route, text in leaks:
        lines.append(f"- `{route}`: {text}")
    report.write_text("\n".join(lines) or "clean", encoding="utf-8")
    print(f"\n  total leaks: {len(leaks)} -> {report}")
    if len(leaks) > 0:
        for route, text in leaks[:20]:
            print(f"    {route}: {text}")


run(scenario)
