# DataInfra-RedactionEverything

## Project Overview
Legal document redaction platform with AI-powered PII detection.
Monorepo: frontend (React 19 + Vite + TypeScript + Tailwind CSS) + backend (FastAPI) + AI microservices.

## Architecture
- **Frontend**: `frontend/` — React 19, Vite 6, TypeScript strict, Tailwind CSS 3.4, Zustand 5, React Router 7
- **Backend**: `backend/` — FastAPI + Python 3.10+, SQLite WAL, async task queue
- **AI Services**: PaddleOCR (port 8082), NER (port 8080), YOLO11 Vision (port 8081)

## Build & Run
```bash
# Frontend dev
cd frontend && npm run dev        # Vite dev server on :3000

# Frontend checks
cd frontend && npm run build      # tsc + vite build
cd frontend && npm run lint       # ESLint
cd frontend && npm run test       # Vitest unit tests
cd frontend && npx playwright test # E2E tests

# Backend dev
cd backend && uvicorn app.main:app --reload --port 8000
```

## Frontend Directory Structure
```
src/
  app/              # App shell (layout, router, providers)
  components/
    ui/             # ShadCN components (auto-generated, do NOT hand-edit)
    shared/         # Shared business components
  features/         # Feature modules (playground, batch, jobs, history, settings, dashboard, audit-log)
  services/         # Unified API client (api-client.ts)
  hooks/            # Global hooks
  types/            # Global type definitions
  config/           # Configuration constants
  i18n/             # Internationalization (en/zh)
  lib/              # Utilities (cn() etc.)
```

## Frontend Coding Rules
1. Named exports only (no default exports)
2. Components under 150 lines; decompose if larger
3. One Zustand store per feature domain
4. All API calls through `src/services/api-client.ts` — no raw fetch()
5. All user-facing strings through i18n — no hardcoded text
6. Tailwind utility classes only; use ShadCN `cn()` for conditional merging
7. No `any` types — use `unknown` + type guards
8. All interactive elements need `data-testid` attributes
9. Path alias: `@/*` maps to `src/*`

## Git Conventions
```
<type>(<scope>): <description>
Types: feat, fix, chore, docs, test, refactor, ui, perf
Scopes: playground, batch, jobs, history, settings, dashboard, audit, layout, api, i18n, e2e
```

## API Overview
- Base URL: `/api/v1`
- Auth: Bearer JWT + CSRF double-submit cookie
- File upload: multipart/form-data to `/files/upload`
- Jobs: REST at `/jobs/`
- Vite proxies `/api`, `/health`, `/uploads`, `/outputs` to backend

## Ports (local dev)
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- PaddleOCR: http://localhost:8082
- NER Service: http://localhost:8080
- YOLO11 Vision: http://localhost:8081
