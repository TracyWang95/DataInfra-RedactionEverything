---
name: redaction-batch-job-create
description: Functional skill for creating a batch redaction job, selecting batch mode, validating file types, adding uploaded file items, and preparing server-side job records before recognition starts. Use when the user asks to create or inspect batch jobs.
---

# Batch Job Create

## Capability

Create a batch job and attach file items before recognition starts.

## Input And Output

- Input: job_type, preset/config, file_ids, owner.
- Output: job_id, item_ids, initial status, progress summary.

## Project Entry Points

- API: `POST /jobs`, `POST /jobs/{job_id}/items`.
- Services: `backend/app/services/job_store.py`, `backend/app/services/job_management_service.py`.
- Validation: `backend/app/services/batch_mode_validation.py`.
- Frontend: `frontend/src/features/batch/hooks/use-batch-wizard.ts`, `use-batch-files.ts`.

## Rules

- Validate file types against batch mode.
- Keep job and item records owner-scoped.
- Only submit should enqueue background work.
