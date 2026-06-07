# DataInfra-RedactionEverything

Local-first document redaction system for mixed files, scans, images, and PDFs.

The current runtime is built around one converged vision pipeline:

- PaddleOCR-VL 1.6 extracts image text and document elements.
- PP-StructureV3 strengthens layouts, tables, and structured scan regions.
- HaS Text performs semantic entity recognition over OCR text.
- LocateAnything-3B handles visual features, including the 22 fixed presets and user-defined visual labels.

The old split visual-region/checklist model path has been removed. Visual privacy targets are now configured and displayed as a single "visual features" capability.

## Capabilities

| Area | Runtime |
| --- | --- |
| Text in documents and scans | PaddleOCR-VL 1.6 + PP-StructureV3 |
| Semantic text entities | HaS Text |
| Tables and structured layouts | PP-StructureV3 |
| Fixed visual features | LocateAnything-3B |
| User-defined visual labels | LocateAnything-3B checklist grounding |
| Seal recognition | PaddleOCR-VL first, LocateAnything as supplementary visual evidence |

## Visual Feature Presets

The built-in visual feature set contains 22 fixed classes:

`face`, `fingerprint`, `palmprint`, `id_card`, `hk_macau_permit`, `passport`, `employee_badge`, `license_plate`, `bank_card`, `physical_key`, `receipt`, `shipping_label`, `official_seal`, `whiteboard`, `sticky_note`, `mobile_screen`, `monitor_screen`, `medical_wristband`, `qr_code`, `barcode`, `paper`, `signature`.

Users can add custom visual feature labels from the recognition settings UI. Custom labels are stored under the visual feature pipeline and are prompted through the same LocateAnything service.

## Local Development

Install dependencies, then run:

```bash
npm run dev
```

The dev entry starts services in this order:

1. PaddleOCR-VL 1.6 vLLM endpoint on `8118`
2. HaS Text vLLM endpoint on `8080`
3. PaddleOCR/PP-Structure wrapper on `8082`
4. LocateAnything visual feature service on `8090`
5. Backend API on `8000`
6. Frontend on `3000`

Model warmup covers PaddleOCR-VL, PP-StructureV3, HaS Text, and LocateAnything before the UI is considered ready.

Stop the local stack with:

```bash
npm run stop
```

## Required Service URLs

```env
OCR_BASE_URL=http://127.0.0.1:8082
HAS_LLAMACPP_BASE_URL=http://127.0.0.1:8080/v1
VISUAL_FEATURES_BASE_URL=http://127.0.0.1:8090
LOCATE_ANYTHING_MAX_NEW_TOKENS=8192
```

## Docker

CPU API/frontend only:

```bash
docker compose up -d
```

Full GPU model stack:

```bash
docker compose --profile gpu up -d
```

The GPU profile starts `ocr`, `ner`, and `visual-features`. The visual feature service is LocateAnything on port `8090`.

## Architecture

```text
Frontend
  |
Backend API
  |
  +-- OCR/layout pipeline: PaddleOCR-VL 1.6 + PP-StructureV3
  |       |
  |       +-- HaS Text semantic recognition
  |
  +-- Visual feature pipeline: LocateAnything-3B
          |
          +-- fixed 22 presets
          +-- user-defined visual labels
```

## Verification

```bash
python -m py_compile backend/app/core/config.py backend/app/main.py backend/scripts/ocr_server.py backend/scripts/locate_anything_server.py
npm --prefix frontend run build
```

Runtime health:

```bash
curl http://127.0.0.1:8000/health/services
```

Expected model services are `paddle_ocr`, `has_ner`, and `visual_features`.
