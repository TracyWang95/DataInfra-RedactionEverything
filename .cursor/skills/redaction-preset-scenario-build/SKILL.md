---
name: redaction-preset-scenario-build
description: Functional skill for building scenario recognition presets by selecting text entity types, OCR-HaS types, visual feature types, replacement mode, data domains, linkage groups, and industry defaults. Use when the user asks to create finance, legal, medical, or custom anonymization presets.
---

# Preset Scenario Build

## Capability

Build recognition presets for business scenarios such as finance, legal, healthcare, contracts, or image privacy.

## Input And Output

- Input: scenario description, text entity types, visual types, replacement mode.
- Output: preset payload ready to save or import.

## Project Entry Points

- Config: `backend/config/preset_entity_types.json`, `backend/config/preset_pipeline_types.json`, `backend/config/industry_presets.json`.
- API: `backend/app/api/presets.py`.
- Service: `backend/app/services/preset_service.py`.
- Frontend: `frontend/src/features/settings/redaction-preset-dialog.tsx`.

## Rules

- Keep text, OCR-HaS, and visual selections separate.
- Keep default selections conservative unless the scenario requires breadth.
- Keep IDs, dataDomains, genericTargets, and linkageGroups aligned.
