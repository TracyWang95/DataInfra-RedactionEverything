---
name: redaction-api-demo-call
description: Functional skill for explaining or composing concrete RedactionEverything API call sequences for one capability such as upload image, OCR parse, NER, visual detection, preview mask, execute redaction, batch submit, or structured export. Use when the user asks how to call a function point.
---

# API Demo Call

## Capability

Compose concrete API call sequences for one function point.

## Input And Output

- Input: requested capability, auth constraints, file or payload.
- Output: curl/fetch/axios sequence, endpoint order, key response fields.

## Common Flows

- Image recognition: `POST /files/upload` -> `GET /files/{file_id}/parse` -> `POST /redaction/{file_id}/vision`.
- Preview mask: `POST /redaction/{file_id}/preview-image`.
- Execute redaction: `POST /redaction/execute` -> `GET /files/{file_id}/download?redacted=true`.
- Batch: `POST /jobs` -> `POST /jobs/{job_id}/items` -> `POST /jobs/{job_id}/submit`.
- Structured: upload -> profile -> policy -> job -> export.

## Rules

- API prefix is usually `/api/v1`.
- Browser calls must preserve auth and CSRF behavior through the existing client.
- Do not put real tokens or sensitive files into examples.
