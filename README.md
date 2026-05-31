<div align="center">

# DataInfra &middot; RedactionEverything

**Local-first unstructured data redaction for documents, scanned PDFs, images, Word files, and plain text**

RedactionEverything is a local-first redaction workbench for sensitive information in real-world files. It combines semantic NER, OCR, visual object detection, configurable industry schemas, human review, batch processing, and export workflows so sensitive content can be found, reviewed, and anonymized without sending raw documents to a remote API.

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
  <a href="#latest-validated-updates">Latest Updates</a> &middot;
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

**RedactionEverything** is a document anonymization system designed for local deployment. It splits unstructured files into text and vision pipelines, detects names, organizations, IDs, accounts, addresses, amounts, dates, seals, faces, signatures, and other sensitive elements, then provides a review interface, batch task management, and exportable redacted outputs.

The goal is not a narrow fixed-rule PII scanner. The project is built around configurable schemas:

- General schemas cover people, organizations, contact details, credentials, accounts, financial values, dates, addresses, and common identifiers.
- Industry schemas cover legal, finance, and healthcare scenarios with domain-specific detection items.
- Text recognition is handled by HaS Text semantic NER by default; regex is kept only as a user-defined fallback capability.
- Vision recognition combines OCR + HaS, HaS Image YOLO, and VLM checklist/rubric detection for visual semantic features such as signatures.
- Raw files, configuration, recognition results, and exported artifacts are intended to remain inside a local or intranet runtime.

---

## Positioning

RedactionEverything is designed as a full redaction workbench rather than a text-only privacy filter. Projects such as [OpenAI Privacy Filter](https://github.com/openai/privacy-filter) are valuable high-throughput baselines for token-level PII detection in text. This project targets a different layer of the problem: messy Chinese and bilingual business documents, scanned PDFs, Word contracts, images, visual privacy regions, human review, batch delivery, and local deployment.

The distinction is scope, not rhetoric:

- **Language and schema depth:** Chinese contracts, legal files, finance documents, healthcare materials, and mixed Chinese-English content often require domain schemas rather than a small fixed label set.
- **Document reality:** Production files are rarely clean text. They include PDF layout, OCR noise, tables, stamps, signatures, screenshots, photos, and scanned pages.
- **Vision coverage:** OCR+HaS handles text inside images, HaS Image YOLO handles visual regions, and VLM rubric detection fills gaps such as handwritten signatures.
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
| OCR + HaS | Images and scanned documents are converted into text blocks, then HaS Text performs semantic recognition and maps results back to coordinates. |
| HaS Image YOLO | Detects visual regions such as faces, fingerprints, identity documents, bank cards, seals, QR codes, screens, and similar visual privacy targets. |
| VLM checklist | Adds visual-semantic coverage for targets that are hard to express as fixed object detection classes, with signature detection enabled by default. |
| Configurable schemas | Built-in general, legal, finance, and healthcare presets; custom text, image, VLM, and fallback items are supported. |
| Local deployment | Frontend, backend, and model services can run on a local or intranet GPU workstation. |

---

## Latest Validated Updates

The current branch includes a broad stability pass focused on demo readiness, customer deployment, and real-document recall. The changes are general engineering improvements rather than document-specific rules:

| Area | Update |
|---|---|
| User and tenant isolation | Recognition items, presets, vision pipeline settings, files, jobs, review drafts, history, previews, exports, and cleanup actions are scoped to the authenticated user. `super_admin` keeps system configuration and user-management privileges. |
| Single-GPU scheduling | GPU-heavy inference is guarded by a shared queue so OCR, HaS Image, HaS NER, and VLM work do not overload a single 16 GB GPU. VLM runs as a late supplemental stage for visual-semantic gaps. |
| OCR recall | OCR text boxes now use stronger coordinate matching, fuzzy matching, and visual-line matching so spaced or fragmented organization names can be recovered without hard-coding a company name. |
| Table semantic recall | Table headers, cells, and numeric columns are used to recover semantically sensitive values such as unit prices, totals, percentages, accounts, and contract amounts. |
| Seal and signature fallback | HaS Image remains the primary visual detector; local red/dark seal fallback and VLM/stroke-based signature checks supplement edge seals, seam seals, and handwritten signatures. |
| NER robustness | HaS NER responses are parsed with tolerant JSON recovery, long entity lists are chunked, and generation limits are raised to reduce truncation failures. |
| UI/UX reliability | New users land on the Start page, settings expose admin/runtime/monitoring controls, batch review and export states are clearer, narrow-screen layouts avoid horizontal overflow, and image review no longer revokes preview `blob:` URLs too early. |
| Validation evidence | A real UI batch run over `D:\ceshi` covered TXT, DOCX, image, and scanned PDF files: 7/7 uploaded, recognized, reviewed, redacted, and exported; 271 detections; 0 failed files; quality report `ready_for_delivery`. |

Validation commands used for this pass:

```bash
PYTHONPATH=backend pytest backend/tests -q

cd frontend
npm run lint
npm run build
```

The UI regression was run with Playwright against the local services and checked batch upload, recognition, review, redaction, ZIP export, quality-report export, console errors, and 390 px narrow-screen overflow.

---

## Quick Start

### Requirements

| Dependency | Recommended version |
|---|---|
| Node.js | 24 LTS |
| Python | 3.11 |
| GPU | NVIDIA GPU; 16 GB VRAM is recommended for the full vision pipeline |
| CUDA | Match the local Paddle / vLLM / llama.cpp build you use |

Model weights, real samples, uploaded files, runtime databases, logs, and exported results are not committed to this repository. Configure local paths in your own environment.

### One-command Local Startup (Windows + WSL)

From the repository root:

```bash
npm run dev
```

This starts the local hybrid profile in a fixed order: vLLM model services and the OCR wrapper in WSL, Windows CUDA llama.cpp VLM, HaS Image, the backend API, and finally the frontend. The script runs model warmup first. It only prints the ready signal after HaS Text, PaddleOCR-VL, PP-StructureV3, HaS Image, and GLM VLM all warm up successfully:

```text
[dev] ready: http://localhost:3000
```

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

Open:

```text
http://localhost:3000
```

### Docker

The repository keeps Dockerfiles and compose configuration for containerized frontend, backend, and model-service deployments. Before production deployment, configure `.env`, model mounts, GPU runtime, authentication, reverse proxy, and access-control policies.

---

## Architecture

```text
                   +------------------------+
                   |  TXT / DOCX / PDF / IMG |
                   +-----------+------------+
                               |
                   +-----------v------------+
                   |  FastAPI orchestration  |
                   +-----------+------------+
                               |
        +----------------------+----------------------+
        |                      |                      |
+-------v--------+     +-------v--------+     +-------v--------+
| Text semantic  |     | OCR + HaS      |     | Vision regions |
| HaS Text NER   |     | OCR text boxes |     | YOLO / VLM     |
+-------+--------+     +-------+--------+     +-------+--------+
        |                      |                      |
        +----------------------+----------------------+
                               |
                   +-----------v------------+
                   | Coordinate merge/dedupe |
                   +-----------+------------+
                               |
                   +-----------v------------+
                   | Review, redact, export |
                   +------------------------+
```

---

## Model Services

Default local ports:

| Service | Port | Description |
|---|---:|---|
| Backend API | 8000 | Uploads, jobs, presets, recognition, redaction, export |
| Frontend | 3000 | Browser workbench |
| HaS Text | 8080 | OpenAI-compatible text NER service |
| HaS Image | 8081 | YOLO11 visual-region detection |
| PaddleOCR-VL | 8082 | OCR, layout, and text boxes |
| VLM | 8090 | OpenAI-compatible visual-semantic supplement |

Common environment variables:

```env
OCR_BASE_URL=http://127.0.0.1:8082
HAS_TEXT_RUNTIME=vllm
HAS_TEXT_VLLM_BASE_URL=http://127.0.0.1:8080/v1
HAS_IMAGE_BASE_URL=http://127.0.0.1:8081
VLM_BASE_URL=http://127.0.0.1:8090
VLM_MODEL_NAME=GLM-4.6V-Flash-Q4
```

When VRAM is tight, adjust context length, maximum generation tokens, concurrency, and image size before allowing any critical model to silently fall back to CPU. CPU fallback typically appears in the UI as long waits, missing results, or offline service probes.

---

## Model Credits

RedactionEverything is an orchestration and product layer. It does not claim ownership of third-party model weights, and this repository does not redistribute those weights. Please download models from their official repositories, review each model card, and comply with the corresponding license and terms before deployment.

| Component | Upstream model or project | Used for |
|---|---|---|
| PaddleOCR-VL | [PaddlePaddle/PaddleOCR-VL](https://huggingface.co/PaddlePaddle/PaddleOCR-VL) | Document OCR, layout understanding, text boxes, and page structure extraction |
| HaS Text | [xuanwulab/HaS_4.0_0.6B](https://huggingface.co/xuanwulab/HaS_4.0_0.6B), optionally [xuanwulab/HaS_4.0_0.6B_GGUF](https://huggingface.co/xuanwulab/HaS_4.0_0.6B_GGUF) | Semantic NER for text and OCR text blocks |
| HaS Image | [xuanwulab/HaS_Image_0209_FP32](https://huggingface.co/xuanwulab/HaS_Image_0209_FP32) | YOLO11-based visual privacy region segmentation |
| GLM VLM | [zai-org/GLM-4.6V-Flash](https://huggingface.co/zai-org/GLM-4.6V-Flash), with local llama.cpp deployment through a compatible GGUF quant such as [unsloth/GLM-4.6V-Flash-GGUF](https://huggingface.co/unsloth/GLM-4.6V-Flash-GGUF) | Rubric/checklist-based visual-semantic detection, currently focused on signatures |
| YOLO runtime | [Ultralytics YOLO](https://github.com/ultralytics/ultralytics) | Runtime framework for HaS Image instance segmentation |
| llama.cpp runtime | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) | Local OpenAI-compatible VLM serving for GGUF weights |
| vLLM runtime | [vLLM](https://github.com/vllm-project/vllm) | Local OpenAI-compatible serving for HaS Text and PaddleOCR-VL |

Thanks to PaddlePaddle, Tencent Xuanwu Lab, Z.ai, Unsloth, Ultralytics, llama.cpp, vLLM, and the broader open-source model community. Their work makes local-first document redaction possible on commodity GPUs.

---

## Limitations and GPU Memory

RedactionEverything intentionally keeps recognition inside a local or intranet inference loop. The system processes raw sensitive files; sending those files to an online API may enable larger vision-language models, but it also weakens the privacy boundary that a redaction infrastructure is meant to provide. The default engineering direction is therefore single-GPU workstation deployment, with quantization, context control, concurrency control, and pipeline scheduling used to compress the full workflow into a local GPU runtime.

The VLM stage in the vision pipeline is not a replacement for HaS Image YOLO11. It is a complementary layer. YOLO11 covers common visual privacy regions such as faces, fingerprints, identity documents, bank cards, seals, QR codes, and screens. It does not currently include a separately trained object-detection class for handwritten signatures. Signatures and signing strokes require more visual-semantic judgment, so the default local profile uses the GLM-4.6V-Flash Q4 quantized model with rubric/checklist prompting to detect signature regions.

This design has a clear resource tradeoff. The complete local pipeline can include PaddleOCR-VL, HaS Text, HaS Image YOLO, and GLM VLM at the same time. Even with warmup, GPU health checks, context compression, and serialized VLM scheduling, devices below 16 GB VRAM may still slow down under VRAM pressure, KV cache allocation, multi-page images, or concurrent requests. For the full vision pipeline, 16 GB or more NVIDIA VRAM is recommended.

If your documents do not need signature recognition, disable the VLM/signature item in the preset configuration or in the single-file recognition panel. Keeping only OCR+HaS and HaS Image usually gives more stable latency and more VRAM headroom.

Larger local VLMs can improve visual-semantic understanding, but they also raise the deployment bar. This project prioritizes practical local deployment on personal workstations, single-GPU laptops, and intranet machines rather than depending on the largest possible model or a hosted external API.

---

## Presets

The system includes four preset families:

| Preset | Purpose |
|---|---|
| General | People, organizations, IDs, accounts, contact details, addresses, amounts, dates, and common sensitive entities |
| Legal | Parties, agents, courts, case numbers, contract identifiers, case facts, and legal-document fields |
| Finance | Accounts, cards, transactions, amounts, institutions, customers, and financial business data |
| Healthcare | Patients, medical institutions, examinations, diagnoses, medications, medical records, and visit information |

Text and image pipeline presets are independent. When creating a new preset, each module supports select-all and clear-all actions so schemas can be quickly trimmed for a scenario.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, Radix UI, Zustand |
| Backend | FastAPI, Pydantic, SQLite, local file storage |
| Text recognition | HaS Text through vLLM or an OpenAI-compatible llama.cpp service |
| OCR | PaddleOCR-VL / PP-Structure capabilities |
| Vision detection | HaS Image YOLO11, VLM checklist/rubric detection |
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

Use per-tenant production env files based on `.env.production.example`. Set a unique `CORS_ORIGINS` domain and `JWT_SECRET_KEY` for each tenant, keep `AUTH_ENABLED=true`, and keep `FILE_ENCRYPTION_ENABLED=true` for sensitive customer data. `BACKEND_ENV_FILE` must point at the same tenant env file so the backend container does not load a shared local `.env`.

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
python -m ruff check app/

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
