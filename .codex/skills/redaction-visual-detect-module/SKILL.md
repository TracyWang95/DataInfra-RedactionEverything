---
name: redaction-visual-detect-module
description: Functional module for non-text visual privacy detection on images including LocateAnything grounding, red seal supplements, and QR/barcode local detection in one stage. Use when the user asks for visual boxes without splitting locate, seal, and code skills.
---

# Visual Detect Module

## Capability

Detect non-text visual privacy regions in one module: model grounding (faces, signatures, IDs, cards, screens, seals, custom labels), OpenCV red seal/binding seal supplements, and QR/barcode local detection with deduplication against model boxes.

## Input And Output

- Input: image bytes; visual category slugs or custom labels requested for this image (not industry presets).
- Output: `BoundingBox[]` with type, label, confidence, source, page, normalized coordinates.

## Project Entry Points

- `backend/app/services/vision/locate_grounding.py`.
- `backend/app/services/vision_service.py`: `_detect_with_visual_features`.
- Seal supplement: seal detection helpers in vision pipeline.
- Code supplement: QR/barcode detectors in vision pipeline.
- API: `POST /redaction/{file_id}/vision`.

## Internal steps (do not expose as separate skills)

1. LocateAnything / visual feature grounding for requested categories.
2. Red seal and edge/binding seal OpenCV supplement.
3. QR/barcode local detect and merge with model boxes.

## Rules

- Request only the visual categories needed for the current image content.
- Text-in-image boxes come from `$redaction-entity-box-map`, not this module.
- No UI; API/service only.
- Merge with text boxes in `$redaction-region-deduplicate`.

## Downstream

- `$redaction-region-deduplicate` — merge with OCR entity boxes.

## Supersedes

`$redaction-visual-region-locate`, `$redaction-seal-region-detect`, `$redaction-code-region-detect` — use this module instead.
