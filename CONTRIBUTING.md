# Contributing / 贡献指南

Thanks for your interest in contributing! 感谢你对本项目的关注！

---

## Getting Started / 开发环境

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| Node.js | 18+ |
| GPU | NVIDIA 8 GB+ VRAM (recommended) |

### Option A: Docker Compose (recommended)

```bash
git clone https://github.com/TracyWang95/DataInfra-RedactionEverything.git
cd DataInfra-RedactionEverything

# CPU only (no AI model services)
docker compose up -d

# With GPU model services (OCR + NER + Vision)
docker compose --profile gpu up -d
```

### Option B: Local Development (no Docker)

```bash
git clone https://github.com/TracyWang95/DataInfra-RedactionEverything.git
cd DataInfra-RedactionEverything

# 1. Backend (FastAPI)
cd backend
pip install -r requirements.txt
DEBUG=true python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 2. Frontend (Vite dev server)
cd frontend && npm install && npm run dev

# 3. GPU Model Services (each in a separate terminal)
# PaddleOCR-VL (port 8082) — requires paddlepaddle-gpu + paddleocr
cd backend && python scripts/ocr_server.py

# HaS Image YOLO (port 8081) — requires ultralytics
cd backend && python scripts/has_image_server.py

# HaS Text NER (port 8080) — requires llama-server (llama.cpp)
llama-server --host 0.0.0.0 --port 8080 \
  -m /path/to/HaS_Text_0209_0.6B_Q4_K_M.gguf -ngl 99
```

> **Note:** When running locally (not Docker), the backend auto-detects
> `127.0.0.1` service URLs. No `.env` file change needed for local dev.

Verify services: `curl http://localhost:8000/health/services`

---

## Branch & Commit Convention / 分支与提交

Branch names:

```
feature/<name>    — new capability
fix/<name>        — bug fix
refactor/<name>   — restructuring without behavior change
```

Commit messages — **[Conventional Commits](https://www.conventionalcommits.org/)**:

```
feat: add batch re-run recognition button
fix: popover overflows canvas in step4 review
refactor: extract shared domSelection utils
docs: update quickstart for Docker Compose
chore: clean repo for release
```

---

## Code Style / 代码规范

**Frontend (TypeScript + React)**

- Named exports only — no `export default`
- Components ≤ 150 lines; extract hooks / utils when larger
- Tailwind for styling — no inline `style` except dynamic values
- All user-facing strings via `@/i18n` — no hardcoded text
- ShadCN components for UI primitives

**Backend (Python + FastAPI)**

- Thin API routers — business logic in `services/`
- Pydantic models in `models/` (domain-split schema files)
- All file paths resolved via `core/config.py` settings
- No cloud API calls — all inference must run locally

---

## Testing / 测试

```bash
# TypeScript type check
cd frontend && npx tsc --noEmit

# Playwright E2E tests (requires backend running)
cd frontend && npx playwright test

# Single test
npx playwright test e2e/click-upload.spec.ts
```

---

## Pre-commit Hooks / 预提交钩子

This project uses [pre-commit](https://pre-commit.com/) to enforce code quality checks before every commit.

**Installation / 安装:**

```bash
pip install pre-commit
pre-commit install
```

**Manual run / 手动运行:**

```bash
# Run all hooks on every file
pre-commit run --all-files

# Run a specific hook
pre-commit run ruff --all-files
```

**Configured hooks / 已配置的钩子:**

| Hook | Purpose |
|---|---|
| **ruff** | Python linter and formatter (replaces flake8 + isort + black) |
| **prettier** | TypeScript / JSON / Markdown formatter |
| **bandit** | Python security linter (detects common vulnerabilities) |
| **detect-secrets** | Prevents accidental commit of API keys, passwords, tokens |

If a hook fails, fix the reported issues and `git add` the changed files before committing again.
Pre-commit hooks 失败时，请修复报告的问题并重新 `git add` 后再提交。

---

## Pull Request Checklist / PR 清单

- [ ] All inference runs locally — no cloud API calls
- [ ] `npx tsc --noEmit` passes with zero errors
- [ ] Playwright tests pass (or new tests added for new features)
- [ ] User-facing strings use i18n keys
- [ ] Documentation updated if applicable

---

## Reporting Issues / 提交 Issue

- **Bug**: reproduction steps + environment info + error log
- **Feature request**: use case + expected behavior
- **Security**: see [SECURITY.md](./SECURITY.md) for responsible disclosure

---

## License Agreement / 许可协议

By submitting a pull request, you agree that your contributions will be licensed under the [Apache License 2.0](./LICENSE), the same license that covers this project. If your employer has intellectual property policies, please ensure you have permission to contribute.

提交 PR 即表示您同意将贡献按 [Apache License 2.0](./LICENSE) 许可。如果您的雇主有知识产权政策，请确保已获得贡献许可。

---

We welcome Issues and PRs! 欢迎提交 Issue 与 PR！
