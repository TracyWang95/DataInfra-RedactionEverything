"""
文件解析与 NER 执行服务 — 从 file_management_service.py 提取。

负责文件内容解析 (parse_file) 和混合 NER 识别 (run_hybrid_ner / run_default_ner)。
所有函数依赖 file_store / _file_store_lock 单例，通过延迟导入获取。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _store_and_lock():
    """Deferred import to avoid circular dependency at module load time."""
    from app.services.file_management_service import _file_store_lock, file_store
    return file_store, _file_store_lock


def _assign_pages_to_entities(entities: list, pages: list[str] | None) -> None:
    """Mutate each entity's `page` attribute based on `entity.start` offset.

    Assumes `content = "\\n\\n".join(pages)` (matches file_parser._parse_pdf).
    No-op when there's only a single page or pages are missing — entities
    keep their default page=1.
    """
    if not pages or len(pages) <= 1 or not entities:
        return
    sep_len = 2  # "\n\n"
    ranges: list[tuple[int, int, int]] = []
    offset = 0
    for idx, page_text in enumerate(pages, start=1):
        length = len(page_text or "")
        ranges.append((offset, offset + length, idx))
        offset += length + sep_len
    last_page = ranges[-1][2]
    for entity in entities:
        start_val = getattr(entity, "start", None)
        if start_val is None and isinstance(entity, dict):
            start_val = entity.get("start")
        try:
            start = int(start_val or 0)
        except (TypeError, ValueError):
            start = 0
        page_num = last_page
        for _r_start, r_end, p in ranges:
            if start < r_end:
                page_num = p
                break
        if isinstance(entity, dict):
            entity["page"] = page_num
        else:
            try:
                entity.page = page_num
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

async def parse_file(file_id: str) -> dict[str, Any]:
    """
    Parse an uploaded file. Returns ParseResult-compatible dict.
    Raises ValueError if file not found.
    """
    from app.models.schemas import FileType
    from app.services.file_parser import FileParser

    file_store, _file_store_lock = _store_and_lock()

    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info:
            raise ValueError(f"file_id={file_id} NOT in file_store (keys={len(file_store)}, path={file_store._path})")
        snapshot = dict(file_info)

    file_path = snapshot["file_path"]
    file_type = snapshot["file_type"]
    parser_file_type = (
        FileType.PDF
        if str(getattr(file_type, "value", file_type)) == FileType.PDF_SCANNED.value
        else file_type
    )

    parser = FileParser()
    result = await parser.parse(file_path, parser_file_type)

    async with _file_store_lock:
        if file_id in file_store:
            # Also update file_type: upload records it from magic bytes ("pdf"),
            # but _parse_pdf re-classifies scanned PDFs to PDF_SCANNED. Without
            # syncing, redactor dispatches on the stale "pdf" and runs the text
            # pipeline on a scanned file, producing an unchanged output file.
            resolved_file_type = (
                result.file_type.value
                if hasattr(result.file_type, "value")
                else str(result.file_type)
            )
            file_store.update_fields(file_id, {
                "file_type": resolved_file_type,
                "content": result.content,
                "pages": result.pages,
                "page_count": result.page_count,
                "is_scanned": result.is_scanned,
            })

    result.file_id = file_id
    return result


# ---------------------------------------------------------------------------
# Hybrid NER
# ---------------------------------------------------------------------------

async def run_hybrid_ner(
    file_id: str,
    entity_type_ids: list[str] | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """
    Run hybrid NER on parsed file. Returns NERResult-compatible values.
    Raises ValueError if file not found or not yet parsed.
    """
    from app.services.hybrid_ner_service import HybridNERService, perform_hybrid_ner

    file_store, _file_store_lock = _store_and_lock()

    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info:
            raise ValueError("文件不存在")
        snapshot = dict(file_info)
    owner_id = owner_id or str(snapshot.get("owner_id") or "local_user")

    if "content" not in snapshot:
        raise ValueError("请先解析文件内容")

    if snapshot.get("is_scanned", False):
        return {"entities": [], "entity_count": 0, "entity_summary": {}, "warnings": []}

    content = snapshot["content"]

    from app.services.entity_type_service import get_default_generic_types, resolve_requested_entity_types

    if entity_type_ids is None:
        entity_types = get_default_generic_types(owner_id=owner_id)
    else:
        entity_types = resolve_requested_entity_types(entity_type_ids, owner_id=owner_id)

    warnings: list[str] = []
    if len(content) > HybridNERService.MAX_TEXT_LENGTH:
        warnings.append(
            f"文本过长（{len(content)} 字符），已截断至 {HybridNERService.MAX_TEXT_LENGTH} 字符，"
            "超出部分未进行识别。"
        )

    logger.info(
        "Hybrid NER requested types=%s resolved=%s",
        entity_type_ids,
        [getattr(entity_type, "id", None) for entity_type in entity_types],
    )

    try:
        entities = await perform_hybrid_ner(content, entity_types)
        logger.info("混合识别完成，共 %d 个实体", len(entities))
    except Exception as e:
        logger.exception("混合识别失败: %s", e)
        return {
            "entities": [],
            "entity_count": 0,
            "entity_summary": {},
            "warnings": warnings,
            "recognition_failed": True,
            "error": str(e),
        }

    _assign_pages_to_entities(entities, snapshot.get("pages"))

    entity_summary = {}
    for ent in entities:
        etype = ent.type
        entity_summary[etype] = entity_summary.get(etype, 0) + 1

    async with _file_store_lock:
        if file_id in file_store:
            file_store.update_fields(file_id, {
                "entities": entities,
                "recognition_config": {
                    "entity_type_ids": entity_type_ids,
                    "resolved_entity_type_ids": [
                        getattr(entity_type, "id", None) for entity_type in entity_types
                    ],
                },
            })

    return {
        "entities": entities,
        "entity_count": len(entities),
        "entity_summary": entity_summary,
        "warnings": warnings,
    }


async def run_default_ner(
    file_id: str,
    entity_type_ids: list[str] | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """Run NER with default or caller-specified entity types."""
    from app.services.hybrid_ner_service import perform_hybrid_ner

    file_store, _file_store_lock = _store_and_lock()

    async with _file_store_lock:
        file_info = file_store.get(file_id)
        if not file_info:
            raise ValueError("文件不存在")
        snapshot = dict(file_info)
    owner_id = owner_id or str(snapshot.get("owner_id") or "local_user")

    if "content" not in snapshot:
        raise ValueError("请先解析文件内容")

    if snapshot.get("is_scanned", False):
        return {"entities": [], "entity_count": 0, "entity_summary": {}}

    from app.services.entity_type_service import get_default_generic_types, resolve_requested_entity_types

    if entity_type_ids is None:
        entity_types = get_default_generic_types(owner_id=owner_id)
    else:
        entity_types = resolve_requested_entity_types(entity_type_ids, owner_id=owner_id)
    try:
        entities = await perform_hybrid_ner(snapshot["content"], entity_types)
    except Exception as e:
        logger.exception("默认识别失败: %s", e)
        return {
            "entities": [],
            "entity_count": 0,
            "entity_summary": {},
            "recognition_failed": True,
            "error": str(e),
        }

    _assign_pages_to_entities(entities, snapshot.get("pages"))

    entity_summary = {}
    for ent in entities:
        etype = ent.type
        entity_summary[etype] = entity_summary.get(etype, 0) + 1

    async with _file_store_lock:
        if file_id in file_store:
            file_store.update_fields(file_id, {
                "entities": entities,
                "recognition_config": {
                    "entity_type_ids": entity_type_ids,
                    "resolved_entity_type_ids": [
                        getattr(entity_type, "id", None) for entity_type in entity_types
                    ],
                },
            })

    return {
        "entities": entities,
        "entity_count": len(entities),
        "entity_summary": entity_summary,
    }
