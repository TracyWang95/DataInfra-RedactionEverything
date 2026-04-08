"""
文件列表构建服务 — 从 file_management_service.py 提取。

负责将 file_store 条目转换为前端所需的 FileListItem 列表，
包含批量分组、排序、Job embed 摘要等逻辑。
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Optional

from app.models.schemas import (
    FileListItem,
    FileType,
    JobEmbedSummary,
    JobItemMini,
)
from app.services.wizard_furthest import coerce_wizard_furthest_step, infer_batch_step1_configured


def _effective_upload_source(info: dict) -> str:
    """Deferred import wrapper — delegates to file_management_service."""
    from app.services.file_management_service import effective_upload_source
    return effective_upload_source(info)


def _entity_count(info: dict) -> int:
    """Deferred import wrapper — delegates to file_management_service."""
    from app.services.file_management_service import entity_count
    return entity_count(info)


# ---------------------------------------------------------------------------
# File list building
# ---------------------------------------------------------------------------

def build_file_list_items(
    filtered_entries: list[tuple[str, dict]],
    item_status_map: dict[str, dict],
) -> list[FileListItem]:
    """Build FileListItem list from filtered entries, grouped by batch."""
    batch_counts: dict[str, int] = defaultdict(int)
    for _fid, info in filtered_entries:
        bg = info.get("batch_group_id")
        if isinstance(bg, str) and bg.strip():
            batch_counts[bg.strip()] += 1

    raw_items: list[FileListItem] = []
    for fid, info in filtered_entries:
        ft = info.get("file_type")
        if ft is not None and not isinstance(ft, FileType):
            try:
                ft = FileType(ft) if isinstance(ft, str) else ft
            except (ValueError, KeyError):
                ft = FileType.DOCX
        bg_raw = info.get("batch_group_id")
        bg_key: Optional[str] = None
        if isinstance(bg_raw, str) and bg_raw.strip():
            bg_key = bg_raw.strip()
        cnt = batch_counts.get(bg_key) if bg_key else None
        eff = _effective_upload_source(info)
        jid = info.get("job_id")
        job_key = jid.strip() if isinstance(jid, str) and jid.strip() else None
        raw_items.append(
            FileListItem(
                file_id=fid,
                original_filename=info.get("original_filename", ""),
                file_size=int(info.get("file_size", 0)),
                file_type=ft if isinstance(ft, FileType) else FileType.DOCX,
                created_at=info.get("created_at"),
                has_output=bool(info.get("output_path")),
                entity_count=_entity_count(info),
                upload_source=eff,
                job_id=job_key,
                batch_group_id=bg_key,
                batch_group_count=cnt,
                item_status=(item_status_map.get(fid) or {}).get("status"),
                item_id=(item_status_map.get(fid) or {}).get("item_id"),
            )
        )
    return raw_items


def group_and_sort_items(raw_items: list[FileListItem]) -> list[FileListItem]:
    """Group items by batch, sort groups by newest timestamp descending."""
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
    return items


def build_job_embed_map(page_items: list[FileListItem], store: Any) -> dict[str, JobEmbedSummary]:
    """Build job embed summaries for page items that have job_id."""
    jids = {it.job_id for it in page_items if it.job_id}
    embed_map: dict[str, JobEmbedSummary] = {}
    for jid in jids:
        row = store.get_job(jid)
        if not row:
            continue
        jt = row.get("job_type")
        if jt not in ("text_batch", "image_batch", "smart_batch"):
            continue
        raw_items = store.list_items(jid)
        mini = [JobItemMini(id=str(x["id"]), status=str(x["status"])) for x in raw_items]
        first_awaiting_embed: str | None = None
        for x in raw_items:
            if str(x.get("status")) == "awaiting_review":
                first_awaiting_embed = str(x["id"])
                break
        progress = {
            "total_items": len(raw_items),
            "pending": sum(1 for x in raw_items if str(x.get("status")) == "pending"),
            "queued": sum(1 for x in raw_items if str(x.get("status")) == "queued"),
            "parsing": sum(1 for x in raw_items if str(x.get("status")) == "parsing"),
            "ner": sum(1 for x in raw_items if str(x.get("status")) == "ner"),
            "vision": sum(1 for x in raw_items if str(x.get("status")) == "vision"),
            "awaiting_review": sum(1 for x in raw_items if str(x.get("status")) == "awaiting_review"),
            "review_approved": sum(1 for x in raw_items if str(x.get("status")) == "review_approved"),
            "redacting": sum(1 for x in raw_items if str(x.get("status")) == "redacting"),
            "completed": sum(1 for x in raw_items if str(x.get("status")) == "completed"),
            "failed": sum(1 for x in raw_items if str(x.get("status")) == "failed"),
            "cancelled": sum(1 for x in raw_items if str(x.get("status")) == "cancelled"),
        }
        try:
            cfg_row = json.loads(row.get("config_json") or "{}")
        except json.JSONDecodeError:
            cfg_row = {}
        wf_embed = coerce_wizard_furthest_step(cfg_row.get("wizard_furthest_step"))
        step1_ok = infer_batch_step1_configured(cfg_row, jt)
        embed_map[jid] = JobEmbedSummary(
            status=str(row["status"]),
            job_type=jt,
            items=mini,
            progress=progress,
            wizard_furthest_step=wf_embed,
            first_awaiting_review_item_id=first_awaiting_embed,
            batch_step1_configured=step1_ok,
        )
    return embed_map
