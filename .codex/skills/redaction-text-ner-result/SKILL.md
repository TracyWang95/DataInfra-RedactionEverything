---
name: redaction-text-ner-result
description: Functional skill for taking plain text or OCR text and returning sensitive text entities through HaS Text semantic NER plus optional user regex fallback. Use when the user asks for entity recognition results such as names, IDs, accounts, dates, amounts, addresses, legal, finance, or medical tags.
---

# Text NER Result

## Capability

Return sensitive text entities from plain text or OCR text. This skill does not map entities to image boxes.

## Input And Output

- Input: text, enabled entity types, optional regex fallback types.
- Output: `Entity[]` with text, type, start, end, confidence, source, tag, and coref metadata.

## Project Entry Points

- `backend/app/services/hybrid_ner_service.py`.
- `backend/app/services/has_service.py`.
- `backend/app/services/has_client.py`.
- `backend/config/preset_entity_types.json`.

## Rules

- Use HaS Text as the semantic recognition path.
- Use regex only as user-defined fallback.
- Keep entity concepts atomic and exact-tagged.
