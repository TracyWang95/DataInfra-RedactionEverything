# Copyright 2026 DataInfra-RedactionEverything Contributors
"""操作员恢复 CLI（R1-1）。必须停服后运行——活库的 WAL 句柄、进程内缓存
（auth 版本缓存）与内存任务队列会让在线恢复三重踩坑，因此刻意不提供
HTTP 恢复端点。

用法：
  python scripts/restore_backup.py list
  python scripts/restore_backup.py restore --store jobs --latest [--dry-run]
  python scripts/restore_backup.py restore --all --latest

uploads/outputs 文件树恢复不在本工具范围（rsync 回拷流程见
docs/backup-restore.md）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import urllib.request
from datetime import UTC, datetime
from glob import glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402
from app.core.db_backup import backup_inventory, check_db_integrity  # noqa: E402


def _backup_dir() -> str:
    return settings.BACKUP_DIR or os.path.join(settings.DATA_DIR, "backups")


def _server_alive() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3):
            return True
    except Exception:
        return False


def _snapshots_for(name: str, live_path: str) -> list[str]:
    ext = ".sqlite3" if live_path.endswith(".sqlite3") else (os.path.splitext(live_path)[1] or ".bin")
    # sqlite 目标沿用 backup_sqlite 的 {db 文件名}_{ts} 命名；小文件用清单名
    stem = os.path.splitext(os.path.basename(live_path))[0] if ext == ".sqlite3" else name
    return sorted(glob(os.path.join(_backup_dir(), f"{stem}_*{ext}")))


def cmd_list() -> int:
    print(f"backup dir: {_backup_dir()}\n")
    for name, live_path, kind in backup_inventory():
        snaps = _snapshots_for(name, live_path)
        if not snaps:
            print(f"[{name}] ({kind})  —  无快照")
            continue
        latest = snaps[-1]
        size_kb = os.path.getsize(latest) / 1024
        integrity = ""
        if kind == "sqlite":
            integrity = "  integrity=ok" if check_db_integrity(latest) else "  integrity=FAILED"
        print(f"[{name}] ({kind})  {len(snaps)} 份，最新 {os.path.basename(latest)} "
              f"({size_kb:.0f}KB){integrity}")
    return 0


def _restore_one(name: str, live_path: str, kind: str, dry_run: bool) -> bool:
    snaps = _snapshots_for(name, live_path)
    if not snaps:
        print(f"[{name}] 跳过：无快照")
        return True
    snapshot = snaps[-1]
    if kind == "sqlite" and not check_db_integrity(snapshot):
        print(f"[{name}] 拒绝：最新快照完整性校验失败 {snapshot}")
        return False
    plan = f"[{name}] {os.path.basename(snapshot)} → {live_path}"
    if dry_run:
        print(f"DRY-RUN {plan}")
        return True
    if os.path.exists(live_path):
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        shutil.move(live_path, f"{live_path}.pre_restore.{ts}")
        # WAL 伴生文件一并挪开，避免新库配旧 WAL
        for suffix in ("-wal", "-shm"):
            side = live_path + suffix
            if os.path.exists(side):
                shutil.move(side, f"{side}.pre_restore.{ts}")
    shutil.copy2(snapshot, live_path)
    if kind == "sqlite":
        try:
            conn = sqlite3.connect(live_path)
            conn.execute("PRAGMA integrity_check")
            conn.close()
        except Exception as exc:
            print(f"[{name}] 恢复后校验异常：{exc}")
            return False
    print(f"RESTORED {plan}")
    return True


def cmd_restore(store: str | None, restore_all: bool, dry_run: bool) -> int:
    if _server_alive():
        print("拒绝执行：检测到后端服务仍在 8000 端口运行。先停服再恢复"
              "（活库恢复会被 WAL 句柄与进程内缓存破坏）。")
        return 2
    inventory = backup_inventory()
    if restore_all:
        targets = inventory
    else:
        targets = [t for t in inventory if t[0] == store]
        if not targets:
            names = ", ".join(t[0] for t in inventory)
            print(f"未知 store: {store}；可选：{names}")
            return 2
    ok = all(_restore_one(name, path, kind, dry_run) for name, path, kind in targets)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="备份列表与停服恢复")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_restore = sub.add_parser("restore")
    p_restore.add_argument("--store")
    p_restore.add_argument("--all", action="store_true")
    p_restore.add_argument("--latest", action="store_true", default=True)
    p_restore.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.cmd == "list":
        return cmd_list()
    if not args.all and not args.store:
        print("restore 需要 --store <name> 或 --all")
        return 2
    return cmd_restore(args.store, args.all, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
