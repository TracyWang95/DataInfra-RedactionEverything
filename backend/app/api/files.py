"""
文件管理 API 路由
处理文件上传、下载、解析等操作

Thin routing layer — business logic lives in
app.services.file_management_service.
"""
import logging
import os
import shutil
import uuid

import aiofiles

logger = logging.getLogger(__name__)


from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

import app.services.file_management_service as _fms
from app.api.jobs import get_job_store
from app.core.audit import audit_log
from app.core.config import settings
from app.core.idempotency import check_idempotency, save_idempotency
from app.models.schemas import (
    APIResponse,
    BatchDownloadRequest,
    FileListResponse,
    FileUploadResponse,
    HybridNERRequest,
    NERRequest,
    NERResult,
    ParseResult,
)
from app.services.job_store import JobStore

router = APIRouter()


def validate_file(file: UploadFile) -> None:
    """验证上传的文件"""
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，支持的类型: {settings.ALLOWED_EXTENSIONS}"
        )


@router.get("/files", response_model=FileListResponse)
async def list_files(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    source: str | None = Query(
        None,
        description="按来源筛选：playground（仅 Playground）| batch（批量/任务）；不传为全部",
    ),
    embed_job: bool = Query(
        False,
        description="为 true 时对本页含 job_id 的行注入 job_embed（状态、类型、items 摘要），避免前端逐条 getJob",
    ),
    job_id: str | None = Query(None, description="按 job_id 筛选，仅返回属于该任务的文件"),
    store: JobStore = Depends(get_job_store),
):
    """列出已上传文件（处理历史）；同批次文件相邻排列，支持分页与来源筛选。"""
    src_filter: str | None = None
    if source is not None and str(source).strip():
        s = str(source).strip().lower()
        if s not in ("playground", "batch"):
            raise HTTPException(status_code=400, detail="source 须为 playground 或 batch")
        src_filter = s

    # 如果指定了 job_id，先取该任务的所有 file_id 做白名单
    job_file_ids: set[str] | None = None
    if job_id:
        items = store.list_items(job_id)
        job_file_ids = {it["file_id"] for it in items}

    file_store = _fms.get_file_store()
    filtered_entries: list[tuple[str, dict]] = []
    for fid, info in file_store.items():
        if not isinstance(info, dict):
            continue
        if job_file_ids is not None and fid not in job_file_ids:
            continue
        eff = _fms.effective_upload_source(info)
        if src_filter and eff != src_filter:
            continue
        filtered_entries.append((fid, info))

    # 批量查找 item_status
    all_file_ids = [fid for fid, _ in filtered_entries]
    item_status_map = store.batch_find_item_statuses(all_file_ids)

    raw_items = _fms.build_file_list_items(filtered_entries, item_status_map)
    items = _fms.group_and_sort_items(raw_items)

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]

    if embed_job and page_items:
        embed_map = _fms.build_job_embed_map(page_items, store)
        if embed_map:
            page_items = [
                it.model_copy(update={"job_embed": embed_map[it.job_id]})
                if it.job_id and it.job_id in embed_map
                else it
                for it in page_items
            ]

    return FileListResponse(
        files=page_items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/files/batch/download")
async def batch_download_zip(request: BatchDownloadRequest):
    """将多个文件打包为 ZIP 下载。"""
    try:
        zip_bytes, filename = _fms.build_batch_zip(request)
    except ValueError as exc:
        detail = exc.args[0] if exc.args else str(exc)
        if isinstance(detail, list):
            raise HTTPException(status_code=400, detail={"missing": detail})
        raise HTTPException(status_code=400, detail=detail)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/files/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    batch_group_id: str | None = Form(None),
    job_id: str | None = Form(None),
    upload_source: str | None = Form(None),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
):
    """
    上传文件

    支持的文件类型:
    - Word 文档 (.doc, .docx)
    - PDF 文档 (.pdf)
    - 图片 (.jpg, .jpeg, .png)
    """
    cached = check_idempotency(x_idempotency_key)
    if cached is not None:
        return cached

    validate_file(file)

    # 生成唯一文件ID
    file_id = str(uuid.uuid4())
    file_ext = os.path.splitext(file.filename)[1].lower()
    stored_filename = f"{file_id}{file_ext}"
    file_path = os.path.realpath(os.path.join(settings.UPLOAD_DIR, stored_filename))

    # 磁盘空间检查
    disk = shutil.disk_usage(os.path.dirname(file_path))
    if disk.free < 500 * 1024 * 1024:
        raise HTTPException(status_code=507, detail="磁盘空间不足，请清理后重试")

    # 保存文件（流式读取，边读边验证大小）
    CHUNK_SIZE = 1024 * 1024  # 1MB
    file_size = 0
    try:
        async with aiofiles.open(file_path, 'wb') as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > settings.MAX_FILE_SIZE:
                    await f.close()
                    os.remove(file_path)
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件过大，最大支持 {settings.MAX_FILE_SIZE // 1024 // 1024}MB",
                    )
                await f.write(chunk)
    except HTTPException:
        raise
    except OSError:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail="文件保存失败，请稍后重试")

    # Delegate to service layer for validation and registration
    try:
        response_and_jid = await _fms.process_upload(
            file_path=file_path,
            file_ext=file_ext,
            filename=file.filename,
            file_size=file_size,
            batch_group_id=batch_group_id,
            job_id=job_id,
            upload_source=upload_source,
        )
        response, jid = response_and_jid
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if jid:
        try:
            _fms.register_file_with_job(jid, response.file_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except HTTPException:
            raise
        except Exception:
            logger.exception("Failed to register file %s with job %s, rolling back", response.file_id, jid)
            await _fms.rollback_upload(response.file_id, file_path)
            raise HTTPException(status_code=500, detail="任务注册失败，文件已回滚")

    audit_log("upload", "file", response.file_id, detail={"filename": file.filename})
    save_idempotency(x_idempotency_key, response)
    return response


@router.get("/files/{file_id}/parse", response_model=ParseResult)
async def parse_file(file_id: str):
    """
    解析文件内容

    - 对于 Word/PDF: 提取文本内容
    - 对于图片/扫描版 PDF: 标记为需要视觉处理
    """
    try:
        result = await _fms.parse_file(file_id)
    except ValueError as exc:
        if "NOT in file_store" in str(exc) or "不存在" in str(exc):
            logger.error("parse_file: %s", exc)
            raise HTTPException(status_code=404, detail="文件不存在")
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/files/{file_id}/ner/hybrid", response_model=NERResult)
async def hybrid_ner_extract(
    file_id: str,
    request: HybridNERRequest = Body(default=HybridNERRequest()),
):
    """
    混合NER识别 - HaS本地模型 + 正则

    工作流程:
    1. Stage 1: HaS 本地模型识别
    2. Stage 2: 正则识别（高置信度模式匹配）
    3. Stage 3: 交叉验证 + 指代消解
    """
    if hasattr(request, 'entity_type_ids') and request.entity_type_ids and len(request.entity_type_ids) > 200:
        raise HTTPException(status_code=400, detail="实体类型数量超过上限（200）")

    try:
        ner_result = await _fms.run_hybrid_ner(file_id, entity_type_ids=request.entity_type_ids)
    except ValueError as exc:
        detail = str(exc)
        if "不存在" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)

    return NERResult(
        file_id=file_id,
        entities=ner_result["entities"],
        entity_count=ner_result["entity_count"],
        entity_summary=ner_result["entity_summary"],
        warnings=ner_result.get("warnings"),
    )


@router.get("/files/{file_id}/ner", response_model=NERResult)
async def extract_entities(file_id: str):
    """
    对文件进行命名实体识别 (NER) - 使用默认实体类型
    """
    try:
        ner_result = await _fms.run_default_ner(file_id)
    except ValueError as exc:
        detail = str(exc)
        if "不存在" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)

    return NERResult(
        file_id=file_id,
        entities=ner_result["entities"],
        entity_count=ner_result["entity_count"],
        entity_summary=ner_result["entity_summary"],
    )


@router.post("/files/{file_id}/ner", response_model=NERResult)
async def extract_entities_with_config(
    file_id: str,
    request: NERRequest = Body(default=NERRequest()),
):
    """
    对文件进行命名实体识别 (NER) - 支持自定义实体类型
    """
    # Merge built-in entity_types and custom_entity_type_ids into a single list
    entity_type_ids = (request.entity_types or []) + (request.custom_entity_type_ids or [])
    try:
        ner_result = await _fms.run_default_ner(
            file_id,
            entity_type_ids=entity_type_ids if entity_type_ids else None,
        )
    except ValueError as exc:
        detail = str(exc)
        if "不存在" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)

    return NERResult(
        file_id=file_id,
        entities=ner_result["entities"],
        entity_count=ner_result["entity_count"],
        entity_summary=ner_result["entity_summary"],
    )


@router.get("/files/{file_id}")
async def get_file_info(file_id: str):
    """获取文件信息"""
    info = await _fms.get_file_info(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="文件不存在")
    return info


@router.get("/files/{file_id}/download")
async def download_file(file_id: str, redacted: bool = False):
    """
    下载文件

    - redacted=False: 下载原始文件
    - redacted=True: 下载匿名化后的文件
    """
    snapshot = await _fms.get_file_snapshot(file_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="文件不存在")

    if redacted:
        if "output_path" not in snapshot:
            raise HTTPException(status_code=400, detail="文件尚未匿名化")
        file_path = snapshot["output_path"]
        filename = f"redacted_{snapshot['original_filename']}"
    else:
        file_path = snapshot["file_path"]
        filename = snapshot["original_filename"]

    # 路径遍历保护
    expected_dir = settings.OUTPUT_DIR if redacted else settings.UPLOAD_DIR
    if not _fms.safe_path_in_dir(file_path, expected_dir):
        raise HTTPException(status_code=403, detail="禁止访问该路径")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@router.delete("/files/{file_id}")
async def delete_file(file_id: str):
    """删除文件"""
    snapshot = await _fms.delete_file(file_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="文件不存在")
    audit_log("delete", "file", file_id)
    return APIResponse(message="文件删除成功")
