# 运行时密钥管理

## 原则

- **密钥不入库**：所有敏感值放服务器 `~/.redaction_secrets`（`chmod 600`，仅 owner 可读），由 `backend_g0.sh` 启动时 `source`；仓库里的 `backend_g0.sh` 只保留 `. ~/.redaction_secrets`，不含任何明文。
- 共享 GPU 机上 `backend_g0.sh` 权限为 775（组/其他可读），故**绝不能把密钥写进脚本**——这正是审计 CP0-5/CP5-1 的问题。

## `~/.redaction_secrets` 内容

```sh
# RedactionEverything runtime secrets — sourced by backend_g0.sh
export JWT_SECRET_KEY=<强随机值>
```

首次部署到新机：

```sh
umask 077
printf 'export JWT_SECRET_KEY=%s\n' "$(openssl rand -hex 32)" > ~/.redaction_secrets
chmod 600 ~/.redaction_secrets
```

## 轮换 JWT_SECRET_KEY

⚠️ 轮换会使**所有已签发的登录态失效**（用户需重新登录）。选低峰或演示间隙做。

```sh
umask 077
printf 'export JWT_SECRET_KEY=%s\n' "$(openssl rand -hex 32)" > ~/.redaction_secrets
chmod 600 ~/.redaction_secrets
fuser -k 8000/tcp; sleep 2
setsid nohup bash ~/backend_g0.sh > ~/logs/backend_g0.log 2>&1 </dev/null &
# 验证：旧 token 401、新登录 200
```

## 现状（2026-07-06）

- JWT_SECRET_KEY 已从 `backend_g0.sh` 外置到 `~/.redaction_secrets`（600）。
- **值沿用历史值未轮换**（当日平台在用/演示中，轮换会踢掉登录态）——首次低峰期按上文轮换一次即闭环。
