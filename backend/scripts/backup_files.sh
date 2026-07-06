#!/usr/bin/env bash
# Copyright 2026 DataInfra-RedactionEverything Contributors
# 文件树备份（uploads/outputs/structured_uploads）——操作员 cron 任务，
# 刻意不进 FastAPI 进程（数十 GB 拷贝抢 I/O + 进程重启产生半快照）。
# rsync --link-dest 硬链增量：未变文件近零成本。
#
# 用法（cron 每日一次）：
#   BACKUP_FILES_TARGET=/mnt/backup ./backup_files.sh
# 环境：
#   BACKUP_FILES_TARGET      目标目录（必填，建议独立卷/USB 盘）
#   BACKUP_FILES_KEEP_DAYS   保留天数（默认 7）
#   BACKUP_FILES_MIN_FREE_GB 目标盘最低剩余空间（默认 20，低于拒跑）
#   BACKEND_DIR              后端目录（默认脚本上级）
set -euo pipefail

BACKEND_DIR="${BACKEND_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
TARGET="${BACKUP_FILES_TARGET:?BACKUP_FILES_TARGET 必填（独立卷/USB 盘路径）}"
KEEP_DAYS="${BACKUP_FILES_KEEP_DAYS:-7}"
MIN_FREE_GB="${BACKUP_FILES_MIN_FREE_GB:-20}"

free_gb=$(df -BG --output=avail "$TARGET" | tail -1 | tr -dc '0-9')
if [ "${free_gb:-0}" -lt "$MIN_FREE_GB" ]; then
  echo "拒绝备份：目标盘剩余 ${free_gb}G < 水位 ${MIN_FREE_GB}G" >&2
  exit 3
fi

DATE=$(date +%Y%m%d)
DEST="$TARGET/files_$DATE"
PREV=$(ls -d "$TARGET"/files_* 2>/dev/null | sort | tail -1 || true)
LINK_ARGS=()
if [ -n "$PREV" ] && [ "$PREV" != "$DEST" ]; then
  LINK_ARGS=(--link-dest="$PREV")
fi

mkdir -p "$DEST"
for d in uploads outputs data/structured_uploads; do
  src="$BACKEND_DIR/$d"
  [ -d "$src" ] || continue
  rsync -a "${LINK_ARGS[@]}" "$src/" "$DEST/$(basename "$d")/"
done

# 清理超保留期快照
ls -d "$TARGET"/files_* 2>/dev/null | sort | head -n -"$KEEP_DAYS" | xargs -r rm -rf

# 写 marker 供 /health/services 报新鲜度（BACKUP_INCLUDE_FILES=true 时检查）
BACKUP_DIR="${BACKUP_DIR:-$BACKEND_DIR/data/backups}"
mkdir -p "$BACKUP_DIR"
bytes=$(du -sb "$DEST" | cut -f1)
printf '{"completed_at":"%s","bytes":%s,"snapshot":"files_%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$bytes" "$DATE" > "$BACKUP_DIR/last_file_backup.json"
echo "OK $DEST ($bytes bytes)"
