---
name: redaction-mask-pdf-render
description: Functional skill for rendering redaction masks on PDFs, including text PDFs, scanned PDFs, page image rendering, visual region masks, text replacements, output path updates, and PDF comparison support. Use when the user asks to redact or mask a PDF.
---

# PDF Mask Render

## Capability

Redact PDFs using text replacement for text-layer PDFs and page/image masks for scanned pages or visual regions.

## Input And Output

- Input: PDF file_id or path, entities, boxes, replacement config.
- Output: redacted PDF, version metadata, compare-ready output.

## Project Entry Points

- `backend/app/services/redactor.py`.
- `backend/app/services/redaction/text_redactor.py`: `_redact_pdf_text`.
- `backend/app/services/vision_service.py`: `_redact_pdf`.
- `backend/app/services/file_parser.py`.

## Rules

- Distinguish text PDFs from scanned PDFs.
- Keep page coordinates consistent with render scale.
- Write output path and versions back to file store.
