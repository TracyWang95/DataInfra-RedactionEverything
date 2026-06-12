---
name: redaction-mask-image-render
description: Functional skill for applying a mask plan to images using fill, blur, mosaic, or configured visual effects. Use when the user asks to generate a masked image from bounding boxes or render anonymization regions onto a PNG or JPG.
---

# Image Mask Render

## Capability

Render selected mask regions onto an image and output a redacted PNG/JPG or preview image.

## Input And Output

- Input: image, boxes, effect mode, strength, fill color.
- Output: masked image file or base64 preview.

## Project Entry Points

- `backend/app/services/vision_service.py`: `_apply_region_effect`, `_apply_box_effect`, `_redact_image`, `preview_redaction`.
- `backend/app/services/redaction/image_redactor.py`.

## Rules

- Clip boxes to page bounds.
- Preserve region source metadata.
- Keep effect parameters aligned with frontend config.
