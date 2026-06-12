---
name: redaction-model-service-check
description: Functional skill for checking OCR, HaS Text, visual feature, GPU memory, runtime mode, active model slot, and service health before recognition or anonymization. Use when the user asks why OCR, NER, or visual detection is offline, slow, or falling back to CPU.
---

# Model Service Check

## Capability

Check model service readiness before recognition or anonymization.

## Input And Output

- Input: active slot, service URL, environment config.
- Output: online/offline/degraded, runtime_mode, CPU fallback risk, GPU memory, slot details.

## Project Entry Points

- API: `GET /health/services`.
- Service: `backend/app/core/health_checks.py`.
- Config: `backend/app/services/model_config_service.py`.
- Frontend: `frontend/src/hooks/use-service-health.ts`, `frontend/src/components/Layout/app-sidebar.tsx`.

## Rules

- Surface CPU fallback risk.
- Distinguish Paddle and MinerU OCR slots.
- Use existing WSL localhost resolver logic.
