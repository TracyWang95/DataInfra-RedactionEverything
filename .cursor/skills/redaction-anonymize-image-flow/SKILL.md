---
name: redaction-anonymize-image-flow
description: Orchestration for single-image anonymization via API and services only — OCR module, text entities, box mapping, visual detect, region merge, mask plan, preview or render. No UI or industry preset steps. Use for complete image redaction pipeline wiring.
---

# Image Anonymize Flow

## Capability

End-to-end image anonymization through backend modules. Recognition types are **per-request** based on document content, not industry preset bundles. No Playground or bbox-editor UI steps.

## Input And Output

- Input: image file or file_id, optional entity_types and visual_categories for this image, mask style.
- Output: normalized OCR, entities, merged boxes, mask plan, preview or masked image, optional report.

## Project Entry Points

- API: `backend/app/api/files.py`, `backend/app/api/redaction.py`.
- Services: `backend/app/services/redaction_orchestrator.py`, `backend/app/services/vision_service.py`.

## Module chain (independent stages)

1. `$redaction-model-service-check` (optional)
2. `$redaction-ocr-module`
3. `$redaction-text-entity-module` — pass `entity_types` for this image
4. `$redaction-entity-box-map`
5. `$redaction-visual-detect-module` — pass visual categories needed for this image
6. `$redaction-region-deduplicate`
7. `$redaction-mask-plan-build`
8. `$redaction-preview-image` or `$redaction-mask-image-render`
9. `$redaction-report-json`, `$redaction-compare-version` (optional)

## Rules

- Do not include `$redaction-preset-scenario-build` or `$redaction-ui-bbox-editor`.
- Each numbered module is independently callable for debugging.
- API upload: see `$redaction-api-demo-call` if endpoint sequence is needed.
