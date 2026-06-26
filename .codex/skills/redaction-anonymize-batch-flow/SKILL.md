---
name: redaction-anonymize-batch-flow
description: Orchestration for unstructured batch jobs via API — job create, worker run, review draft API, export package. No UI steps or industry presets.
---

# Batch Anonymize Flow

## Module chain

1. `$redaction-model-service-check` (optional)
2. `$redaction-batch-job-create`
3. `$redaction-batch-recognize-run`
4. `$redaction-batch-review-draft` — persist entity/box edits via API only
5. `$redaction-batch-export-package`
6. `$redaction-report-json` (optional)

## Rules

- `text_batch` | `image_batch` | `smart_batch` — workers invoke recognition modules internally.
- No `$redaction-ui-bbox-editor` or preset scenario steps.
