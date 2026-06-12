---
name: redaction-preview-image
description: Functional skill for generating redaction preview images without committing final output, including selected boxes, page-level preview, base64 preview payloads, and frontend image review contracts. Use when the user asks to preview masks before export.
---

# Preview Image

## Capability

Generate a preview image for manual review before final export.

## Input And Output

- Input: file_id, page, boxes, redaction config.
- Output: preview image base64 or temporary preview image.

## Project Entry Points

- API: `POST /redaction/{file_id}/preview-image`.
- `backend/app/services/redaction_orchestrator.py`: `preview_image`.
- `backend/app/services/vision_service.py`: `preview_redaction`.
- Frontend: `frontend/src/components/ImageBBoxEditor.tsx` and batch/playground review components.

## Rules

- Do not write final output path during preview.
- Use the same mask parameters as final render.
- Preserve page, coordinate, and selected-state traceability.
