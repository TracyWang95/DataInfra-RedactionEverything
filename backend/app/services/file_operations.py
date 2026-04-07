# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
Service-layer wrappers for file operations.

Decouples job_runner (and other service-layer callers) from direct
API-layer imports.  The functions here delegate to the service layer
(file_management_service / redaction_orchestrator).
"""
from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# file_store accessors – the store lives in the service layer.
# ---------------------------------------------------------------------------

def get_file_info(file_id: str) -> Optional[dict[str, Any]]:
    """Return the file-store dict for *file_id*, or ``None``."""
    from app.services.file_management_service import file_store
    return file_store.get(file_id)


# ---------------------------------------------------------------------------
# Thin async wrappers that delegate to service-layer implementations.
# ---------------------------------------------------------------------------

async def parse_file(file_id: str) -> None:
    """Parse an uploaded file (text extraction / scan detection)."""
    from app.services.file_management_service import parse_file as _parse
    await _parse(file_id)


async def hybrid_ner(file_id: str, entity_type_ids: list[str]) -> None:
    """Run hybrid NER (HaS model + regex) on an already-parsed file."""
    from app.services.file_management_service import run_hybrid_ner
    await run_hybrid_ner(file_id, entity_type_ids=entity_type_ids)


async def vision_detect(
    file_id: str,
    page: int,
    ocr_has_types: Optional[list[str]] = None,
    has_image_types: Optional[list[str]] = None,
) -> None:
    """Run dual-pipeline vision detection on a single page."""
    from app.services.redaction_orchestrator import detect_vision
    await detect_vision(
        file_id=file_id,
        page=page,
        selected_ocr_has_types=ocr_has_types,
        selected_has_image_types=has_image_types,
        has_request=True,
    )


async def execute_redaction_request(
    file_id: str,
    entities: list,
    bounding_boxes: list,
    config: Any,
) -> None:
    """Execute redaction via the service layer."""
    from app.services.redaction_orchestrator import execute_redaction
    from app.models.schemas import RedactionRequest
    req = RedactionRequest(
        file_id=file_id,
        entities=entities,
        bounding_boxes=bounding_boxes,
        config=config,
    )
    await execute_redaction(req)
