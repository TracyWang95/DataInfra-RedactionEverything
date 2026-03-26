"""
文件管理 API 路由
处理文件上传、下载、解析等操作
"""
import io
import os
import re
import uuid
import zipfile
from collections import defaultdict
import aiofiles
from datetime import datetime, timezone
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Body, Query
from fastapi.responses import FileResponse, Response
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.persistence import load_json, save_json
from app.models.schemas import (
    FileUploadResponse,
    FileListResponse,
    FileListItem,
    ParseResult,
    NERResult,
    NERRequest,
    FileType,
    APIResponse,
)
from app.services.hybrid_ner_service import perform_hybrid_ner

router = APIRouter()

_BATCH_GROUP_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")


def _sanitize_batch_group_id(raw: Optional[str]) -> Optional[str]:
    """批量向导会话 ID：UUID 或短标识，非法则忽略（视为单文件）。"""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if len(s) > 80:
        s = s[:80]
    if not _BATCH_GROUP_ID_RE.match(s):
        return None
    return s


# 文件存储（磁盘持久化 + 内存缓存）
def _normalize_file_type(value):
    try:
        return FileType(value) if isinstance(value, str) else value
    except Exception:
        return value


def _bounding_box_total(info: dict) -> int:
    """图像/视觉链：bounding_boxes 为 {page: [BoundingBox, ...]} 或列表。"""
    raw = info.get("bounding_boxes")
    if not raw:
        return 0
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, dict):
        n = 0
        for v in raw.values():
            if isinstance(v, list):
                n += len(v)
        return n
    return 0


def _recognition_count_from_stored_fields(info: dict) -> int:
    """仅从 file_store 已有字段推断条数（不含 redacted_count）。"""
    ents = info.get("entities")
    n_text = len(ents) if isinstance(ents, list) else 0
    n_boxes = _bounding_box_total(info)
    n = n_text + n_boxes
    if n > 0:
        return n
    em = info.get("entity_map")
    if isinstance(em, dict) and len(em) > 0:
        return len(em)
    return 0


def _entity_count(info: dict) -> int:
    """
    处理历史「识别项」数量：
    - 已生成脱敏文件时优先使用 redacted_count（执行接口落库）；
    - 否则根据 entities / bounding_boxes / entity_map 推断。
    """
    if bool(info.get("output_path")) and isinstance(info.get("redacted_count"), int):
        return int(info["redacted_count"])
    return _recognition_count_from_stored_fields(info)


def _backfill_redacted_counts(store: dict[str, dict]) -> bool:
    """已脱敏但缺少 redacted_count 的旧记录：用可解析字段回填并落盘，避免列表恒为 0。"""
    changed = False
    for info in store.values():
        if not isinstance(info, dict):
            continue
        if not info.get("output_path"):
            continue
        if isinstance(info.get("redacted_count"), int):
            continue
        n = _recognition_count_from_stored_fields(info)
        if n > 0:
            info["redacted_count"] = n
            changed = True
    return changed


def _load_file_store() -> dict[str, dict]:
    raw = load_json(settings.FILE_STORE_PATH, default={}) or {}
    store: dict[str, dict] = {}
    for file_id, info in raw.items():
        if not isinstance(info, dict):
            continue
        file_path = info.get("file_path")
        if file_path and not os.path.exists(file_path):
            # 原始文件不存在，跳过
            continue
        info["file_type"] = _normalize_file_type(info.get("file_type"))
        store[file_id] = info
    if _backfill_redacted_counts(store):
        save_json(settings.FILE_STORE_PATH, store)
    return store


file_store: dict[str, dict] = _load_file_store()


def persist_file_store() -> None:
    save_json(settings.FILE_STORE_PATH, file_store)


class HybridNERRequest(BaseModel):
    """混合识别请求（HaS 固定为 NER）"""
    model_config = ConfigDict(extra="ignore")

    entity_type_ids: List[str] = Field(default_factory=list, description="要识别的实体类型ID列表")


class BatchDownloadRequest(BaseModel):
    """批量打包下载"""
    file_ids: List[str] = Field(..., min_length=1, description="要打包的文件 ID 列表")
    redacted: bool = Field(default=False, description="为 True 时打包脱敏后的文件（需已脱敏）")


@router.get("/files", response_model=FileListResponse)
async def list_files(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
):
    """列出已上传文件（处理历史）；同批次文件相邻排列，支持分页。"""
    batch_counts: dict[str, int] = defaultdict(int)
    for _fid, info in file_store.items():
        bg = info.get("batch_group_id")
        if isinstance(bg, str) and bg.strip():
            batch_counts[bg.strip()] += 1

    raw_items: list[FileListItem] = []
    for fid, info in file_store.items():
        ft = info.get("file_type")
        if ft is not None and not isinstance(ft, FileType):
            try:
                ft = FileType(ft) if isinstance(ft, str) else ft
            except Exception:
                ft = FileType.DOCX
        bg_raw = info.get("batch_group_id")
        bg_key: Optional[str] = None
        if isinstance(bg_raw, str) and bg_raw.strip():
            bg_key = bg_raw.strip()
        cnt = batch_counts.get(bg_key) if bg_key else None
        raw_items.append(
            FileListItem(
                file_id=fid,
                original_filename=info.get("original_filename", ""),
                file_size=int(info.get("file_size", 0)),
                file_type=ft if isinstance(ft, FileType) else FileType.DOCX,
                created_at=info.get("created_at"),
                has_output=bool(info.get("output_path")),
                entity_count=_entity_count(info),
                batch_group_id=bg_key,
                batch_group_count=cnt,
            )
        )

    groups: dict[str, list[FileListItem]] = defaultdict(list)
    for it in raw_items:
        gk = it.batch_group_id if it.batch_group_id else f"single:{it.file_id}"
        groups[gk].append(it)

    for gk in groups:
        groups[gk].sort(key=lambda x: x.created_at or "")

    def _group_max_ts(k: str) -> str:
        xs = groups[k]
        return max((x.created_at or "" for x in xs), default="")

    ordered_keys = sorted(groups.keys(), key=_group_max_ts, reverse=True)
    items: list[FileListItem] = []
    for k in ordered_keys:
        items.extend(groups[k])

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    return FileListResponse(
        files=page_items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/files/batch/download")
async def batch_download_zip(request: BatchDownloadRequest):
    """将多个文件打包为 ZIP 下载。"""
    seen: set[str] = set()
    unique_ids: list[str] = []
    for fid in request.file_ids:
        if fid not in seen:
            seen.add(fid)
            unique_ids.append(fid)

    missing: list[str] = []
    pairs: list[tuple[str, str]] = []
    used_names: dict[str, int] = {}

    for fid in unique_ids:
        if fid not in file_store:
            missing.append(fid)
            continue
        info = file_store[fid]
        if request.redacted:
            path = info.get("output_path")
            if not path or not os.path.isfile(path):
                missing.append(fid)
                continue
            base = f"redacted_{os.path.basename(info.get('original_filename', 'file'))}"
        else:
            path = info.get("file_path")
            if not path or not os.path.isfile(path):
                missing.append(fid)
                continue
            base = os.path.basename(info.get("original_filename", "file"))

        safe = os.path.basename(base) or "file"
        n = used_names.get(safe, 0)
        used_names[safe] = n + 1
        arcname = safe if n == 0 else f"{n}_{safe}"
        pairs.append((path, arcname))

    if missing:
        raise HTTPException(status_code=400, detail={"missing": missing})
    if not pairs:
        raise HTTPException(status_code=400, detail="没有可下载的文件（不存在或未脱敏）")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, arcname in pairs:
            zf.write(path, arcname)
    buf.seek(0)
    filename = "redacted_batch.zip" if request.redacted else "original_batch.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def get_file_type(filename: str) -> FileType:
    """根据文件扩展名判断文件类型"""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".doc":
        return FileType.DOC
    elif ext == ".docx":
        return FileType.DOCX
    elif ext == ".pdf":
        return FileType.PDF
    elif ext in [".jpg", ".jpeg", ".png"]:
        return FileType.IMAGE
    else:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")


def validate_file(file: UploadFile) -> None:
    """验证上传的文件"""
    # 检查文件扩展名
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, 
            detail=f"不支持的文件类型: {ext}，支持的类型: {settings.ALLOWED_EXTENSIONS}"
        )


@router.post("/files/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    batch_group_id: Optional[str] = Form(None),
):
    """
    上传文件
    
    支持的文件类型:
    - Word 文档 (.doc, .docx)
    - PDF 文档 (.pdf)
    - 图片 (.jpg, .jpeg, .png)
    """
    validate_file(file)
    
    # 生成唯一文件ID
    file_id = str(uuid.uuid4())
    file_ext = os.path.splitext(file.filename)[1].lower()
    stored_filename = f"{file_id}{file_ext}"
    file_path = os.path.join(settings.UPLOAD_DIR, stored_filename)
    
    # 保存文件
    try:
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
            file_size = len(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")
    
    # 检查文件大小
    if file_size > settings.MAX_FILE_SIZE:
        os.remove(file_path)
        raise HTTPException(
            status_code=400, 
            detail=f"文件过大，最大支持 {settings.MAX_FILE_SIZE // 1024 // 1024}MB"
        )
    
    file_type = get_file_type(file.filename)
    created_at = datetime.now(timezone.utc)
    bg = _sanitize_batch_group_id(batch_group_id)

    # 存储文件元信息
    file_store[file_id] = {
        "id": file_id,
        "original_filename": file.filename,
        "stored_filename": stored_filename,
        "file_path": file_path,
        "file_type": file_type,
        "file_size": file_size,
        "created_at": created_at.isoformat(),
        **({"batch_group_id": bg} if bg else {}),
    }
    persist_file_store()
    
    return FileUploadResponse(
        file_id=file_id,
        filename=file.filename,
        file_type=file_type,
        file_size=file_size,
        created_at=created_at,
    )


@router.get("/files/{file_id}/parse", response_model=ParseResult)
async def parse_file(file_id: str):
    """
    解析文件内容
    
    - 对于 Word/PDF: 提取文本内容
    - 对于图片/扫描版 PDF: 标记为需要视觉处理
    """
    from app.services.file_parser import FileParser

    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    file_info = file_store[file_id]
    file_path = file_info["file_path"]
    file_type = file_info["file_type"]
    
    parser = FileParser()
    result = await parser.parse(file_path, file_type)
    
    # 更新文件信息
    file_store[file_id].update({
        "content": result.content,
        "pages": result.pages,
        "page_count": result.page_count,
        "is_scanned": result.is_scanned,
    })
    persist_file_store()
    
    result.file_id = file_id
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
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    file_info = file_store[file_id]
    
    # 检查是否已解析
    if "content" not in file_info:
        raise HTTPException(status_code=400, detail="请先解析文件内容")
    
    # 如果是扫描件，返回空结果（需要视觉处理）
    if file_info.get("is_scanned", False):
        return NERResult(
            file_id=file_id,
            entities=[],
            entity_count=0,
            entity_summary={},
        )
    
    content = file_info["content"]
    
    # 获取实体类型配置
    from app.api.entity_types import get_enabled_types, entity_types_db
    
    # 确定要识别的类型
    if request.entity_type_ids:
        entity_types = [entity_types_db[tid] for tid in request.entity_type_ids if tid in entity_types_db]
    else:
        entity_types = get_enabled_types()
    
    try:
        # 执行混合识别（HaS + 正则）
        entities = await perform_hybrid_ner(content, entity_types)
        
        print(f"混合识别完成，共 {len(entities)} 个实体")
        
    except Exception as e:
        print(f"混合识别失败: {e}")
        import traceback
        traceback.print_exc()
        entities = []
    
    # 统计各类型实体数量
    entity_summary = {}
    for entity in entities:
        entity_type = entity.type
        entity_summary[entity_type] = entity_summary.get(entity_type, 0) + 1
    
    # 存储识别结果
    file_store[file_id]["entities"] = entities
    persist_file_store()
    
    return NERResult(
        file_id=file_id,
        entities=entities,
        entity_count=len(entities),
        entity_summary=entity_summary,
    )


@router.get("/files/{file_id}/ner", response_model=NERResult)
async def extract_entities(file_id: str):
    """
    对文件进行命名实体识别 (NER) - 使用默认实体类型
    
    识别文档中的敏感信息:
    - 人名、机构名
    - 身份证号、电话号码
    - 地址、银行卡号
    - 案件编号等
    """
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    file_info = file_store[file_id]
    
    # 检查是否已解析
    if "content" not in file_info:
        raise HTTPException(status_code=400, detail="请先解析文件内容")
    
    # 如果是扫描件，返回空结果（需要视觉处理）
    if file_info.get("is_scanned", False):
        return NERResult(
            file_id=file_id,
            entities=[],
            entity_count=0,
            entity_summary={},
        )
    
    from app.api.entity_types import get_enabled_types
    entity_types = get_enabled_types()
    entities = await perform_hybrid_ner(file_info["content"], entity_types)
    
    # 统计各类型实体数量
    entity_summary = {}
    for entity in entities:
        entity_type = entity.type
        entity_summary[entity_type] = entity_summary.get(entity_type, 0) + 1
    
    # 存储识别结果
    file_store[file_id]["entities"] = entities
    persist_file_store()
    
    return NERResult(
        file_id=file_id,
        entities=entities,
        entity_count=len(entities),
        entity_summary=entity_summary,
    )


@router.post("/files/{file_id}/ner", response_model=NERResult)
async def extract_entities_with_config(
    file_id: str,
    request: NERRequest = Body(default=NERRequest()),
):
    """
    对文件进行命名实体识别 (NER) - 支持自定义实体类型
    
    可以指定:
    - entity_types: 要识别的内置实体类型列表
    - custom_entity_type_ids: 要识别的自定义实体类型ID列表
    """
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    file_info = file_store[file_id]
    
    # 检查是否已解析
    if "content" not in file_info:
        raise HTTPException(status_code=400, detail="请先解析文件内容")
    
    # 如果是扫描件，返回空结果（需要视觉处理）
    if file_info.get("is_scanned", False):
        return NERResult(
            file_id=file_id,
            entities=[],
            entity_count=0,
            entity_summary={},
        )
    
    from app.api.entity_types import get_enabled_types
    entity_types = get_enabled_types()
    entities = await perform_hybrid_ner(file_info["content"], entity_types)
    
    # 统计各类型实体数量
    entity_summary = {}
    for entity in entities:
        entity_type = entity.type
        entity_summary[entity_type] = entity_summary.get(entity_type, 0) + 1
    
    # 存储识别结果
    file_store[file_id]["entities"] = entities
    persist_file_store()
    
    return NERResult(
        file_id=file_id,
        entities=entities,
        entity_count=len(entities),
        entity_summary=entity_summary,
    )


@router.get("/files/{file_id}")
async def get_file_info(file_id: str):
    """获取文件信息"""
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return file_store[file_id]


@router.get("/files/{file_id}/download")
async def download_file(file_id: str, redacted: bool = False):
    """
    下载文件
    
    - redacted=False: 下载原始文件
    - redacted=True: 下载脱敏后的文件
    """
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    file_info = file_store[file_id]
    
    if redacted:
        if "output_path" not in file_info:
            raise HTTPException(status_code=400, detail="文件尚未脱敏")
        file_path = file_info["output_path"]
        filename = f"redacted_{file_info['original_filename']}"
    else:
        file_path = file_info["file_path"]
        filename = file_info["original_filename"]
    
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
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    file_info = file_store[file_id]
    
    # 删除原始文件
    if os.path.exists(file_info["file_path"]):
        os.remove(file_info["file_path"])
    
    # 删除脱敏后的文件
    if "output_path" in file_info and os.path.exists(file_info["output_path"]):
        os.remove(file_info["output_path"])
    
    del file_store[file_id]
    persist_file_store()
    
    return APIResponse(message="文件删除成功")
