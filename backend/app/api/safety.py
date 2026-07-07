"""
数据安全 API 路由
存储信息查询与一键清理。
"""
from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter, Depends

from app.core.auth import require_auth
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/safety", tags=["数据安全"])

# Simple time-based cache for directory size calculations
_dir_size_cache: dict[str, tuple[float, int]] = {}  # path -> (timestamp, size_bytes)
_DIR_SIZE_CACHE_TTL = 60  # seconds


def _get_dir_size_cached(directory: str) -> int:
    now = time.monotonic()
    cached = _dir_size_cache.get(directory)
    if cached and (now - cached[0]) < _DIR_SIZE_CACHE_TTL:
        return cached[1]
    if not os.path.isdir(directory):
        _dir_size_cache[directory] = (now, 0)
        return 0
    total = 0
    try:
        for f in os.listdir(directory):
            fp = os.path.join(directory, f)
            if os.path.isfile(fp):
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except OSError:
        pass
    _dir_size_cache[directory] = (now, total)
    return total


def invalidate_dir_size_cache() -> None:
    _dir_size_cache.clear()


@router.get("/storage-info")
async def storage_info(owner_id: str = Depends(require_auth)):
    """返回数据存储路径信息，便于用户了解文件存放位置。"""
    from app.services.file_management_service import file_owner_id, get_file_store

    upload_size = 0
    output_size = 0
    for _fid, info in get_file_store().project_fields(("owner_id", "file_path", "output_path")):
        if file_owner_id(info) != owner_id:
            continue
        for key, expected_dir in (("file_path", settings.UPLOAD_DIR), ("output_path", settings.OUTPUT_DIR)):
            path = info.get(key) if isinstance(info, dict) else None
            if isinstance(path, str) and path and os.path.isfile(path):
                real_path = os.path.realpath(path)
                if os.path.commonpath([real_path, os.path.realpath(expected_dir)]) == os.path.realpath(expected_dir):
                    if key == "file_path":
                        upload_size += os.path.getsize(real_path)
                    else:
                        output_size += os.path.getsize(real_path)
    return {
        "upload_dir": os.path.realpath(settings.UPLOAD_DIR),
        "output_dir": os.path.realpath(settings.OUTPUT_DIR),
        "db_path": os.path.realpath(settings.JOB_DB_PATH),
        "upload_size_bytes": upload_size,
        "output_size_bytes": output_size,
        "total_size_bytes": upload_size + output_size,
    }


@router.post("/cleanup")
async def cleanup_all_data(owner_id: str = Depends(require_auth)):
    """一键清理所有上传文件、匿名化产物和任务记录。"""
    from app.services.file_management_service import delete_file, file_owner_id, get_file_store, get_file_store_lock
    from app.services.job_store import get_job_store

    file_store = get_file_store()
    _file_store_lock = get_file_store_lock()
    # 先统计用户文件数（file_store 记录数，不是磁盘文件数）
    async with _file_store_lock:
        owned_file_ids = [fid for fid, info in file_store.items() if file_owner_id(info) == owner_id]
    # 清磁盘
    files_count = 0
    for file_id in owned_file_ids:
        if await delete_file(file_id):
            files_count += 1
    store = get_job_store()
    jobs_count = store.clear_jobs_for_owner(owner_id)
    invalidate_dir_size_cache()
    logger.info("Cleanup: %d files, %d jobs", files_count, jobs_count)
    return {
        "files_removed": files_count,
        "jobs_removed": jobs_count,
    }
