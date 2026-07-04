# E2E Harness（有头 Chrome，永不无头）

五层闸门的第 3 层。目标由 `E2E_BASE_URL` 决定（默认 `http://localhost:8000`，即隧道到 5090 或本地全栈）。

## 分层

| Tier | 脚本 | GPU | 何时跑 |
|---|---|---|---|
| 1 冒烟 | `smoke_routes.py`（全路由渲染）、`perm_matrix.py`（权限矩阵：API 403 + UI 门禁） | 无 | 每轮必跑，随时可打生产隧道 |
| 2 黄金路径 | `golden_single.py`（单文件文本全链路：上传→识别→匿名化→成品栏无原始PII，✅已实现） | 轻 | 部署后 / 随时（文本路径秒级） |
| 2 待实现 | `golden_batch.py`（批量五步含批量确认）、`golden_structured.py`（导入→策略→交付）、`golden_export.py`（异步分卷导出） | 有 | 下一轮 loop |

## 运行

```bash
cd e2e
python smoke_routes.py          # Tier 1
python perm_matrix.py
# 或 cd frontend && npm run e2e （= Tier 1 全部）
```

账号：`E2E_USERNAME`/`E2E_PASSWORD`（默认 e2e_user，首跑自动注册，普通角色）。
管理员侧断言需要 `E2E_ADMIN_USERNAME`/`E2E_ADMIN_PASSWORD`（不入库，跑前 export）。

## 约定

- 选择器优先 `data-testid`；新功能落地时同步补 testid。
- 每个脚本一个场景函数，`common.run()` 负责起浏览器/登录/结果横幅（`E2E_PASS xxx`）。
- 失败=抛 AssertionError，退出码非 0，CI 可直接接。
