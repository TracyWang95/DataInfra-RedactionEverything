---
name: redaction-mask-docx-render
description: Functional skill for redacting DOCX or converted DOC files by replacing sensitive text while preserving paragraph structure, run formatting, tables, headers, footers, and document XML parts where supported. Use when the user asks to anonymize a Word document.
---

# DOCX Mask Render

## Capability

Redact Word documents by replacing sensitive text while preserving as much document structure and formatting as possible.

## Input And Output

- Input: DOCX or converted DOC path, entities, replacement strategy.
- Output: redacted DOCX, replacement count, version metadata.

## Project Entry Points

- `backend/app/services/redaction/text_redactor.py`.
- Key functions: `_redact_docx`, `_replace_in_docx_xml_parts`, `_replace_in_paragraph`.
- `backend/app/services/redactor.py`: `_convert_doc_to_docx`.

## Rules

- Handle text that crosses DOCX runs.
- Avoid corrupting XML parts.
- Keep font tracing disabled unless debugging.
