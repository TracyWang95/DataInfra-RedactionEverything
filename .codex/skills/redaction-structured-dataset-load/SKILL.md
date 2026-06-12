---
name: redaction-structured-dataset-load
description: Functional skill for loading structured datasets from CSV, XLSX, JSONL, SQLite, MySQL, or Postgres sources, registering datasets, discovering tables or sheets, and preserving owner-scoped metadata. Use when the user asks to ingest structured data.
---

# Structured Dataset Load

## Capability

Load structured data sources and register datasets. This skill does not build redaction policy.

## Input And Output

- Input: uploaded file or database connection payload.
- Output: source metadata, dataset list, schema/table/sheet metadata, row estimates.

## Project Entry Points

- API: `/structured/files`, `/structured/connections`, `/structured/connections/{id}/datasets`.
- Service: `backend/app/services/structured_service.py`.
- Store: `backend/app/services/structured_store.py`.

## Rules

- Apply `STRUCTURED_DB_HOST_ALLOWLIST` to DB connections.
- Encrypt saved credentials.
- Keep source and dataset metadata owner-scoped.
