> **Flow note:** Prefer the stage module listed in workflows.md. This fine-grained skill is for code navigation only.

---
name: redaction-image-ocr-result
description: Functional skill for taking an image or scanned page and returning OCR recognition results such as raw text, OCR service payloads, text blocks, line text, page size, timings, cache status, and OCR warnings. Use when the user asks to OCR an image or inspect OCR output before anonymization.
---

# Image OCR Result

## Capability

Return OCR recognition output for one image or scanned page. This skill stops at OCR and does not perform NER, visual detection, or masking.

## Input And Output

- Input: image bytes, file_id plus page, or a renderable page.
- Output: raw OCR text, OCR items, OCR text blocks, page size, timings, warnings, and cache status.

## Project Entry Points

- `backend/app/services/vision/ocr_pipeline.py`: `run_paddle_ocr`, `_run_ocr_service`, `prepare_image`.
- `backend/app/services/ocr_service.py`.
- `backend/app/core/health_checks.py`.

## Rules

- Distinguish Paddle/PP-Structure, MinerU, and optional PaddleOCR-VL supplement paths.
- Return service status and timeout clues when OCR fails.
- Do not generate masks in this skill.
