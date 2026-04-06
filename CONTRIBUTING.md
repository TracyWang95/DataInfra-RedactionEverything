# Contributing / 贡献指南

Thanks for your interest in contributing! 感谢你对本项目的关注！

---

## Getting Started / 开发环境

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| Node.js | 18+ |
| GPU | NVIDIA 8 GB+ VRAM (recommended) |

```bash
# Clone
git clone https://github.com/TracyWang95/DataInfra-RedactionEverything.git
cd DataInfra-RedactionEverything

# Backend
cd backend && pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

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

We welcome Issues and PRs! 欢迎提交 Issue 与 PR！
