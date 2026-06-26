---
name: redaction-anonymize-text-flow
description: Orchestration for plain-text anonymization via API and services — text entities, mask plan, text render, report. No UI or industry presets. Use for TXT end-to-end redaction.
---

# Text Anonymize Flow

## Module chain

1. `$redaction-model-service-check` (optional)
2. `$redaction-text-entity-module` — entity types per document content
3. `$redaction-mask-plan-build`
4. `$redaction-mask-text-render`
5. `$redaction-report-json`, `$redaction-compare-version` (optional)

## Rules

- No OCR or visual modules for pure TXT.
- No UI steps; API `upload` → `parse` → `execute` via `$redaction-api-demo-call` when needed.
