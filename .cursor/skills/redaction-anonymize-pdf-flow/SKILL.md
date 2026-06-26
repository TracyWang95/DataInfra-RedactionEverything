---
name: redaction-anonymize-pdf-flow
description: Orchestration for PDF anonymization via API and services — text-layer or scanned-page modules, PDF render, report. No UI or industry presets.
---

# PDF Anonymize Flow

## Module chain

1. `$redaction-model-service-check` (optional)
2. **Text-layer PDF:** `$redaction-text-entity-module` → `$redaction-mask-plan-build`
3. **Scanned pages:** `$redaction-ocr-module` → `$redaction-text-entity-module` → `$redaction-entity-box-map` → `$redaction-visual-detect-module` → `$redaction-region-deduplicate` → `$redaction-mask-plan-build`
4. `$redaction-mask-pdf-render`
5. `$redaction-report-json`, `$redaction-compare-version` (optional)

## Rules

- Branch on text PDF vs scanned per page; no UI steps.
