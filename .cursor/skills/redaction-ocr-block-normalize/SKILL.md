---
name: redaction-ocr-block-normalize
description: Functional skill for converting raw OCR items into normalized OCR text blocks with bounding boxes, char boxes, page dimensions, visual line reconstruction, table block expansion, merged OCR blocks, and cache-safe output. Use when the user asks for OCR block results or page text segmentation.
---

# OCR Block Normalize

## Capability

Convert raw OCR service output into normalized text blocks that later stages can match back to image coordinates.

## Input And Output

- Input: OCR items, image dimensions, optional table HTML, optional VL supplement blocks.
- Output: normalized `OCRTextBlock[]`, optionally with char boxes, table cell blocks, and merged blocks.

## Project Entry Points

- `backend/app/services/vision/ocr_pipeline.py`.
- Key functions: `_ocr_items_to_blocks`, `reconstruct_visual_line_blocks`, `_merge_ocr_blocks`, `extract_table_cells`, `expand_table_blocks`.

## Rules

- Preserve real char boxes when available.
- Synthesize char boxes only as fallback.
- Keep source and quality metadata useful for later debugging.
