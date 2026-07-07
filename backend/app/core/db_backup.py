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

MAX_BACKUPS = 24  # 保留最近 24 个备份（backup_all 可用 BACKUP_RETENTION_COUNT 覆盖）

# 例行备份状态注册表（/health/services 只读时间戳，不暴露路径）
_backup_status: dict[str, dict[str, str | None]] = {}


def get_backup_status() -> dict[str, dict[str, str | None]]:
    return {name: dict(entry) for name, entry in _backup_status.items()}


def backup_inventory() -> list[tuple[str, str, str]]:
    """声明式备份清单：(名称, 路径, 类型 sqlite|small_file)。

    覆盖全部持久化状态：4 个 SQLite 库 + 配置/凭据小文件。
    jwt_secret.json 与 structured_credentials.key 必须入册——缺了它们，
    恢复出的令牌与数据库凭据都解不开。文件不存在则跳过。
    """
    from app.core.config import settings

    targets: list[tuple[str, str, str]] = [
        ("jobs", settings.JOB_DB_PATH, "sqlite"),
        ("structured_store", os.path.join(settings.DATA_DIR, "structured_store.sqlite3"), "sqlite"),
    ]
    try:
        from app.services.file_management_service import get_file_store

        fs = get_file_store()
        if hasattr(fs, "db_path"):
            targets.append(("file_store", fs.db_path, "sqlite"))
    except Exception:
        logger.debug("backup inventory: file_store unavailable", exc_info=True)
    try:
        from app.core.token_blacklist import get_blacklist

        bl = get_blacklist()
        if hasattr(bl, "db_path"):
            targets.append(("token_blacklist", bl.db_path, "sqlite"))
    except Exception:
        logger.debug("backup inventory: token_blacklist unavailable", exc_info=True)

    small_files = [
        ("auth", os.path.join(settings.DATA_DIR, "auth.json")),
        ("jwt_secret", os.path.join(settings.DATA_DIR, "jwt_secret.json")),
        ("structured_credentials", os.path.join(settings.DATA_DIR, "structured_credentials.key")),
        ("presets", settings.PRESET_STORE_PATH),
        ("entity_types", settings.ENTITY_TYPES_STORE_PATH),
        ("pipelines", settings.PIPELINE_STORE_PATH),
        ("model_config", settings.MODEL_CONFIG_PATH),
        ("runtime_settings", os.path.join(settings.DATA_DIR, "runtime_settings.json")),
    ]
    for name, path in small_files:
        if path:
            targets.append((name, path, "small_file"))
    return targets


def _snapshot_small_file(name: str, src_path: str, backup_dir: str, retention: int) -> str | None:
    """小文件原子快照：读字节 → 写 .tmp → fsync → os.replace（照 auth.py 模式）。"""
    if not os.path.exists(src_path):
        return None
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    ext = os.path.splitext(src_path)[1] or ".bin"
    final_path = os.path.join(backup_dir, f"{name}_{timestamp}{ext}")
    tmp_path = final_path + ".tmp"
    try:
        with open(src_path, "rb") as fh:
            payload = fh.read()
        with open(tmp_path, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, final_path)
        _cleanup_old_backups(backup_dir, name, retention=retention, ext=ext)
        return final_path
    except Exception:
        logger.exception("small-file backup failed: %s", name)
        for leftover in (tmp_path, final_path):
            if os.path.exists(leftover):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
        return None


def backup_all(backup_dir: str | None = None, retention: int | None = None) -> dict[str, bool]:
    """按清单备份全部存储，更新状态注册表。返回 {名称: 是否成功}。"""
    from app.core.config import settings

    target_dir = backup_dir or getattr(settings, "BACKUP_DIR", "") or os.path.join(
        settings.DATA_DIR, "backups"
    )
    keep = retention or getattr(settings, "BACKUP_RETENTION_COUNT", MAX_BACKUPS)
    results: dict[str, bool] = {}
    for name, path, kind in backup_inventory():
        if not os.path.exists(path):
            continue
        if kind == "sqlite":
            ok = backup_sqlite(path, target_dir, retention=keep) is not None
        else:
            ok = _snapshot_small_file(name, path, target_dir, keep) is not None
        results[name] = ok
        _backup_status[name] = {
            "last_success_at": datetime.now(UTC).isoformat() if ok else
            (_backup_status.get(name, {}).get("last_success_at")),
            "last_error": None if ok else "backup failed",
        }
    return results


def backup_sqlite(db_path: str, backup_dir: str | None = None, retention: int | None = None) -> str | None:
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
        _cleanup_old_backups(backup_dir, db_name, retention=retention)
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


def _cleanup_old_backups(
    backup_dir: str, db_name: str, retention: int | None = None, ext: str = ".sqlite3"
) -> int:
    """删除超出保留数量的旧备份。"""
    keep = retention if retention and retention > 0 else MAX_BACKUPS
    pattern = os.path.join(backup_dir, f"{db_name}_*{ext}")
    backups = sorted(glob(pattern))
    removed = 0
    while len(backups) > keep:
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
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        ok = result and result[0] == "ok"
        if not ok:
            logger.error("Database integrity check FAILED: %s → %s", db_path, result)
        return ok
    except Exception:
        logger.exception("Database integrity check error: %s", db_path)
        return False
    finally:
        # 损坏文件路径上曾泄漏连接句柄（Windows 下会锁死后续 move）
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


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
