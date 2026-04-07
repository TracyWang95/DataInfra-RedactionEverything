# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
数据安全 API 路由
存储信息查询与一键清理。
"""
from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter

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
async def storage_info():
    """返回数据存储路径信息，便于用户了解文件存放位置。"""
    upload_size = _get_dir_size_cached(settings.UPLOAD_DIR)
    output_size = _get_dir_size_cached(settings.OUTPUT_DIR)
    return {
        "upload_dir": os.path.realpath(settings.UPLOAD_DIR),
        "output_dir": os.path.realpath(settings.OUTPUT_DIR),
        "db_path": os.path.realpath(settings.JOB_DB_PATH),
        "upload_size_bytes": upload_size,
        "output_size_bytes": output_size,
        "total_size_bytes": upload_size + output_size,
    }


@router.post("/cleanup")
async def cleanup_all_data():
    """一键清理所有上传文件、匿名化产物和任务记录。"""
    from app.services.file_management_service import get_file_store, get_file_store_lock
    from app.services.job_store import get_job_store

    file_store = get_file_store()
    _file_store_lock = get_file_store_lock()
    # 先统计用户文件数（file_store 记录数，不是磁盘文件数）
    async with _file_store_lock:
        files_count = len(file_store)
        file_store.clear()
    # 清磁盘
    for d in (settings.UPLOAD_DIR, settings.OUTPUT_DIR):
        if os.path.isdir(d):
            for f in os.listdir(d):
                fp = os.path.join(d, f)
                if os.path.isfile(fp):
                    try:
                        os.remove(fp)
                    except OSError:
                        pass
    # 清任务
    store = get_job_store()
    jobs_list, _ = store.list_jobs(page=1, page_size=10000)
    jobs_count = len(jobs_list)
    for j in jobs_list:
        try:
            store.delete_job(j["id"])
        except Exception:
            pass
    invalidate_dir_size_cache()
    logger.info("Cleanup: %d files, %d jobs", files_count, jobs_count)
    return {
        "files_removed": files_count,
        "jobs_removed": jobs_count,
    }
