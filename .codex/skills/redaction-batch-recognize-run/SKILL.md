---
name: redaction-batch-recognize-run
description: Functional skill for submitting batch jobs to the async task queue and running recognition or redaction workers over queued items. Use when the user asks to process batch items, debug queue status, handle stuck jobs, or tune recognition scheduling.
---

# Batch Recognize Run

## Capability

Submit batch work and process queued recognition or redaction tasks.

## Input And Output

- Input: job_id, task_type, item status.
- Output: status transitions, progress, recognition results, failure details.

## Project Entry Points

- API: `POST /jobs/{job_id}/submit`, `POST /jobs/{job_id}/cancel`, `GET /jobs/{job_id}/stream`.
- Queue: `backend/app/services/task_queue.py`.
- State: `backend/app/services/job_store.py`.

## Rules

- Do not enqueue duplicate `(task_type, item_id)` work.
- Keep page concurrency conservative under GPU pressure.
- Mark worker errors and continue processing remaining work.
