# 交付运维 Runbook（裸机双 GPU 版）

适用拓扑：单机双卡（现行 5090 生产拓扑），全部服务 `~/*.sh` + `start_all.sh` 管理。

## 1. 全新安装（从零）

1. 前置：Ubuntu 22/24、NVIDIA 驱动、CUDA 12.8+、`~/anaconda3/envs/dataInfra`（python+node）、
   `~/rvenv/vllm` 与 `~/rvenv/la` 两个 venv——按 `deploy/host-scripts/bootstrap.sh` 与
   `build_*_venv.sh` 执行；模型经魔搭下载（`dl_models.sh`，HF 网络不可用时的默认路径）。
2. 代码落位：`~/redaction-deploy/`（backend + frontend/dist）。
3. 服务脚本落位：`deploy/host-scripts/*.sh` 拷到 `~/`（含 GPU 钉卡与显存配额，勿改数值）。
4. `backend_g0.sh` 里设置 **JWT_SECRET_KEY**（必改）、AUTH_ENABLED=true、并发参数（见脚本内注释）。
5. 启动：`bash ~/start_all.sh`（自愈式：只拉起 DOWN 的端口）。VL 服务就绪要 1-3 分钟。
6. 验收：`curl localhost:8000/health/services` → `all_online: true`；跑 `e2e/` Tier-1 两条冒烟。

## 2. 版本升级（带自动回滚）

本地出包 → 传服务器 → 一条命令升级：

```bash
# 本地（仓库根）
python deploy/release.py            # 产出 dist-release/redaction-release-<ver>-<时间>.tar.gz
# 传到服务器家目录后（scp/base64 均可）
bash deploy/upgrade.sh ~/redaction-release-*.tar.gz
```

`upgrade.sh` 流程：备份现网（`~/upgrade-backups/<时间戳>/`）→ 应用 → 只重启后端 :8000
（GPU 模型服务不动）→ **90 秒健康门禁，失败自动回滚到备份并再次拉起**。
退出码：0=升级成功；1=已自动回滚；2=回滚后健康未确认（看 `~/backend.log`）。
自动保留最近 5 份升级备份。

## 3. 备份与恢复

- **每小时自动**：后端进程内置 SQLite 备份（jobs/file_store/token_blacklist，`db_backup`）。
- **每日建议**（crontab）：`tar -czf ~/backups/data-$(date +%F).tar.gz -C ~/redaction-deploy/backend data uploads outputs`
- **恢复**：停后端（`fuser -k 8000/tcp`）→ 解包覆盖 `backend/data|uploads|outputs` → 拉起
  `bash ~/backend_g0.sh`。auth.json 损坏时后端会自动用同目录 `.bak` 恢复。

## 4. 常见故障

| 症状 | 处理 |
|---|---|
| all_online=false，某模型服务 DOWN | `bash ~/start_all.sh`（只拉起挂掉的）；vLLM 类服务杀残留要按 `nvidia-smi --query-compute-apps` 查孤儿 EngineCore PID `kill -9`，别按名字 pkill |
| 重启服务器后全栈恢复 | `bash ~/start_all.sh` 一条命令（脚本自带依赖顺序与就绪等待） |
| 显存不足/OOM | 先查孤儿进程；配额（gpu-util 等）都在 `~/*.sh` 内注释处，改前先看注释红线 |
| 升级后异常 | `upgrade.sh` 已自动回滚；手动回滚=用 `~/upgrade-backups/<最新>/` 覆盖后重启 :8000 |
| 忘记管理员密码 | 停后端，编辑 `backend/data/auth.json` 删除该用户条目后重启，用 /auth/setup 重建（仅剩余 0 用户时）或由另一管理员改密 |

## 5. 升级影响面速查

- 只动 `backend/app`、`backend/config`、`backend/scripts`、`frontend/dist` → 重启 :8000，秒级中断
- 动 `~/*.sh`（GPU 服务配置）→ 需重启对应模型服务，遵循 `start_all.sh` 依赖顺序，避开业务高峰
- 动 `backend_g0.sh` 环境变量 → 重启 :8000 即生效
