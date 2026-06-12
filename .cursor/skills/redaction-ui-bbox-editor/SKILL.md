---
name: redaction-ui-bbox-editor
description: Functional skill for editing the frontend bounding-box review UI, including image viewport, box drawing, resizing, selection, annotation popovers, text-image review sync, and manual mask edits. Use when the user asks to improve manual review of detected boxes.
---

# UI BBox Editor

## Capability

Maintain the frontend manual box review and edit experience for image and scanned-document anonymization.

## Input And Output

- Input: box list, image dimensions, viewport state, selection state.
- Output: edited boxes, selected flags, annotation or review draft state.

## Project Entry Points

- `frontend/src/components/ImageBBoxEditor.tsx`.
- `frontend/src/components/bbox-utils.ts`.
- `frontend/src/components/hooks/useBBoxInteraction.ts`.
- `frontend/src/components/hooks/useImageViewport.ts`.
- `frontend/src/features/batch/components/review-image-content.tsx`.

## Rules

- Keep coordinate conversion stable under zoom and pan.
- Keep text entities and visual boxes independently selectable.
- Support both playground and batch review flows.
