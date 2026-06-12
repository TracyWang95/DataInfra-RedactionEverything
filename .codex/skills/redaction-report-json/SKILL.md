---
name: redaction-report-json
description: Functional skill for producing redaction report JSON, including entity counts, selected item counts, visual evidence, page-level box statistics, replacement summaries, batch export summaries, and audit-friendly metadata. Use when the user asks for a report after recognition or redaction.
---

# Report JSON

## Capability

Produce redaction report JSON for display, audit, and batch export summaries.

## Input And Output

- Input: file_id or job_id.
- Output: entity stats, box stats, selected counts, output metadata, skipped items, quality details.

## Project Entry Points

- Single file: `backend/app/services/redaction_orchestrator.py`: `get_report`.
- API: `GET /redaction/{file_id}/report`.
- Batch: `backend/app/api/jobs.py`: `/jobs/{job_id}/export-report`.
- Schemas: `backend/app/models/job_schemas.py`, `backend/app/models/redaction_schemas.py`.

## Rules

- Distinguish recognized items from selected redacted items.
- Keep frontend export report display in sync.
- Do not expose other users' paths or data.
