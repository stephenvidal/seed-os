# SEED OS

**From intention to execution.** A self-hostable, model-agnostic autonomous agent
platform: describe an outcome, and SEED plans, executes, verifies, and delivers
it — with full visibility and control.

| | |
|---|---|
| Directive | v1.1 — [DIRECTIVE.md](DIRECTIVE.md) |
| Current milestone | M1 Premium application foundation (see [progress](docs/progress.md)) |
| Stack | React + Vite + TS + Tailwind · Python + FastAPI · Docker Compose |

## What works today
- **Sign-in** as the bootstrap administrator (from environment), with signed
  HttpOnly session cookie, server-side role checks, and failed-login rate limiting.
- **SEED Workspace shell:** collapsible sidebar, mobile drawer, command palette
  (`Ctrl/⌘+K`), `G`-then-key navigation, light/dark/system theme with persistence.
- **Command Center** with live host telemetry from the API (memory, load, uptime,
  API RSS) and an honest component status list.
- **Settings:** theme selection, account, system details.
- Chat, Tasks, Agents, Projects, Studio, Inspector, Models, Tools: page structure
  with empty states naming the milestone that delivers each. **No agent execution
  exists yet** (M2).

## API (as built)
| Method | Path | Auth | Result |
|---|---|---|---|
| GET | `/healthz` | none | `{status, version}` |
| POST | `/api/v1/auth/login` | none | `{username, role}` + cookie; 401 `invalid_credentials`, 429 `rate_limited`, 503 `auth_not_configured`, 422 `invalid_request` |
| POST | `/api/v1/auth/logout` | none | 204, clears cookie |
| GET | `/api/v1/auth/me` | session | `{username, role}`; 401 `unauthenticated` |
| GET | `/api/v1/system` | session | host/process telemetry |

Errors are always `{"error": {"code", "message"}}`. OpenAPI at `/api/docs`.

## Run
**Compose:** `cp .env.example .env`, set `SEED_ADMIN_PASSWORD` and
`SEED_SESSION_SECRET`, then `docker compose up -d --build` → http://localhost:8080.

**Development:**
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
SEED_ADMIN_PASSWORD=dev .venv/bin/uvicorn seed_api.main:app --reload   # :8000
cd frontend && npm ci && npm run dev                                   # :5173
```

## Configuration
| Variable | Default | Meaning |
|---|---|---|
| `SEED_ADMIN_USERNAME` | `admin` | Bootstrap admin username |
| `SEED_ADMIN_PASSWORD` | unset | Required to enable sign-in |
| `SEED_SESSION_SECRET` | random per process | Session signing key; set it so sessions survive restarts |
| `SEED_SESSION_TTL_SECONDS` | `43200` | Session lifetime |
| `SEED_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `SEED_LOGIN_MAX_FAILURES` / `SEED_LOGIN_WINDOW_SECONDS` | `5` / `60` | Sign-in rate limit |
| `SEED_CORS_ORIGINS` | `[]` | JSON list; only needed if the UI is served from another origin |

## Repository map
| Path | Purpose |
|---|---|
| `DIRECTIVE.md`, `CLAUDE.md` | Governing directive and implementer rules |
| `backend/` | SEED API (FastAPI) |
| `frontend/` | SEED Workspace (React SPA) |
| `compose.yaml`, `.env.example` | Local/self-hosted stack (builds from source) |
| `deploy/compose.yaml`, `.github/workflows/` | Production stack (GHCR images) and self-hosted CI/deploy; see `docs/deployment.md` |
| `docs/` | Vision, requirements, architecture, design system, security, deployment, model strategy, testing, roadmap, progress, decisions |
| `docs/decisions/` | ADRs |
