<div align="center">

# DataInfra &middot; RedactionEverything

**Local-first unstructured data redaction for documents, scanned PDFs, images, Word files, and plain text**

RedactionEverything is a local-first redaction workbench for sensitive information in real-world files. It combines semantic NER, OCR, visual feature grounding, configurable industry schemas, human review, batch processing, and export workflows so sensitive content can be found, reviewed, and anonymized without sending raw documents to a remote API.

[![License](https://img.shields.io/badge/license-Personal%20Use-blue.svg)](./LICENSE)
[![CI](https://github.com/TracyWang95/DataInfra-RedactionEverything/actions/workflows/ci.yml/badge.svg)](https://github.com/TracyWang95/DataInfra-RedactionEverything/actions/workflows/ci.yml)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#contributing)
[![GitHub Stars](https://img.shields.io/github/stars/TracyWang95/DataInfra-RedactionEverything.svg?style=flat&logo=github&label=Stars&cacheSeconds=3600)](https://github.com/TracyWang95/DataInfra-RedactionEverything/stargazers)

**Language:** English | [中文](./README_zh.md)

> This project uses a custom [Personal Use License](./LICENSE). Individuals may use it for free personal, non-commercial purposes. Paid work, consulting delivery, companies, institutions, government agencies, teams, hosted services, production deployments, OEM redistribution, and commercial integrations require a separate commercial license.
>
> Commercial licensing, support, procurement terms, and custom delivery: **wwang11@alumni.nd.edu**

<p>
  <a href="#overview">Overview</a> &middot;
  <a href="#positioning">Positioning</a> &middot;
  <a href="#features">Features</a> &middot;
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#architecture">Architecture</a> &middot;
  <a href="#model-services">Model Services</a> &middot;
  <a href="#model-credits">Model Credits</a> &middot;
  <a href="#limitations-and-gpu-memory">Limitations</a> &middot;
  <a href="#multi-tenant-deployment">Multi-Tenant</a> &middot;
  <a href="#user-isolation">User Isolation</a> &middot;
  <a href="#security-and-deployment">Security</a> &middot;
  <a href="#license">License</a>
</p>

</div>

---

## Overview

**RedactionEverything** is a document anonymization system designed for local deployment. It splits unstructured files into a text path and a visual path, detects names, organizations, IDs, accounts, addresses, amounts, dates, seals, faces, signatures, and other sensitive elements, then provides a review interface, batch task management, and exportable redacted outputs.

The goal is not a narrow fixed-rule PII scanner. The project is built around configurable schemas:

- General schemas cover people, organizations, contact details, credentials, accounts, financial values, dates, addresses, and common identifiers.
- Industry schemas cover legal, finance, and healthcare scenarios with domain-specific detection items.
- Text recognition is handled by HaS Text semantic NER by default; regex is kept only as a user-defined fallback capability.
- Visual recognition combines OCR + HaS over extracted text with a single LocateAnything-3B visual feature service for visual-semantic targets such as faces, seals, and signatures, plus a local OpenCV detector that recovers binding and edge seals.
- Raw files, configuration, recognition results, and exported artifacts are intended to remain inside a local or intranet runtime.

---

## Positioning

RedactionEverything is designed as a full redaction workbench rather than a text-only privacy filter. Projects such as [OpenAI Privacy Filter](https://github.com/openai/privacy-filter) are valuable high-throughput baselines for token-level PII detection in text. This project targets a different layer of the problem: messy Chinese and bilingual business documents, scanned PDFs, Word contracts, images, visual privacy regions, human review, batch delivery, and local deployment.

The distinction is scope, not rhetoric:

- **Language and schema depth:** Chinese contracts, legal files, finance documents, healthcare materials, and mixed Chinese-English content often require domain schemas rather than a small fixed label set.
- **Document reality:** Production files are rarely clean text. They include PDF layout, OCR noise, tables, stamps, signatures, screenshots, photos, and scanned pages.
- **Vision coverage:** OCR + HaS handles text inside images, and LocateAnything-3B grounds visual features such as faces, IDs, bank cards, seals, screens, and handwritten signatures; a local OpenCV detector supplements red and dark binding/edge seals.
- **Operational workflow:** Recognition is only the first step. The system includes review, correction, selection, batch processing, task state, result history, and export packaging.
- **Privacy boundary:** The default architecture keeps raw files and model inference local or inside an intranet instead of depending on hosted external APIs.

---

## Features

| Capability | Description |
|---|---|
| Single-file processing | Upload TXT, DOCX, PDF, scanned PDF, PNG, JPG, and similar files, then recognize, review, redact, and export in one workflow. |
| Batch processing | Select a schema, upload a mixed queue, run recognition, review each file, and export packaged results. |
| Task center | Track task status, progress, review continuation, details, and deletion. Running tasks must be cancelled before deletion. |
| Processing results | View processed files, single-file outputs, batch tree results, paginated selection, and packaged downloads. |
| Text semantic NER | HaS Text recognizes entities directly from configured NER tags, without relying on built-in exhaustive rule mappings. |
| OCR + HaS | Images and scanned documents are converted into text blocks by PaddleOCR-VL / PP-StructureV3, then HaS Text performs semantic recognition and maps results back to coordinates. |
| Visual features | A single LocateAnything-3B service grounds the fixed visual presets (faces, fingerprints, IDs, bank cards, seals, screens, QR/barcodes, signatures, and more) and any user-defined visual label. |
| Seal recovery | A local OpenCV detector supplements LocateAnything by recovering red and dark/gray binding and edge seals, deduplicated against existing seal boxes. |
| Configurable schemas | Built-in general, legal, finance, and healthcare presets; custom text and visual items are supported, with exact tags (no family collapse). |
| Local deployment | Frontend, backend, and model services can run on a local or intranet GPU workstation. |

---

## Quick Start

### Requirements

| Dependency | Recommended version |
|---|---|
| Node.js | 24 LTS |
| Python | 3.11 |
| GPU | NVIDIA GPU; 16 GB VRAM is recommended for the full vision pipeline |
| CUDA | Match the local Paddle / vLLM build you use |

Model weights, real samples, uploaded files, runtime databases, logs, and exported results are not committed to this repository. Configure local paths in your own environment.

### One-command Local Startup (Windows + WSL)

From the repository root:

```bash
npm run dev
```

This starts the local hybrid profile in a fixed order: vLLM model services and the OCR wrapper in WSL, the LocateAnything visual feature service, the backend API, and finally the frontend. It only prints the ready signal after the model services are online and warmup has run:

```text
[dev] ready: http://localhost:3000
```

By default the heavy PaddleOCR-VL model is **off** and the text path uses PP-StructureV3 directly, which frees GPU memory for HaS Text and LocateAnything. Set `OCR_VL_ENABLED=1` to also start PaddleOCR-VL on port `8118`.

Stop all local services:

```bash
npm run stop
```

If WSL localhost forwarding is unavailable, the startup script automatically uses the WSL IP for vLLM/OCR services so frontend service detection does not incorrectly report them as offline. Model services should stay on GPU/CUDA; if `/health/services` reports CPU fallback risk for any critical model, fix the runtime before processing files.

### Manual Backend Startup

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/services
```

### Manual Frontend Startup

```bash
cd frontend
npm ci
npm run dev -- --host 0.0.0.0 --port 3000
```

Open `http://localhost:3000`.

### Docker

CPU API and frontend only:

```bash
docker compose up -d
```

Full GPU model stack (starts `ocr`, `ner`, and `visual-features`):

```bash
docker compose --profile gpu up -d
```

Before production deployment, configure `.env`, model mounts, GPU runtime, authentication, reverse proxy, and access-control policies.

---

## Architecture

```text
                   TXT / DOCX / PDF / IMG
                            |
                   FastAPI orchestration
                            |
        +-------------------+--------------------+
        |                                        |
  Text + OCR path                        Visual feature path
  PaddleOCR-VL 1.6 (optional)            LocateAnything-3B
  + PP-StructureV3                       (MoonViT vision tower +
        |                                 Qwen2 LM backbone)
  HaS Text semantic NER                          |
        |                                + OpenCV seal supplement
        |                                  (red / dark seals)
        +-------------------+--------------------+
                            |
                  Coordinate merge / dedupe
                            |
                  Review, redact, export
```

---

## Model Services

Default local ports:

| Service | Port | Description |
|---|---:|---|
| Backend API | 8000 | Uploads, jobs, presets, recognition, redaction, export |
| Frontend | 3000 | Browser workbench |
| HaS Text | 8080 | OpenAI-compatible semantic NER service (vLLM) |
| PaddleOCR / PP-StructureV3 | 8082 | OCR, layout, tables, and text boxes |
| PaddleOCR-VL 1.6 | 8118 | Optional VL OCR (vLLM); off by default |
| LocateAnything visual features | 8090 | MoonViT vision tower; visual presets and custom labels |
| LocateAnything LM backbone | 8091 | Optional Qwen2 LM via vLLM (prompt-embeds) for LocateAnything |

Common environment variables (see [`.env.example`](./.env.example) for the full template):

```env
# Local development without Docker
OCR_BASE_URL=http://127.0.0.1:8082
HAS_TEXT_RUNTIME=vllm
HAS_TEXT_VLLM_BASE_URL=http://127.0.0.1:8080/v1
VISUAL_FEATURES_BASE_URL=http://127.0.0.1:8090
LOCATE_ANYTHING_PORT=8090
LOCATE_ANYTHING_MAX_NEW_TOKENS=8192
# Optional VL OCR
OCR_VL_ENABLED=0
OCR_VLLM_URL=http://127.0.0.1:8118/v1
```

When VRAM is tight, adjust context length, maximum generation tokens, concurrency, and image size before allowing any critical model to silently fall back to CPU. CPU fallback typically appears in the UI as long waits, missing results, or offline service probes.

---

## Visual Feature Presets

The built-in visual feature set contains 22 fixed classes:

`face`, `fingerprint`, `palmprint`, `id_card`, `hk_macau_permit`, `passport`, `employee_badge`, `license_plate`, `bank_card`, `physical_key`, `receipt`, `shipping_label`, `official_seal`, `whiteboard`, `sticky_note`, `mobile_screen`, `monitor_screen`, `medical_wristband`, `qr_code`, `barcode`, `paper`, `signature`.

Users can add custom visual feature labels from the recognition settings UI. Custom labels are stored under the visual feature pipeline and are prompted through the same LocateAnything service.

---

## Model Credits

RedactionEverything is an orchestration and product layer. It does not claim ownership of third-party model weights, and this repository does not redistribute those weights. Please download models from their official repositories, review each model card, and comply with the corresponding license and terms before deployment.

| Component | Upstream model or project | Used for |
|---|---|---|
| PaddleOCR-VL / PP-StructureV3 | [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR), [PaddleOCR-VL](https://huggingface.co/PaddlePaddle/PaddleOCR-VL) | Document OCR, layout understanding, tables, text boxes, and page structure extraction |
| HaS Text | [xuanwulab/HaS_4.0_0.6B](https://huggingface.co/xuanwulab/HaS_4.0_0.6B) | Semantic NER for text and OCR text blocks |
| LocateAnything-3B | LocateAnything visual grounding model (download weights from the official upstream source) | Visual feature grounding: presets, custom labels, and signatures |
| vLLM runtime | [vLLM](https://github.com/vllm-project/vllm) | Local OpenAI-compatible serving for HaS Text, PaddleOCR-VL, and the LocateAnything LM backbone |
| Transformers runtime | [Hugging Face Transformers](https://github.com/huggingface/transformers) | Local runtime for the LocateAnything MoonViT vision tower |
| OpenCV | [OpenCV](https://github.com/opencv/opencv) | Local red/dark seal detection that supplements binding and edge seals |

Thanks to PaddlePaddle, Tencent Xuanwu Lab, the LocateAnything authors, vLLM, Hugging Face, OpenCV, and the broader open-source community. Their work makes local-first document redaction possible on commodity GPUs.

---

## Limitations and GPU Memory

RedactionEverything intentionally keeps recognition inside a local or intranet inference loop. The system processes raw sensitive files; sending those files to an online API may enable larger vision-language models, but it also weakens the privacy boundary that a redaction infrastructure is meant to provide. The default engineering direction is therefore single-GPU workstation deployment, with quantization, context control, concurrency control, and pipeline scheduling used to compress the full workflow into a local GPU runtime.

The visual feature stage uses a single LocateAnything-3B grounding model rather than a stack of specialized detectors. It covers common visual privacy regions such as faces, fingerprints, identity documents, bank cards, seals, QR/barcodes, screens, and handwritten signatures, and accepts user-defined visual labels through the same prompt path. A local OpenCV detector supplements red and dark binding/edge seals that grounding alone tends to miss.

This design has a clear resource tradeoff. The complete local pipeline can include PP-StructureV3, optional PaddleOCR-VL, HaS Text, and LocateAnything-3B at the same time. Even with warmup, GPU health checks, context compression, and serialized scheduling, devices below 16 GB VRAM may still slow down under VRAM pressure, KV cache allocation, multi-page images, or concurrent requests. For the full vision pipeline, 16 GB or more NVIDIA VRAM is recommended.

If your documents do not need visual recognition, disable the visual features in the preset configuration or in the single-file recognition panel. Keeping only OCR + HaS usually gives more stable latency and more VRAM headroom.

---

## Presets

The system ships a general default checklist plus three industry presets:

| Preset | Purpose |
|---|---|
| General (default) | People, IDs, passports, phone, email, address, dates, bank cards, and institutions — the common cross-domain set |
| Legal | Parties, agents, courts, case numbers, contract identifiers, and legal-document fields |
| Finance | Accounts, cards, transactions, amounts, institutions, customers, and financial business data |
| Healthcare | Patient name, ID, phone, address, birth date, gender, age, social security, medical record / registration / inpatient numbers, dates, times, medical institution and department |

Recognition items are atomic and exact-tagged, so a tag maps to exactly one recognition concept. Text and visual pipeline presets are independent. When creating a new preset, each module supports select-all and clear-all actions so schemas can be quickly trimmed for a scenario.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS, Radix UI |
| Backend | FastAPI, Pydantic, SQLite, local file storage |
| Text recognition | HaS Text through a vLLM OpenAI-compatible service |
| OCR | PaddleOCR-VL / PP-StructureV3 capabilities |
| Visual detection | LocateAnything-3B visual grounding + OpenCV seal supplement |
| Export | Text, image, PDF, Word, and batch packaging workflows |

---

## Repository Layout

```text
backend/
  app/          FastAPI app, task queue, recognition orchestration, redaction, export
  config/       Built-in recognition schemas and industry presets
  scripts/      Local model service and warmup scripts

frontend/
  src/          React workbench: single-file, batch, task center, results, presets
  public/       Static frontend assets

scripts/        Root local startup and shutdown scripts
```

---

## Security and Deployment

- The repository should contain application code and default configuration only. Do not commit local `.env` files, model weights, real samples, uploaded files, runtime databases, logs, or exported results.
- The default deployment model is local or intranet use. Before exposing the system to the public internet, configure authentication, access control, reverse proxy, TLS, logging, and key-rotation policies.
- Authentication supports multiple local users. Uploaded files, batch jobs, review drafts, downloads, previews, export reports, and cleanup operations are scoped to the authenticated username. The first setup user is the `super_admin`; only super administrators can create users or change runtime concurrency.
- Default recognition is driven by model capability and configured schemas. Regex exists only as a user-defined fallback mechanism.
- Keep models, samples, task data, and export directories in private runtime storage protected by access control and backup policies.

---

## Multi-Tenant Deployment

For customer deployments that require tenant isolation, use instance-level isolation: one Docker Compose project per tenant, with its own `.env`, domain, JWT secret, network, and Docker volumes. Do not share `DATA_DIR`, `UPLOAD_DIR`, `OUTPUT_DIR`, SQLite stores, exported results, or `JWT_SECRET_KEY` across tenants.

Example PowerShell tenant launch commands:

```powershell
$env:BACKEND_ENV_FILE=".env.tenant-a"
docker compose --env-file .env.tenant-a -p redaction-tenant-a --profile gpu up -d
Remove-Item Env:\BACKEND_ENV_FILE

$env:BACKEND_ENV_FILE=".env.tenant-b"
docker compose --env-file .env.tenant-b -p redaction-tenant-b --profile gpu up -d
Remove-Item Env:\BACKEND_ENV_FILE
```

Use per-tenant production env files based on `.env.production.example`. Set a unique `CORS_ORIGINS` domain and `JWT_SECRET_KEY` for each tenant, and keep `AUTH_ENABLED=true` for sensitive customer data. `BACKEND_ENV_FILE` must point at the same tenant env file so the backend container does not load a shared local `.env`.

The backend job queue uses `JOB_CONCURRENCY` for concurrent recognition/redaction job items. If a shared GPU must be capped at three concurrent job items, keep the sum of `JOB_CONCURRENCY` across all tenant instances at or below 3:

| Deployment shape | Recommended setting |
|---|---|
| One tenant on a dedicated GPU | `JOB_CONCURRENCY=3` |
| Two tenants sharing one GPU | split as `2 + 1` by SLA |
| Three tenants sharing one GPU | `JOB_CONCURRENCY=1` per tenant |

For stable latency on shared GPUs, start with `BATCH_RECOGNITION_PAGE_CONCURRENCY=1`, `HAS_NER_MAX_PARALLEL_REQUESTS=1`, and `VISION_DUAL_PIPELINE_PARALLEL=false`. Raise these only after measuring latency and VRAM headroom.

---

## User Isolation

Within one company deployment, use one application instance and create separate local users. Users share the same service URL and queue, but each authenticated username only sees its own files, jobs, review drafts, exports, previews, and cleanup scope.

The first login setup screen creates the `super_admin`. Additional users can be created only by a super administrator:

```bash
curl -X POST http://localhost:8000/api/v1/auth/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"username":"alice","password":"StrongPassw0rd!"}'
```

`JOB_CONCURRENCY=3` still means the whole instance processes at most three background job items at once; extra user requests queue instead of requiring a new deployment or port. A super administrator can change the live value from Settings -> Runtime or through the admin-only API:

```bash
curl -X PUT http://localhost:8000/api/v1/auth/concurrency \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"job_concurrency":3}'
```

---

## Contributing

Issues and pull requests are welcome. Keep PRs focused on one problem or feature, and avoid including local samples, experiment scripts, model weights, runtime data, or temporary outputs.

Before submitting, at minimum run:

```bash
cd backend
ruff check app/

cd ../frontend
npm run build
```

---

## License

This project uses a custom [Personal Use License](./LICENSE):

- Individuals may use it for free personal, non-commercial purposes, including personal projects, learning, research, private experiments, and demos.
- Paid work, consulting delivery, companies, institutions, government agencies, teams, and other organizations need a separate commercial license for production use, product integration, SaaS, managed services, OEM use, redistribution, and procurement scenarios.
- Model weights, third-party dependencies, and datasets are governed by their own licenses.

Commercial licensing: **wwang11@alumni.nd.edu**

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=TracyWang95/DataInfra-RedactionEverything&type=Date)](https://star-history.com/#TracyWang95/DataInfra-RedactionEverything&Date)
