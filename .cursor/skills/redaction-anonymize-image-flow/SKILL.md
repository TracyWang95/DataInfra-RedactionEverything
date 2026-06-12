---
name: redaction-anonymize-image-flow
description: Functional skill for running or modifying one-image anonymization from input image through OCR, OCR blocks, text entities, visual regions, merged boxes, mask plan, preview, and final masked output. Use when the user asks for the complete image anonymization pipeline or wants to connect several smaller redaction function skills.
---

# Image Anonymize Flow

## Capability

Run the full image anonymization flow: OCR, OCR block normalization, text NER, entity-to-box mapping, visual region detection, region deduplication, mask planning, preview, and final rendering.

## Input And Output

- Input: image file or file_id/page, optional recognition type config, optional mask style.
- Output: OCR text, OCR blocks, entities, candidate boxes, final mask plan, preview or masked image.

## Project Entry Points

- API: `backend/app/api/files.py` and `backend/app/api/redaction.py`.
- Services: `backend/app/services/vision_service.py`, `backend/app/services/vision/ocr_pipeline.py`, `backend/app/services/redaction_orchestrator.py`.
- Frontend: `frontend/src/features/playground/`, `frontend/src/components/ImageBBoxEditor.tsx`.

## Use Smaller Skills In Order

1. `$redaction-image-ocr-result`
2. `$redaction-ocr-block-normalize`
3. `$redaction-text-ner-result`
4. `$redaction-ocr-entity-box-map`
5. `$redaction-visual-region-locate`
6. `$redaction-region-deduplicate`
7. `$redaction-mask-plan-build`
8. `$redaction-preview-image` or `$redaction-mask-image-render`
