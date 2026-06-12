---
name: redaction-structured-export-run
description: Functional skill for applying structured redaction policies to rows and exporting redacted CSV, XLSX, SQLite, SQL, or ZIP outputs. Use when the user asks to run structured anonymization or debug structured delivery output.
---

# Structured Export Run

## Capability

Apply a structured redaction policy row by row and export the redacted dataset.

## Input And Output

- Input: dataset_id, policy, export_format, job_id.
- Output: redacted dataset file, export metadata, download path.

## Project Entry Points

- API: `POST /structured/jobs`, `GET /structured/jobs/{job_id}/export`.
- Service: `backend/app/services/structured_service.py`.
- Key functions: `redact_row`, `redact_value`, `export_dataset`, `run_structured_job_item`, `build_job_export_zip`.

## Rules

- Require reviewed policy before export.
- Use stable salt for hash actions.
- Keep output column order and filenames predictable.
