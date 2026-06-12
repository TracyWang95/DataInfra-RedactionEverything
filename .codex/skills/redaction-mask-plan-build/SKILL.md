---
name: redaction-mask-plan-build
description: Functional skill for turning selected text entities, visual boxes, replacement modes, mask effects, page mappings, and review state into a deterministic redaction mask plan. Use when the user asks to generate masks but not yet render them.
---

# Mask Plan Build

## Capability

Build the plan for what to redact, how to redact it, and what replacement text or visual effect to use. This skill does not render files.

## Input And Output

- Input: entities, bounding boxes, selected flags, replacement config, page mapping.
- Output: mask plan with replacement map and page-level region list.

## Project Entry Points

- `backend/app/services/redaction_orchestrator.py`.
- `backend/app/services/redactor.py`.
- `backend/app/services/redaction/image_redactor.py`: `prepare_image_redaction`.
- `backend/app/services/redaction/replacement_strategy.py`.

## Rules

- Respect `selected` flags.
- Keep text replacement and visual masking separate.
- Make the output usable by preview, execute, and report flows.
