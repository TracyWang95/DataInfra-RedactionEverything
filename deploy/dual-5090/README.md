# Dual-GPU (2× RTX 5090) deployment scripts

Per-service launch scripts for running the full RedactionEverything stack on a
two-GPU box, with round-robin load balancing across both cards.

## Topology (GPU0 / GPU1)

| Service | Port (g0 / g1) | Notes |
|---|---|---|
| LA vision (MoonViT + mlp1) | 8090 / 8091 | posts prompt-embeds to the LM serve |
| LA LM (vLLM-split, Qwen2) | 8092 / 8093 | shared visual encoding; `--enable-prompt-embeds` |
| HaS NER (vLLM) | 8080 / 8081 | gpu-util 0.15 |
| PaddleOCR-VL (vLLM) | 8118 / 8119 | seal / under-stamp text |
| OCR (PP-StructureV3) | 8082 / 8083 | primary text layout |

Round-robin load balancers (`lb_proxy.py`): OCR `9082`, HaS `9080`, LA `9090`.
Backend (FastAPI) `8000`, frontend (vite preview) `3000`.

## Usage

```bash
bash start_all.sh    # self-healing: launches only the ports that are DOWN
```

Set `JWT_SECRET_KEY` in `backend_g0.sh` before use (a placeholder is shipped).

Scripts assume models under `~/redaction-deploy/backend/models`, vLLM/LA venvs at
`~/rvenv/{vllm,la}`, and OCR/backend in the `dataInfra` conda env.
