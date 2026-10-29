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
- **Chat (M2):** pick a model from the configured provider (Ollama),
  send a request, and watch the agent stream its answer and its tool calls. The
  agent has list/read/write file tools confined to a per-run workspace. Runs are
  bounded (steps, time, tokens) and **not saved**: leaving the page stops the run
  (durable runs are M3/M4).
- **Tasks (M3):** create a task, then follow its timeline live: steps, tool calls
  and lifecycle notes (attempts, resumes, retries, interruptions). Tasks run in
  the worker, so they keep going when the page is closed; the timeline is rebuilt
  from stored events on reload and resumes after a dropped connection. Cancel
  and retry appear only in the states that allow them. Needs `SEED_DATABASE_URL`;
  without it the page says so.
- Agents, Projects, Studio, Inspector, Models, Tools: page structure with
  empty states naming the milestone that delivers each.

## API (as built)
| Method | Path | Auth | Result |
|---|---|---|---|
| GET | `/healthz` | none | `{status, version}` |
| POST | `/api/v1/auth/login` | none | `{username, role}` + `seed_session` (HttpOnly) and `seed_csrf` cookies; 401 `invalid_credentials`, 429 `rate_limited` (per username), 503 `auth_not_configured` (no database or no users), 422 `invalid_request` |
| POST | `/api/v1/auth/logout` | session | 204; revokes the session server-side and clears both cookies |
| GET | `/api/v1/auth/me` | session | `{username, role}`; 401 `unauthenticated` |
| GET | `/api/v1/system` | session | host/process telemetry |
| GET | `/api/v1/models` | admin | `{provider, default_model, models[]}` from the provider; 503 `provider_not_configured`, 502 `provider_<kind>` |
| POST | `/api/v1/runs` | admin | `{model, prompt, history[]}` → `text/event-stream` of run events (`run_id`, `run_started`, `step_started`, `text_delta`, `tool_call`, `tool_result`, `step_completed`, `provider_retry`, `run_finished`); 429 `busy` at the concurrency limit |
| POST | `/api/v1/tasks` | admin | `{model, prompt, title?}`, optional `Idempotency-Key` header → 201 task (`queued`); 200 with the existing task on a repeated key; 409 `idempotency_conflict`; 503 `provider_not_configured` |
| GET | `/api/v1/tasks` | admin | Newest first; `?state=queued\|running\|completed\|failed\|canceled`, `?limit=1..100` |
| GET | `/api/v1/tasks/{id}` | admin | Task: state, attempt, termination, error, result, usage, `last_seq`, `resumable_from_step`; 404 `not_found` |
| GET | `/api/v1/tasks/{id}/events` | admin | `{events[], last_seq, state}`; `?after=<seq>&limit=` for incremental reads. Events: `task_created`, `attempt_started`, run events, `cancel_requested`, `task_requeued`, `task_released`, `lease_expired` |
| GET | `/api/v1/tasks/{id}/stream` | admin | `text/event-stream`: each stored event as `id: <seq>` + JSON data, then `event: end` once the task is finished. Resumes after `Last-Event-ID` (or `?after=`); 404 `not_found` |
| POST | `/api/v1/tasks/{id}/cancel` | admin | Queued → `canceled` at once; running → stops at the worker's next heartbeat; 409 `not_cancelable` |
| POST | `/api/v1/tasks/{id}/retry` | admin | Failed/canceled → `queued` as a fresh run; 409 `not_retryable` |

Every authenticated request other than GET/HEAD/OPTIONS must send the `seed_csrf`
cookie's value in `X-CSRF-Token`, or it gets 403 `csrf_failed` (ADR-0009). Sign-ins,
sign-outs, user changes and task create/cancel/retry are recorded in `audit_log`.

Without `SEED_DATABASE_URL` there is no sign-in (503 `auth_not_configured`), so
every protected route answers that.
Tasks are executed by the worker (`python -m seed_api.flow.worker`), not by the API.

Errors are always `{"error": {"code", "message"}}`. OpenAPI at `/api/docs`.

## Run
**Compose:** `cp .env.example .env`, set `SEED_ADMIN_PASSWORD` and
`SEED_POSTGRES_PASSWORD`, then
`docker compose up -d --build` → http://localhost:8080. This starts Postgres, the
API, one worker and the web server.

**Development:**
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
SEED_DATABASE_URL=postgresql://… SEED_ADMIN_PASSWORD=… .venv/bin/uvicorn seed_api.main:app --reload   # :8000
.venv/bin/python -m seed_api.flow.worker    # needs SEED_DATABASE_URL and a provider key
cd frontend && npm ci && npm run dev                                   # :5173
```

**Users:** on first start, with no users yet, the API creates `SEED_ADMIN_USERNAME`
with `SEED_ADMIN_PASSWORD`. After that, manage users with the CLI (passwords are
prompted for, or read from stdin; 12+ characters):
```bash
python -m seed_api.users add alice          # also: set-password, disable, enable, revoke-sessions, list
docker compose exec api python -m seed_api.users list    # in the compose stack
```

## Configuration
| Variable | Default | Meaning |
|---|---|---|
| `SEED_ADMIN_USERNAME` | `admin` | First admin's username, created when no users exist |
| `SEED_ADMIN_PASSWORD` | unset | First admin's password; read only while no users exist. Change it later with `python -m seed_api.users set-password` |
| `SEED_SESSION_TTL_SECONDS` | `43200` | Session lifetime |
| `SEED_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `SEED_LOGIN_MAX_FAILURES` / `SEED_LOGIN_WINDOW_SECONDS` | `5` / `60` | Failed sign-ins per username per window before 429 |
| `SEED_CORS_ORIGINS` | `[]` | JSON list; only needed if the UI is served from another origin |
| `SEED_OLLAMA_API_KEY` | unset | Ollama Cloud key; unset disables Chat (typed 503) |
| `SEED_OLLAMA_BASE_URL` | `https://ollama.com` | Point at a self-hosted Ollama to use local models |
| `SEED_DEFAULT_MODEL` | unset | Model preselected in Chat |
| `SEED_PROVIDER_TIMEOUT_SECONDS` | `120` | Per-request provider timeout |
| `SEED_MAX_CONCURRENT_RUNS` | `2` | Concurrent agent runs |
| `SEED_RUN_MAX_STEPS` / `SEED_RUN_MAX_RUNTIME_SECONDS` / `SEED_RUN_MAX_TOTAL_TOKENS` | `8` / `300` / `200000` | Per-run limits |
| `SEED_WORKSPACE_ROOT` | `/tmp/seed-workspaces` | Per-run/per-task workspace dirs (ephemeral until M6) |
| `SEED_DATABASE_URL` | unset | Postgres URL (`postgresql://user:pass@host/db`); unset disables sign-in and tasks. Compose builds it from `SEED_POSTGRES_PASSWORD` |
| `SEED_TASK_MAX_ATTEMPTS` | `3` | Attempts per task (and per retry) before it is dead-lettered as `failed/abandoned` |
| `SEED_WORKER_LEASE_SECONDS` | `30` | Worker lease; renewed every third of it. A crashed worker's task is resumed after this |
| `SEED_WORKER_POLL_SECONDS` | `2` | Idle worker poll interval |

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
