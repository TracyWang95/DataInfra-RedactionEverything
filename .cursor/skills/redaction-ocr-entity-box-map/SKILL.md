---
name: redaction-ocr-entity-box-map
description: Functional skill for mapping recognized text entities back to OCR glyph boxes or OCR block boxes on an image or scanned page. Use when the user asks to return coordinates for OCR-recognized sensitive text or convert text entities into maskable image boxes.
---

# OCR Entity Box Map

## Capability

Map recognized text entities back to image coordinates so they can become maskable OCR-derived boxes.

## Input And Output

- Input: `Entity[]`, `OCRTextBlock[]`, page size, OCR adapter metadata.
- Output: `SensitiveRegion[]` or `BoundingBox[]` with page, x, y, width, height, type, text, and source.

## Project Entry Points

- `backend/app/services/vision/ocr_pipeline.py`: `match_entities_to_ocr`, `_entity_char_box_x_span`, `_ensure_block_char_boxes`, `_dedupe_ocr_regions`.
- `backend/app/services/vision_service.py`: `_filter_ocr_has_regions`, `_expand_ocr_region`.

## Rules

- Prefer value-span glyph crops when char boxes exist.
- Fall back to whole block only when needed.
- Avoid masking labels together with values unless the selected region actually covers both.
