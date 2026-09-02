# Dual-GPU (GPU 6 / GPU 7) deployment

Launch scripts for the RedactionEverything inference stack pinned to physical
GPU 6 and GPU 7, with round-robin load balancers in front of paired workers.

## Topology

| Service | GPU 6 / GPU 7 worker ports | Load balancer | Purpose |
|---|---:|---:|---|
| HaS Text (vLLM) | 28080 / 28081 | 29080 | semantic PHI detection |
| OCR (PP-StructureV3) | 28082, 28084 / 28083, 28085 | 29082 | text and character boxes |
| LocateAnything vision | 28090 / 28091 | 29090 | visual-region detection |
| LocateAnything LM | 28092 / 28093 | internal | visual-language decoding |
| PaddleOCR-VL | 28118 / 28119 | internal | supplemental OCR |
| visual detector | 28140 / 28141 | 29140 | visual feature detection |

The API listens on `23001` and the development frontend on `3000`.
`backend_g0.sh` sets `VISIBLE_GPU_INDICES=6,7`, so health telemetry and the UI
show only the two cards owned by this deployment.

## Usage

```bash
bash sync_to_live.sh
```

The launcher is self-healing: it starts missing workers, waits for their health
ports, starts the load balancers, and then starts the API. Secrets are loaded
from `~/.redaction_secrets`; the launcher fails closed when that file is absent.

Scripts use the repository at
`/data/ubuntu/lh/projects/DataInfra-RedactionEverything`, model assets below its
`backend/models` directory, and the `dataInfra`/`dataInfra-ocr` conda runtimes.
