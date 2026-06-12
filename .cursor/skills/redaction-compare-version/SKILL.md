---
name: redaction-compare-version
description: Functional skill for comparing original and redacted outputs and reading redaction version metadata. Use when the user asks for before/after comparison, redaction history, versions, or why a download points to a given output.
---

# Compare Version

## Capability

Read original/redacted comparison data and redaction version metadata.

## Input And Output

- Input: file_id.
- Output: compare data, version list, original and redacted references.

## Project Entry Points

- API: `GET /redaction/{file_id}/compare`, `GET /redaction/{file_id}/versions`.
- `backend/app/services/redaction_orchestrator.py`: `get_comparison`, `get_versions`.
- `backend/app/services/redactor.py`: `get_comparison`.

## Rules

- Enforce owner-scoped access.
- Do not trigger a new redaction while comparing.
- Keep version metadata consistent with file store output fields.
