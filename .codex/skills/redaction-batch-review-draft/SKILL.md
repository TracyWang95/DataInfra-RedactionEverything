---
name: redaction-batch-review-draft
description: Functional skill for loading, saving, approving, rejecting, and committing batch review drafts containing edited text entities and bounding boxes. Use when the user asks to persist review edits or control batch review state.
---

# Batch Review Draft

## Capability

Load, save, approve, reject, and commit manual review drafts for batch items.

## Input And Output

- Input: job_id, item_id, edited entities, edited boxes, review decision.
- Output: review draft, item status, next-review navigation state.

## Project Entry Points

- API: `/jobs/{job_id}/items/{item_id}/review-draft`.
- API actions: `review/approve`, `review/reject`, `review/commit`.
- Service: `backend/app/services/job_store.py`.
- Frontend: `frontend/src/features/batch/hooks/use-batch-review.ts`.

## Rules

- Keep drafts owner-scoped.
- Only committed selected entities and boxes enter final redaction.
- Preserve recoverable states for approve/reject flows.
