# Model Deployments

This module owns model-service deployment choices separately from `backend` and `frontend`.
Operators can choose a preset first, then override any task slot by chip type or by pointing
the app to an externally managed custom service.

## Task Slots

| Slot | Built-in choices | Custom contract |
| --- | --- | --- |
| `text_ner` | `has_text_0209_06b` | OpenAI-compatible `/v1/models` and `/v1/chat/completions` |
| `ocr` | `paddle_ocr_service`, `mineru_pipeline_service` | `/health`, `/ocr`, and optional `/structure` |
| `visual_feature` | `visual_features_service`, `has_image_yolo11_glm46v_flash` | `/health`, `/detect`, and OpenAI-compatible `/v1/chat/completions` |

## Presets

| Preset | Text NER | OCR | Visual localization |
| --- | --- | --- | --- |
| `balanced-local` | HaS_Text_0209_0.6B | PaddleOCR-VL 1.6 | LocateAnything-3B-HF |
| `mineru-document` | HaS_Text_0209_0.6B | MinerU Pipeline | LocateAnything-3B-HF |
| `has-image-glm` | HaS_Text_0209_0.6B | PaddleOCR-VL 1.6 | HaS Image YOLO11 + GLM-4.6V-Flash |

## Generate a Compose File

```powershell
.\model-deployments\scripts\render-compose.ps1 `
  -Preset balanced-local `
  -Chip nvidia-cuda `
  -Output .\model-deployments\docker-compose.generated.yml
```

Then start the generated model stack:

```powershell
docker compose -f .\model-deployments\docker-compose.generated.yml up -d
```

The frontend model configuration page should point each task slot to the generated service URLs.

## Chip Profiles

The manifest includes these profiles:

- `nvidia-cuda`: CUDA GPU deployments with Docker device reservations.
- `cpu`: CPU-only or externally accelerated adapters. Heavy VL models are not recommended here.
- `ascend-npu`: reserved for adapter images that expose the same HTTP contracts on Ascend NPUs.
- `custom`: use when models are deployed by another orchestrator and only the endpoint is configured in the app.

Vendor-specific images for MinerU, HaS Image/GLM, Ascend, or other accelerators can be set through
environment variables in `manifest.json` entries or by editing the generated compose file before deployment.
