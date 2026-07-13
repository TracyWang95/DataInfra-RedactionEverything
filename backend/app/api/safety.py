"""
数据安全 API 路由
存储信息查询与一键清理。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.core.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/safety", tags=["数据安全"])


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
    logger.info("Cleanup: %d files, %d jobs", files_count, jobs_count)
    return {
        "files_removed": files_count,
        "jobs_removed": jobs_count,
    }
