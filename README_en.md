<div align="center">

# DataInfra &middot; RedactionEverything

**Open-source anonymization infrastructure for unstructured data**

Not just PII — **Redaction _Everything_**.<br/>
Define your own sensitive content. Anonymize anything: PII, trade secrets, medical records, classified IDs…<br/>
Word, PDF, scans, images — dual AI pipelines, 100% on-premise.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](./LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#contributing)
[![GitHub Stars](https://img.shields.io/github/stars/TracyWang95/DataInfra-RedactionEverything?style=social)](https://github.com/TracyWang95/DataInfra-RedactionEverything)

English &nbsp;|&nbsp; **[中文](./README.md)**

> **License: [Apache License 2.0](./LICENSE)** — free for academic, research, and non-commercial use.<br/>
> **Commercial use (SaaS / OEM / enterprise 50+ seats) requires a commercial license.** See **[COMMERCIAL_LICENSE.md](./COMMERCIAL_LICENSE.md)**.

<p>
  <a href="#what-is-this">What is this?</a> &middot;
  <a href="#features">Features</a> &middot;
  <a href="#quickstart">Quickstart</a> &middot;
  <a href="#architecture">Architecture</a> &middot;
  <a href="#tech-stack">Tech Stack</a> &middot;
  <a href="#deployment">Deployment</a> &middot;
  <a href="#contributing">Contributing</a> &middot;
  <a href="#license">License</a>
</p>

<!-- screenshot: hero -->

</div>

---

## What is this?

It's called **Redaction _Everything_** because we anonymize more than just PII.

Every industry has its own sensitive data — case numbers and party names in legal contracts, diagnoses in medical records, account numbers in financial documents, classified designators in defense files. Legacy tools only handle PII and fall flat on domain-specific fields.

**RedactionEverything** is built around **full customizability**: you define what's sensitive, the system detects and anonymizes it. 60+ entity types work out of the box, plus custom regex rules, AI semantic rules, and tag templates to fit any industry or compliance requirement.

Under the hood, a **dual-pipeline architecture** — OCR + NER for text entities, YOLO11 instance segmentation for 21 visual target categories (faces, seals, ID cards, QR codes…) — fuses results for comprehensive coverage. Everything runs locally: **your data never leaves your network**.

---

## Features

| | Feature | Description |
|---|---|---|
| :wrench: | **Fully Customizable** | Custom entity types, regex rules, AI semantic rules, tag templates — not just PII, **define and detect anything sensitive** |
| :brain: | **AI Semantic Recognition** | LLM-powered NER (Qwen3-0.6B via llama.cpp) that understands context, not just pattern matching |
| :eyes: | **Visual Feature Detection** | YOLO11 instance segmentation — faces, fingerprints, seals, signatures, ID cards, bank cards, QR codes, license plates — **21 categories** |
| :page_facing_up: | **Multi-format** | DOCX, PDF, scanned PDF, JPG, PNG |
| :zap: | **Batch Processing** | 5-step wizard: configure → upload → queue → review → export |
| :shield: | **100% On-premise** | All inference runs locally, zero cloud dependencies, data stays in your network |
| :dart: | **Multi-industry Compliance** | Legal, medical, finance, government — GDPR, PIPL, GB/T 37964-2019 |
| :globe_with_meridians: | **Bilingual UI** | Chinese / English — switch in one click |
| :gear: | **REST API** | 85+ endpoints, SSE real-time progress, Swagger / ReDoc docs |

---

## Screenshots

<!-- screenshot: playground single-file flow -->

<!-- screenshot: batch review three-column layout -->

<!-- screenshot: detection results with dual-pipeline overlay -->

---

## Quickstart

### Docker Compose (recommended)

```bash
git clone https://github.com/TracyWang95/DataInfra-RedactionEverything.git
cd DataInfra-RedactionEverything

# CPU-only (no GPU services)
docker compose up -d

# With GPU services (OCR, NER, Vision)
docker compose --profile gpu up -d
```

Then open **http://localhost:3000**.

### Manual Setup

<details>
<summary><strong>Prerequisites</strong></summary>

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| Node.js | 18+ |
| GPU | NVIDIA with 8 GB+ VRAM (RTX 4060 or above recommended) |
| llama.cpp | Latest release (for NER service) |

</details>

#### 1. Clone and prepare models

```bash
git clone https://github.com/TracyWang95/DataInfra-RedactionEverything.git
cd DataInfra-RedactionEverything

# Download model weights
# - HaS Text NER:  huggingface.co/xuanwulab/HaS_Text_0209_0.6B_Q4
# - HaS Image:     sensitive_seg_best.pt (YOLO11)
# - PaddleOCR-VL:  auto-downloaded on first run (~2 GB)
```

#### 2. Start AI services

```bash
# HaS NER (port 8080)
llama-server -hf xuanwulab/HaS_Text_0209_0.6B_Q4 \
  --port 8080 -ngl 99 --host 0.0.0.0 -c 8192 -np 1

# HaS Image — YOLO11 (port 8081)
cd backend && python has_image_server.py

# PaddleOCR-VL (port 8082)
cd backend && python ocr_server.py
```

#### 3. Start the backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### 4. Start the frontend

```bash
cd frontend
npm install && npm run dev
```

Open **http://localhost:3000** and verify all services are green:

```bash
curl http://127.0.0.1:8000/health/services
```

---

## Architecture

```
                          +------------------+
                          |   User uploads   |
                          | DOCX / PDF / IMG |
                          +--------+---------+
                                   |
                          +--------v---------+
                          |   File parsing   |
                          |  & page imaging  |
                          +--------+---------+
                                   |
                    +--------------+--------------+
                    |                              |
          +---------v----------+       +----------v---------+
          |  Pipeline 1: Text  |       | Pipeline 2: Vision |
          +---------+----------+       +----------+---------+
                    |                              |
          +---------v----------+       +----------v---------+
          |   PaddleOCR-VL-1.5 |       |   YOLO11 (21-class |
          |   text detection   |       |   instance segment) |
          +---------+----------+       +----------+---------+
                    |                              |
          +---------v----------+                   |
          |   HaS NER (Q4)    |                   |
          |   entity recog.   |                   |
          +---------+----------+                   |
                    |                              |
          +---------v----------+       +----------v---------+
          |  Entity-to-coord   |       |  Normalize coords  |
          |  matching          |       |  (0-1 relative)    |
          +---------+----------+       +----------+---------+
                    |                              |
                    +--------------+--------------+
                                   |
                          +--------v---------+
                          |   IoU dedup &    |
                          |   result fusion  |
                          +--------+---------+
                                   |
                          +--------v---------+
                          | Interactive edit |
                          | & redaction      |
                          +------------------+
```

**Five services** work together:

| Service | Port | Role |
|---|---|---|
| **Frontend** | 3000 | React UI — upload, annotate, review, export |
| **Backend API** | 8000 | FastAPI — orchestration, job queue, file I/O |
| **HaS NER** | 8080 | llama.cpp — named entity recognition |
| **HaS Image** | 8081 | YOLO11 — 21-class visual PII segmentation |
| **PaddleOCR** | 8082 | PaddleOCR-VL-1.5 — text detection & layout |

---

## Tech Stack

| Layer | Technology | Version |
|---|---|---|
| **Frontend** | React | 19 |
| | TypeScript | 5.7 |
| | Vite | 6.1 |
| | Tailwind CSS | 3.4 |
| | Radix UI (ShadCN) | latest |
| | Zustand | 5.0 |
| | Playwright | 1.58 |
| **Backend** | FastAPI | 0.115+ |
| | Python | 3.10+ |
| | SQLite | (via job queue) |
| | Celery + Redis | 5.4+ |
| **AI / ML** | PaddleOCR-VL-1.5 | 2.7+ |
| | HaS Text (Qwen3-0.6B Q4) | via llama.cpp |
| | YOLO11 (Ultralytics) | 8.3+ |

---

## API

The backend exposes **85+ REST endpoints** across 13 route modules:

- **Vision Pipeline** — detect, redact, preview
- **Jobs** — batch task CRUD, queue management, review/approve workflow
- **Files** — upload, download, format conversion
- **Entity Types** — custom entity type management
- **Redaction** — apply anonymization with multiple strategies
- **Model Config** — switch models, adjust parameters at runtime
- **Auth** — JWT-based authentication (optional)
- **Safety** — file scanning and validation

Interactive docs available at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

---

## Deployment

### Docker Compose

```yaml
# docker-compose.yml ships with 5 services:
# backend, frontend, ocr, ner, vision
# GPU services use the "gpu" profile

docker compose --profile gpu up -d
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DEBUG` | `false` | Enable debug logging |
| `AUTH_ENABLED` | `false` | Enable JWT authentication |
| `OCR_BASE_URL` | `http://localhost:8082` | PaddleOCR service URL |
| `HAS_LLAMACPP_BASE_URL` | `http://localhost:8080/v1` | HaS NER service URL |
| `HAS_IMAGE_BASE_URL` | `http://localhost:8081` | HaS Image service URL |
| `HAS_IMAGE_WEIGHTS` | auto-detect | Path to YOLO11 weights file |
| `HAS_MODELS_DIR` | auto-detect | Root directory for model files |
| `JOB_DB_PATH` | `data/jobs.sqlite3` | SQLite database path for job queue |
| `HAS_NER_DISPLAY_NAME` | `HaS-Text-0209-Q4` | Display name shown in sidebar |

### GPU Setup

For optimal OCR performance, install the GPU build of PaddlePaddle **before** installing backend dependencies:

```bash
pip install paddlepaddle-gpu          # CUDA 12.6
pip install -r backend/requirements.txt

# Verify
python -c "import paddle; print(paddle.is_compiled_with_cuda(), paddle.get_device())"
# Expected: True gpu:0
```

---

## Visual PII Categories (HaS Image)

YOLO11 detects **21 categories** of visual PII, covering documents, biometrics, devices, and codes:

| ID | Slug | Category |
|:---:|---|---|
| 0 | `face` | Human face |
| 1 | `fingerprint` | Fingerprint |
| 2 | `palmprint` | Palmprint |
| 3 | `id_card` | ID card |
| 4 | `hk_macau_permit` | HK/Macau travel permit |
| 5 | `passport` | Passport |
| 6 | `employee_badge` | Employee badge |
| 7 | `license_plate` | License plate |
| 8 | `bank_card` | Bank card |
| 9 | `physical_key` | Physical key |
| 10 | `receipt` | Receipt |
| 11 | `shipping_label` | Shipping label |
| 12 | `official_seal` | Official seal |
| 13 | `whiteboard` | Whiteboard |
| 14 | `sticky_note` | Sticky note |
| 15 | `mobile_screen` | Mobile screen |
| 16 | `monitor_screen` | Monitor screen |
| 17 | `medical_wristband` | Medical wristband |
| 18 | `qr_code` | QR code |
| 19 | `barcode` | Barcode |
| 20 | `paper` | Paper document |

---

## Compliance

This project references the following data protection standards:

| Standard | Scope |
|---|---|
| **GDPR** (EU) | General Data Protection Regulation |
| **PIPL** (China) | Personal Information Protection Law |
| **GB/T 37964-2019** | Information security — Guide for de-identification of personal information |

The entity taxonomy is built on GB/T 37964-2019, classifying PII into **direct identifiers** (name, ID number, phone), **quasi-identifiers** (company, address, date), and **visual elements** (seals, faces, documents).

---

## Contributing

We welcome contributions! Please read **[CONTRIBUTING.md](./CONTRIBUTING.md)** before submitting a PR.

```bash
# Run E2E tests
cd frontend && npm run test:e2e

# Run unit tests
cd frontend && npm run test
```

PR checklist:
- [ ] All inference runs locally — no cloud API calls
- [ ] Smoke test passes
- [ ] Documentation updated (if applicable)

---

## License

This project is licensed under the **[Apache License 2.0](./LICENSE)**.

For commercial deployment, OEM, or managed-service use, a separate commercial license is required.
See **[COMMERCIAL_LICENSE.md](./COMMERCIAL_LICENSE.md)** for details.

---

## Security

Please see **[SECURITY.md](./SECURITY.md)** for our security policy and responsible disclosure process. Key principle: this platform is designed for **on-premise deployment** — no data is transmitted externally.

---

<div align="center">

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=TracyWang95/DataInfra-RedactionEverything&type=Date)](https://star-history.com/#TracyWang95/DataInfra-RedactionEverything&Date)

If this project helps you, please consider giving it a star.

</div>
