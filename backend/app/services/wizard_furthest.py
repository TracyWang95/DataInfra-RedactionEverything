# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""从 Job config 中解析 wizard_furthest_step（int / str / float），供 jobs 列表与 files embed 共用。"""
from __future__ import annotations

from typing import Any


def infer_batch_step1_configured(config: dict[str, Any], job_type: str) -> bool:
    """与前端 jobPrimaryNavigation 一致：已持久化识别项选择时视为可进入上传步（断点继续）。"""
    if job_type == "text_batch":
        ids = config.get("entity_type_ids") or []
        return isinstance(ids, list) and len(ids) > 0
    ocr = config.get("ocr_has_types") or []
    hi = config.get("has_image_types") or []
    return (isinstance(ocr, list) and len(ocr) > 0) or (isinstance(hi, list) and len(hi) > 0)


def coerce_wizard_furthest_step(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return None
            n = int(float(s))
        elif isinstance(raw, (int, float)):
            n = int(raw)
        else:
            return None
    except (TypeError, ValueError):
        return None
    if 1 <= n <= 5:
        return n
    return None
