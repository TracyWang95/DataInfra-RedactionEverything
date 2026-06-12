---
name: redaction-structured-policy-build
description: Functional skill for building, validating, saving, and previewing structured data redaction policies based on profiled columns. Use when the user asks to choose mask/hash/generalize/drop/keep actions for columns or validate policy schema.
---

# Structured Policy Build

## Capability

Build, validate, save, and preview structured redaction policy from profiled columns.

## Input And Output

- Input: dataset profile and user-selected column actions.
- Output: policy, schema validation result, preview parameters.

## Project Entry Points

- API: `PUT /structured/datasets/{dataset_id}/policy`, `GET /structured/datasets/{dataset_id}/policy`.
- Service: `backend/app/services/structured_service.py`.
- Key functions: `default_policy`, `save_policy`, `validate_policy_columns`, `preview_dataset`.

## Rules

- Policy columns must exactly match the profiled dataset schema.
- Require reviewed policy before export jobs.
- Keep keep/mask/hash/generalize/bucket/drop semantics stable.
