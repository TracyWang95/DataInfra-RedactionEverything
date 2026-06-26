---
name: redaction-ocr-module
description: Functional module for image or scanned-page OCR that returns normalized text blocks with bounding boxes, char boxes, table cells, timings, and warnings in one step. Use when the user asks for OCR on an image without splitting raw OCR and block normalization.
---

# OCR Module

## Capability

Single OCR stage: call OCR service, normalize items into `OCRTextBlock[]`, optionally expand tables and recall form/table values. **Output is always normalized** — do not split into separate raw-OCR and normalize skills.

## Input And Output

- Input: image bytes, file_id + page, or renderable page image.
- Output: normalized blocks (text, bbox, char boxes), page size, full text, timings, warnings, cache status, optional table/form recall metadata.

## Project Entry Points

- `backend/app/services/vision/ocr_pipeline.py`: `run_paddle_ocr`, `_ocr_items_to_blocks`, `reconstruct_visual_line_blocks`, `extract_table_cells`, `expand_table_blocks`.
- `backend/app/services/ocr_service.py`.
- API path: upload file then parse/vision pipeline consumes this module internally.

## Internal steps (do not expose as separate skills)

1. OCR service call (Paddle / MinerU / optional VL supplement).
2. Item → block normalization and line reconstruction.
3. Optional table cell expansion and table/form value recall.

## Rules

- Return normalized blocks only; downstream modules consume blocks, not raw items.
- Distinguish service offline vs blank page vs timeout in status fields.
- No UI steps; API/service invocation only.
- No industry preset selection — entity types are chosen in `$redaction-text-entity-module`.

## Downstream

- `$redaction-text-entity-module` — text from blocks.
- `$redaction-entity-box-map` — entities + blocks → mask boxes.

## Supersedes (deprecated as standalone flow steps)

`$redaction-image-ocr-result`, `$redaction-ocr-block-normalize`, `$redaction-ocr-table-form-recall` — use this module instead.
