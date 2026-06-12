---
name: redaction-mask-text-render
description: Functional skill for redacting plain text files or text strings using selected entities and replacement strategies. Use when the user asks to anonymize text, return replacement maps, or verify text-only masking output.
---

# Text Mask Render

## Capability

Redact plain text by replacing selected entity spans with deterministic replacement values.

## Input And Output

- Input: text or TXT file, entities, replacement config.
- Output: redacted text, entity map, replacement stats.

## Project Entry Points

- `backend/app/services/redaction/text_redactor.py`: `_redact_txt`.
- `backend/app/services/redactor.py`.
- `backend/app/services/redaction/replacement_strategy.py`.

## Rules

- Apply span replacements without corrupting later offsets.
- Respect selected entities.
- Keep structured placeholders deterministic.
