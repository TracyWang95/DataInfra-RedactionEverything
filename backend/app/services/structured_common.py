"""Shared primitives for the structured data service modules.

Implementation split out of structured_service.py; structured_service.py stays the
public import surface and re-exports everything defined here.
"""
from __future__ import annotations

import base64
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

SUPPORTED_FILE_EXTENSIONS = {".csv": "csv", ".xlsx": "xlsx", ".jsonl": "jsonl", ".db": "sqlite", ".sqlite": "sqlite"}
MAX_PROFILE_ROWS = 500
MAX_PREVIEW_ROWS = 100
MAX_EXPORT_ROWS = 250_000


@dataclass(frozen=True)
class LoadedTable:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count_estimate: int | None = None


# Shape heuristics (names for literals).
_WIDE_TABLE_COLUMN_THRESHOLD = 80


def utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def safe_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "data")).strip("._")
    return stem[:120] or "data"


def quote_sqlite_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def cell_to_json(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def infer_runtime_type(values: Iterable[Any]) -> str:
    sample = [value for value in values if value not in (None, "")]
    if not sample:
        return "string"
    if all(isinstance(value, bool) for value in sample):
        return "boolean"
    if all(is_number_like(value) for value in sample):
        return "number"
    return "string"


def infer_shape_kind(columns: list[str], rows: list[dict[str, Any]]) -> str:
    lowered = " ".join(col.lower() for col in columns)
    if len(columns) >= _WIDE_TABLE_COLUMN_THRESHOLD:
        return "wide_feature_table"
    if ("event" in lowered or "action" in lowered or "status" in lowered) and (
        "time" in lowered or "date" in lowered
    ):
        return "event_log"
    if {"key", "value"}.issubset({col.lower() for col in columns}):
        return "json_kv_table"
    nested = 0
    for row in rows[:50]:
        nested += sum(1 for value in row.values() if isinstance(value, list | dict))
    if rows and nested / max(1, len(rows)) >= 1:
        return "json_kv_table"
    return "flat_table"


def is_number_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float | Decimal):
        return True
    text = str(value).strip().replace(",", "").replace("楼", "")
    if not text:
        return False
    try:
        Decimal(text)
        return True
    except InvalidOperation:
        return False


def normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value).strip()


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", normalize_value(value))


def base64_preview(value: bytes) -> str:
    return base64.b64encode(value[:24]).decode("ascii")
