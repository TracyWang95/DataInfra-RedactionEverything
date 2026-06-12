---
name: redaction-batch-export-package
description: Functional skill for packaging batch redaction outputs, selected files, reports, skipped entries, and download metadata into a ZIP or export response. Use when the user asks to download batch results or debug missing files in a package.
---

# Batch Export Package

## Capability

Package batch job outputs and export reports into a downloadable result.

## Input And Output

- Input: job_id, selected scope, include original/redacted/report options.
- Output: ZIP bytes or path, filename, export report, skipped list.

## Project Entry Points

- `backend/app/services/file_management_service.py`: `build_batch_zip`.
- `backend/app/api/files.py`: `/files/batch/download`.
- `backend/app/api/jobs.py`: `/jobs/{job_id}/export-report`.
- Frontend: `frontend/src/features/batch/components/batch-step5-export.tsx`.

## Rules

- Explain every skipped item.
- Keep filenames stable when collisions occur.
- Package only current-user accessible files.
