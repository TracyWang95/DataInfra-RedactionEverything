---
name: redaction-ocr-table-form-recall
description: Functional skill for recovering sensitive values from OCR tables and form fields, including amount column recall, document number recall, label-value splitting, table cell placement, and matching recalled values back to OCR blocks. Use when the user asks for table/form extraction before masking.
---

# OCR Table Form Recall

## Capability

Recover sensitive values from OCR blocks that plain NER may miss, especially table amounts and form field document numbers.

## Input And Output

- Input: `OCRTextBlock[]` and optionally selected entity types.
- Output: recalled entity candidates with text, type, source, and block-match information.

## Project Entry Points

- `backend/app/services/vision/ocr_pipeline.py`.
- Key functions: `recall_table_amount_entities`, `recall_form_field_document_numbers`, `_merge_table_amount_entities`, `_merge_form_field_document_entities`.

## Rules

- Gate recall by selected schema/type.
- Do not recall empty fields.
- Prefer layout-aware table and field rules over substring-only checks.
