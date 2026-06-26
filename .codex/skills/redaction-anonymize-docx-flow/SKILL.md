---
name: redaction-anonymize-docx-flow
description: Orchestration for DOCX anonymization via API and services — text entities, mask plan, DOCX render. No UI or industry presets.
---

# DOCX Anonymize Flow

## Module chain

1. `$redaction-model-service-check` (optional)
2. `$redaction-text-entity-module`
3. `$redaction-mask-plan-build`
4. `$redaction-mask-docx-render`
5. `$redaction-report-json`, `$redaction-compare-version` (optional)
