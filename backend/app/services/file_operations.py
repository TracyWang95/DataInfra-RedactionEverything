"""
Service-layer wrappers for file operations.

Decouples job_runner (and other service-layer callers) from direct
API-layer imports.  The functions here delegate to the service layer
(file_management_service / redaction_orchestrator).
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# file_store accessors – the store lives in the service layer.
# ---------------------------------------------------------------------------

def get_file_info(file_id: str) -> dict[str, Any] | None:
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


async def hybrid_ner(
    file_id: str,
    entity_type_ids: list[str],
    owner_id: str | None = None,
) -> None:
    """Run hybrid NER (HaS model + regex) on an already-parsed file."""
    from app.services.file_management_service import run_hybrid_ner
    if owner_id is None:
        info = get_file_info(file_id) or {}
        owner_id = str(info.get("owner_id") or "local_user")
    await run_hybrid_ner(file_id, entity_type_ids=entity_type_ids, owner_id=owner_id)


async def vision_detect(
    file_id: str,
    page: int,
    ocr_has_types: list[str] | None = None,
    has_image_types: list[str] | None = None,
    vlm_types: list[str] | None = None,
    include_result_image: bool = False,
    merge_existing: bool = False,
    signature_ocr_has_types: list[str] | None = None,
    signature_has_image_types: list[str] | None = None,
    signature_vlm_types: list[str] | None = None,
    owner_id: str | None = None,
) -> Any:
    """Run dual-pipeline vision detection on a single page."""
    from app.services.redaction_orchestrator import detect_vision
    if owner_id is None:
        info = get_file_info(file_id) or {}
        owner_id = str(info.get("owner_id") or "local_user")
    return await detect_vision(
        file_id=file_id,
        page=page,
        selected_ocr_has_types=ocr_has_types,
        selected_has_image_types=has_image_types,
        selected_vlm_types=vlm_types,
        has_request=True,
        include_result_image=include_result_image,
        merge_existing=merge_existing,
        owner_id=owner_id,
        signature_selected_ocr_has_types=signature_ocr_has_types,
        signature_selected_has_image_types=signature_has_image_types,
        signature_selected_vlm_types=signature_vlm_types,
    )


async def execute_redaction_request(
    file_id: str,
    entities: list,
    bounding_boxes: list,
    config: Any,
) -> None:
    """Execute redaction via the service layer."""
    from app.models.schemas import RedactionRequest
    from app.services.redaction_orchestrator import execute_redaction
    req = RedactionRequest(
        file_id=file_id,
        entities=entities,
        bounding_boxes=bounding_boxes,
        config=config,
    )
    await execute_redaction(req)
