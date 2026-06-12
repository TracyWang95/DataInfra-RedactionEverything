---
name: redaction-structured-profile-columns
description: Functional skill for profiling structured dataset columns, inferring runtime type, shape, uniqueness, deterministic sensitive categories, optional HaS semantic classification, risk level, and recommended default action. Use when the user asks to analyze columns before policy review.
---

# Structured Profile Columns

## Capability

Profile structured dataset columns and infer likely sensitive semantics and default redaction actions.

## Input And Output

- Input: dataset_id and sampled rows.
- Output: column profile, entity_type, risk_level, unique_rate, recommended_action.

## Project Entry Points

- API: `POST /structured/datasets/{dataset_id}/profile`.
- Service: `backend/app/services/structured_service.py`.
- Key functions: `profile_dataset`, `profile_column`, `infer_column_semantics_with_has`, `choose_classification`.

## Rules

- Use deterministic name/value classification first.
- Use HaS only for ambiguous semantic columns.
- Avoid treating technical IDs as personal identifiers.
