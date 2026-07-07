# Copyright 2026 DataInfra-RedactionEverything Contributors
"""License 冒烟（无需管理员账号）：
1. 公开 /license/status 可达且 unlicensed（默认关闭=存量零变化）
2. unlicensed 时登录页不显示到期横幅
面板 UI 的 super_admin 视图由后端 29 项 License 测试 + 构建保障，
真机点验留给管理员账号（/settings/system → 授权许可 tab）。
"""
from __future__ import annotations

import json
from urllib.request import urlopen

from common import BASE_URL, run


def scenario(page) -> None:
    with urlopen(f"{BASE_URL}/api/v1/license/status", timeout=30) as resp:
        status = json.loads(resp.read().decode("utf-8"))
    assert status.get("state") == "unlicensed", status
    print("  [ok] /license/status public + unlicensed (enforcement off)")

    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    assert page.locator('[data-testid="license-banner"]').count() == 0, (
        "license banner must not show while unlicensed"
    )
    print("  [ok] login page shows no license banner while unlicensed")


if __name__ == "__main__":
    run(scenario)
