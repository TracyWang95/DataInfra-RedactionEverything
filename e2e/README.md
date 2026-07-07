# E2E Harness（有头 Chrome，永不无头）

五层闸门的第 3 层。目标由 `E2E_BASE_URL` 决定（默认 `http://localhost:8000`，即隧道到 5090 或本地全栈）。

## 分层

| Tier | 脚本 | GPU | 何时跑 |
|---|---|---|---|
| 1 冒烟 | `smoke_routes.py`（全路由渲染）、`perm_matrix.py`（权限矩阵：API 403 + UI 门禁） | 无 | 每轮必跑，随时可打生产隧道 |
| 2 黄金路径 | `golden_single.py`（单文件文本全链路：上传→识别→匿名化→成品栏无原始PII）✅ | 轻 | 随时（文本路径秒级） |
| 2 黄金路径 | `golden_batch.py`（批量五步全流程 + 批量确认权限门断言）✅ | 轻 | 随时（2 个小文本文件） |
| 2 黄金路径 | `golden_structured.py`（库表：上传→字段策略→确认→保存→交付→下载）✅ | 无 | 随时（本地规则，无GPU） |
| 2 黄金路径 | `golden_export.py`（异步分卷导出 API 闭环：估算秒回→后台任务→分卷zip下载）✅ | 无 | 随时 |
| 1 黄金路径 | `golden_password.py`（改密闭环：UI改→新密码登录→还原）✅ | 无 | 随时 |

## 运行

```bash
cd e2e
python smoke_routes.py          # Tier 1
python perm_matrix.py
python golden_single.py         # Tier 2
python golden_batch.py
# 或 cd frontend && npm run e2e （= Tier 1 全部）
```

账号：`E2E_USERNAME`/`E2E_PASSWORD`（默认 e2e_user，首跑自动注册，普通角色）。
管理员侧断言需要 `E2E_ADMIN_USERNAME`/`E2E_ADMIN_PASSWORD`（不入库，跑前 export）。

## 约定

- 选择器优先 `data-testid`；新功能落地时同步补 testid。
- 每个脚本一个场景函数，`common.run()` 负责起浏览器/登录/结果横幅（`E2E_PASS xxx`）；失败自动存全页截图+正文到 `e2e/.artifacts/`。
- 失败=抛 AssertionError，退出码非 0，CI 可直接接。
- ⚠️ 改这个目录的中文文件别用 PowerShell Get/Set-Content 回转（GBK 读+UTF8 写=乱码），用编辑工具直接写。

## 已编码的坑

- httpx 必须 `trust_env=False`（Mihomo 注册表代理会 502 掉 localhost）
- auth 限流 5 次/分钟：连跑脚本触发 429 时等 65s（`_login_token`）
- Windows 上传文件句柄被 Chrome 占用：不能用 TemporaryDirectory 自动清理
- 结果页是原文|成品双栏：PII 断言要 scope 到 `playground-redacted-pane`
- step1 的 `confirm-step1` 是勾选框，前进按钮是 `advance-upload`
