# Redaction Skill Pipeline Phases

Stage **modules** — independent, not over-split. No UI skills in flows. No industry preset bundles in flows.

| Phase | ID | Module Skill | Notes |
|-------|-----|--------------|-------|
| 0 | `infra` | `redaction-model-service-check`, `redaction-api-demo-call`, `redaction-skill-generate` | Health, API examples |
| 1 | `ocr` | `redaction-ocr-module` | Normalized OCR output only |
| 2 | `text-entity` | `redaction-text-entity-module` | Per-request entity types |
| 3 | `entity-box` | `redaction-entity-box-map` | Text entities → image boxes |
| 4 | `visual` | `redaction-visual-detect-module` | Grounding + seal + code |
| 5 | `region-merge` | `redaction-region-deduplicate` | Merge all candidate boxes |
| 6 | `mask-plan` | `redaction-mask-plan-build` | Plan without render |
| 7 | `render` | `redaction-preview-image`, `redaction-mask-image-render`, `redaction-mask-pdf-render`, `redaction-mask-docx-render`, `redaction-mask-text-render` | By file format |
| 8 | `audit` | `redaction-compare-version`, `redaction-report-json` | Compare and report |
| 9 | `batch` | `redaction-batch-job-create`, `redaction-batch-recognize-run`, `redaction-batch-review-draft`, `redaction-batch-export-package` | API only |
| 10 | `structured` | `redaction-structured-dataset-load`, `redaction-structured-profile-columns`, `redaction-structured-policy-build`, `redaction-structured-export-run` | Tabular pipeline |
| E | `orchestration` | `redaction-anonymize-image-flow`, `redaction-anonymize-text-flow`, `redaction-anonymize-docx-flow`, `redaction-anonymize-pdf-flow`, `redaction-anonymize-batch-flow`, `redaction-anonymize-structured-flow` | End-to-end |

## Deprecated as flow steps (use module above)

- `redaction-image-ocr-result`, `redaction-ocr-block-normalize`, `redaction-ocr-table-form-recall` → `redaction-ocr-module`
- `redaction-text-ner-result` → `redaction-text-entity-module`
- `redaction-visual-region-locate`, `redaction-seal-region-detect`, `redaction-code-region-detect` → `redaction-visual-detect-module`
- `redaction-preset-scenario-build` — not in standard anonymization flows
- `redaction-ui-bbox-editor` — not in standard anonymization flows

## Image module chain

`$redaction-ocr-module` → `$redaction-text-entity-module` → `$redaction-entity-box-map` → `$redaction-visual-detect-module` → `$redaction-region-deduplicate` → `$redaction-mask-plan-build` → preview/render

See [workflows.md](workflows.md).
