# 备份与恢复运维手册

## 两条备份线（互不替代）

| | 数据库+配置 | 文件树（原件/成品） |
|---|---|---|
| 内容 | 4 个 SQLite 库 + auth/密钥/配置 JSON | uploads/ outputs/ data/structured_uploads/ |
| 机制 | 应用内每小时热备（SQLite Online Backup + 原子拷贝） | 操作员 cron 跑 `scripts/backup_files.sh`（rsync 硬链增量） |
| 位置 | `DATA_DIR/backups/`（保留 24 份，可配） | `BACKUP_FILES_TARGET`（建议独立卷/USB，保留 7 天） |
| 配置 | `BACKUP_INTERVAL_SEC` / `BACKUP_RETENTION_COUNT` / `BACKUP_DIR` | 脚本环境变量，见脚本头注释 |

**库备份 ≠ 文件备份**：每小时库快照不含任何上传原件与匿名化成品。要能整机恢复，必须两条线都跑。

## 日常监控

`GET /health/services` 的 `backup` 段：各存储最近成功时间；任一存储超过 2×备份间隔未成功 → `stale: true`（管理面板服务监控可见）。

## 恢复流程（数据库+配置）

1. **停服**：`fuser -k 8000/tcp`（工具会拒绝在活服务下运行）
2. 看有什么可恢复：`python scripts/restore_backup.py list`
3. 预演：`python scripts/restore_backup.py restore --store jobs --latest --dry-run`
4. 执行：`python scripts/restore_backup.py restore --store jobs --latest`（或 `--all`）
   - 现有文件自动挪到 `*.pre_restore.<时间戳>`（含 WAL/SHM 伴生文件），恢复错了可回退
   - SQLite 快照恢复前后各做一次 integrity_check
5. 重启服务，验证 `/health/services`

## 恢复流程（文件树）

从最近快照回拷（快照内是完整目录视图，硬链只省磁盘不影响读取）：

```bash
rsync -a /mnt/backup/files_YYYYMMDD/uploads/  <BACKEND_DIR>/uploads/
rsync -a /mnt/backup/files_YYYYMMDD/outputs/  <BACKEND_DIR>/outputs/
rsync -a /mnt/backup/files_YYYYMMDD/structured_uploads/ <BACKEND_DIR>/data/structured_uploads/
```

## 单 worker 部署约束

auth.json 等 JSON 存储使用进程内锁 + 原子替换保护，**要求单 uvicorn worker**（交付脚本 backend_g0.sh 即单 worker）。多 worker 部署未获支持——并发写 auth.json 存在竞态。

## 手动验证清单（交付时一次）

- [ ] 目标机跑一轮 `backup_files.sh`，确认硬链增量（第二轮耗时/增量字节骤降）
- [ ] 磁盘水位闸：`BACKUP_FILES_MIN_FREE_GB=99999` 应拒跑
- [ ] 停服 `restore_backup.py restore --all --dry-run` 计划正确
- [ ] 恢复一个库后启动服务，数据完好
