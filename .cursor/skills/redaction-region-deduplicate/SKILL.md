---
name: redaction-region-deduplicate
description: Functional skill for merging candidate redaction regions from OCR text boxes, LocateAnything visual boxes, seal detection, QR/barcode detection, and manual boxes. Use when the user asks to combine boxes, remove duplicates, resolve overlaps, or produce final maskable regions.
---

# Region Deduplicate

## Capability

Merge OCR text boxes, visual boxes, seal boxes, QR/barcode boxes, and manual boxes into final candidate mask regions.

## Input And Output

- Input: candidate boxes from multiple sources.
- Output: deduplicated boxes preserving type, source, text, and quality metadata.

## Project Entry Points

- `backend/app/services/vision_service.py`: `_deduplicate_boxes`.
- `backend/app/services/vision/region_merger.py`.
- `backend/app/services/vision/ocr_pipeline.py`: `_dedupe_ocr_regions`.

## Rules

- Use IoU, containment, source semantics, and value signatures.
- Prefer tight value boxes over whole-block boxes when both represent the same text.
- Keep overlapping boxes when they represent different sensitive values.
