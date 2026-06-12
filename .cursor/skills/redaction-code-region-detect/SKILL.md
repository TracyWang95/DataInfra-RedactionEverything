---
name: redaction-code-region-detect
description: Functional skill for detecting QR code and barcode privacy regions as deterministic local supplements, respecting requested visual categories and deduplicating with model boxes. Use when the user asks to locate QR or barcode regions on an image.
---

# Code Region Detect

## Capability

Detect QR code and barcode regions as deterministic local supplements.

## Input And Output

- Input: image, requested visual types, existing boxes.
- Output: `qr_code` and `barcode` boxes, optionally with decoded text for diagnostics.

## Project Entry Points

- `backend/app/services/vision/machine_code_detector.py`.
- `backend/app/services/vision_service.py`: `_supplement_machine_codes`.

## Rules

- Respect requested categories.
- Deduplicate against model boxes.
- Treat decode failures separately from region detection failures.
