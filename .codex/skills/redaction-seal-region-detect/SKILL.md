---
name: redaction-seal-region-detect
description: Functional skill for detecting red seal regions that supplement model-based visual detection, including binding seals, edge seals, merged seal splitting, red-ink masks, and deduplication against existing official_seal boxes. Use when the user asks to find or improve seal masks.
---

# Seal Region Detect

## Capability

Supplement visual detection with local red seal detection for binding seals, edge seals, and model-missed official seals.

## Input And Output

- Input: PIL image, page size, optional existing visual boxes.
- Output: seal regions or `official_seal` boxes.

## Project Entry Points

- `backend/app/services/vision/seal_detector.py`.
- `backend/app/services/vision_service.py`: `_supplement_seals`.
- `backend/app/services/vision/ocr_pipeline.py`: `_split_merged_seal_region`.

## Rules

- Deduplicate against existing LocateAnything seal boxes.
- Do not expand small seal regions into whole-page edge masks.
- Keep visible red ink as the main signal.
