---
name: redaction-visual-region-locate
description: Functional skill for locating non-text visual privacy regions with LocateAnything or compatible visual services, including faces, signatures, seals, cards, screens, license plates, documents, and user custom labels. Use when the user asks for visual detection boxes from an image.
---

# Visual Region Locate

## Capability

Locate non-text visual privacy regions such as faces, signatures, IDs, bank cards, screens, license plates, paper, seals, and custom visual labels.

## Input And Output

- Input: image bytes and selected visual types or custom labels.
- Output: `BoundingBox[]` with type, label, confidence, source, page, and normalized coordinates.

## Project Entry Points

- `backend/app/services/vision/locate_grounding.py`.
- `backend/app/services/vision_service.py`: `_detect_with_visual_features`.
- `backend/app/core/visual_feature_categories.py`.
- API: `POST /redaction/{file_id}/vision`.

## Rules

- Keep fixed visual slugs stable.
- Keep custom labels on the same checklist/chat contract.
- Use OCR-derived text boxes through `$redaction-ocr-entity-box-map`, not this skill.
