"""
SQLite 数据库备份 — 定时备份 + 启动时损坏检测。

策略：
- 每小时使用 SQLite Online Backup API 创建热备份
- 保留最近 24 个备份（1天）
- 启动时检测数据库完整性，损坏时自动恢复最近备份
"""
import logging
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from glob import glob

logger = logging.getLogger(__name__)

MAX_BACKUPS = 24  # 保留最近 24 个备份


def backup_sqlite(db_path: str, backup_dir: str | None = None) -> str | None:
    """
    使用 SQLite Online Backup API 创建热备份（不阻塞读写）。
    返回备份文件路径，失败返回 None。
    """
    if not os.path.exists(db_path):
        return None

    if backup_dir is None:
        backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    db_name = os.path.splitext(os.path.basename(db_path))[0]
    backup_path = os.path.join(backup_dir, f"{db_name}_{timestamp}.sqlite3")

    try:
        source = sqlite3.connect(db_path)
        dest = sqlite3.connect(backup_path)
        source.backup(dest)
        dest.close()
        source.close()
        logger.info("Database backup created: %s", backup_path)
        _cleanup_old_backups(backup_dir, db_name)
        return backup_path
    except Exception:
        logger.exception("Database backup failed: %s", db_path)
        # 清理失败的备份文件
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except OSError:
                pass
        return None


def _cleanup_old_backups(backup_dir: str, db_name: str) -> int:
    """删除超出保留数量的旧备份。"""
    pattern = os.path.join(backup_dir, f"{db_name}_*.sqlite3")
    backups = sorted(glob(pattern))
    removed = 0
    while len(backups) > MAX_BACKUPS:
        old = backups.pop(0)
        try:
            os.remove(old)
            removed += 1
        except OSError:
            pass
    return removed


def check_db_integrity(db_path: str) -> bool:
    """检查 SQLite 数据库完整性。"""
    if not os.path.exists(db_path):
        return True  # 不存在视为正常（会自动创建）
    try:
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        ok = result and result[0] == "ok"
        if not ok:
            logger.error("Database integrity check FAILED: %s → %s", db_path, result)
        return ok
    except Exception:
        logger.exception("Database integrity check error: %s", db_path)
        return False


def restore_from_latest_backup(db_path: str, backup_dir: str | None = None) -> bool:
    """从最近的备份恢复数据库。"""
    if backup_dir is None:
        backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    db_name = os.path.splitext(os.path.basename(db_path))[0]
    pattern = os.path.join(backup_dir, f"{db_name}_*.sqlite3")
    backups = sorted(glob(pattern))
    if not backups:
        logger.error("No backups found for %s", db_path)
        return False

    latest = backups[-1]
    # 验证备份完整性
    if not check_db_integrity(latest):
        logger.error("Latest backup is also corrupted: %s", latest)
        return False

    # 备份当前损坏的文件
    corrupted_path = db_path + ".corrupted"
    try:
        if os.path.exists(db_path):
            shutil.move(db_path, corrupted_path)
        shutil.copy2(latest, db_path)
        logger.info("Restored database from backup: %s → %s", latest, db_path)
        return True
    except Exception:
        logger.exception("Failed to restore from backup")
        return False


def ensure_db_healthy(db_path: str) -> None:
    """启动时调用：检查完整性，损坏时自动恢复。"""
    if not os.path.exists(db_path):
        return
    if check_db_integrity(db_path):
        return
    logger.warning("Database corrupted, attempting restore: %s", db_path)
    if restore_from_latest_backup(db_path):
        logger.info("Database restored successfully")
    else:
        logger.error("Database restore failed. Manual intervention required.")
