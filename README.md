# SEED OS

**From intention to execution.** A self-hostable, model-agnostic autonomous agent
platform: describe an outcome, and SEED plans, executes, verifies, and delivers
it — with full visibility and control.

| | |
|---|---|
| Directive | v1.1 — [DIRECTIVE.md](DIRECTIVE.md) |
| Current milestone | M2 Core agent runtime (see [progress](docs/progress.md)) |
| Stack | React + Vite + TS + Tailwind · Python + FastAPI · Docker Compose |

## What works today
- **Sign-in** as the bootstrap administrator (from environment), with signed
  HttpOnly session cookie, server-side role checks, and failed-login rate limiting.
- **SEED Workspace shell:** collapsible sidebar, mobile drawer, command palette
  (`Ctrl/⌘+K`), `G`-then-key navigation, light/dark/system theme with persistence.
- **Command Center** with live host telemetry from the API (memory, load, uptime,
  API RSS) and an honest component status list.
- **Settings:** theme selection, account, system details.
- **Chat (M2, in progress):** pick a model from the configured provider (Ollama),
  send a request, and watch the agent stream its answer and its tool calls. The
  agent has list/read/write file tools confined to a per-run workspace. Runs are
  bounded (steps, time, tokens) and **not saved**: leaving the page stops the run
  (durable runs are M3/M4).
- Tasks, Agents, Projects, Studio, Inspector, Models, Tools: page structure with
  empty states naming the milestone that delivers each.

## API (as built)
| Method | Path | Auth | Result |
|---|---|---|---|
| GET | `/healthz` | none | `{status, version}` |
| POST | `/api/v1/auth/login` | none | `{username, role}` + cookie; 401 `invalid_credentials`, 429 `rate_limited`, 503 `auth_not_configured`, 422 `invalid_request` |
| POST | `/api/v1/auth/logout` | none | 204, clears cookie |
| GET | `/api/v1/auth/me` | session | `{username, role}`; 401 `unauthenticated` |
| GET | `/api/v1/system` | session | host/process telemetry |
| GET | `/api/v1/models` | admin | `{provider, default_model, models[]}` from the provider; 503 `provider_not_configured`, 502 `provider_<kind>` |
| POST | `/api/v1/runs` | admin | `{model, prompt, history[]}` → `text/event-stream` of run events (`run_id`, `run_started`, `step_started`, `text_delta`, `tool_call`, `tool_result`, `step_completed`, `provider_retry`, `run_finished`); 429 `busy` at the concurrency limit |

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
| `SEED_OLLAMA_API_KEY` | unset | Ollama Cloud key; unset disables Chat (typed 503) |
| `SEED_OLLAMA_BASE_URL` | `https://ollama.com` | Point at a self-hosted Ollama to use local models |
| `SEED_DEFAULT_MODEL` | unset | Model preselected in Chat |
| `SEED_PROVIDER_TIMEOUT_SECONDS` | `120` | Per-request provider timeout |
| `SEED_MAX_CONCURRENT_RUNS` | `2` | Concurrent agent runs |
| `SEED_RUN_MAX_STEPS` / `SEED_RUN_MAX_RUNTIME_SECONDS` / `SEED_RUN_MAX_TOTAL_TOKENS` | `8` / `300` / `200000` | Per-run limits |
| `SEED_WORKSPACE_ROOT` | `/tmp/seed-workspaces` | Per-run workspace dirs (ephemeral until M6) |

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
