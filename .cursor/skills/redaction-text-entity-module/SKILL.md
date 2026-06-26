---
name: redaction-text-entity-module
description: Functional module for sensitive text entity recognition from plain text or OCR text via HaS Text NER and optional user regex. Entity types are supplied per request based on content, not fixed industry presets. Use when the user asks for NER or text entity results without box mapping.
---

# Text Entity Module

## Capability

Recognize sensitive text entities (names, IDs, phones, addresses, amounts, dates, institutions, etc.) from plain text or OCR-assembled text. **Does not map to image coordinates** and **does not pick finance/legal/medical industry presets** — callers pass the entity type list they need for the current content.

## Input And Output

- Input: text string, OCR full text, or text blocks; optional `entity_types[]` chosen for this document; optional user regex rules.
- Output: entity list (type, text, span offsets, confidence), NER timings and warnings.

## Project Entry Points

- HaS Text NER services under `backend/app/services/`.
- `backend/app/services/redaction_orchestrator.py` — entity pipeline wiring.
- API: parse/vision responses include entities when recognition runs.

## Rules

- Caller supplies entity types per document or request (e.g. only PERSON + INSTITUTION_NAME for a judgment).
- Do not require or document industry preset bundles (finance/legal/medical) in this flow.
- No UI; API/service only.
- Stop before box mapping — use `$redaction-entity-box-map` for image coordinates.

## Downstream

- `$redaction-entity-box-map` — image/scanned pages.
- `$redaction-mask-plan-build` — text-only files (TXT) after entities are selected.

## Supersedes

`$redaction-text-ner-result` — use this module instead.
