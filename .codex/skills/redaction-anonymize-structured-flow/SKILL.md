---
name: redaction-anonymize-structured-flow
description: Orchestration for structured data anonymization via API — dataset load, column profile, policy, export. No UI steps.
---

# Structured Anonymize Flow

## Module chain

1. `$redaction-model-service-check` (optional)
2. `$redaction-structured-dataset-load`
3. `$redaction-structured-profile-columns`
4. `$redaction-structured-policy-build`
5. `$redaction-structured-export-run`

## Rules

- Column actions chosen per dataset content, not industry preset bundles.
- API only under `/structured/*`.
