"""
Service-layer wrappers for file operations.

Decouples job_runner (and other service-layer callers) from direct
API-layer imports.  The functions here are thin delegates today; a
future refactor can move the real business logic out of the API
endpoints and into this module.
"""
from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# file_store accessors – the store itself lives in the API layer for now,
# but all *service-layer* reads go through these helpers so that the
# import path is contained in one place.
# ---------------------------------------------------------------------------

def get_file_info(file_id: str) -> Optional[dict[str, Any]]:
    """Return the file-store dict for *file_id*, or ``None``."""
    from app.api.files import file_store
    return file_store.get(file_id)


# ---------------------------------------------------------------------------
# Thin async wrappers that delegate to the API-layer implementations.
# Using deferred (inside-function) imports keeps the module importable
# even when the API layer is not fully initialised yet.
# ---------------------------------------------------------------------------

async def parse_file(file_id: str) -> None:
    """Parse an uploaded file (text extraction / scan detection)."""
    from app.api.files import parse_file as _parse
    await _parse(file_id)


async def hybrid_ner(file_id: str, entity_type_ids: list[str]) -> None:
    """Run hybrid NER (HaS model + regex) on an already-parsed file."""
    from app.api.files import HybridNERRequest, hybrid_ner_extract
    await hybrid_ner_extract(file_id, HybridNERRequest(entity_type_ids=entity_type_ids))


async def vision_detect(
    file_id: str,
    page: int,
    ocr_has_types: Optional[list[str]] = None,
    has_image_types: Optional[list[str]] = None,
) -> None:
    """Run dual-pipeline vision detection on a single page."""
    from app.api.redaction import VisionDetectRequest, detect_sensitive_regions
    req = VisionDetectRequest(
        selected_ocr_has_types=ocr_has_types,
        selected_has_image_types=has_image_types,
    )
    await detect_sensitive_regions(file_id, page, req)


async def execute_redaction_request(
    file_id: str,
    entities: list,
    bounding_boxes: list,
    config: Any,
) -> None:
    """Execute redaction via the existing API endpoint logic."""
    from app.api.redaction import execute_redaction
    from app.models.schemas import RedactionRequest
    req = RedactionRequest(
        file_id=file_id,
        entities=entities,
        bounding_boxes=bounding_boxes,
        config=config,
    )
    await execute_redaction(req)
