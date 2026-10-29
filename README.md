# SEED OS

**From intention to execution.** A self-hostable, model-agnostic autonomous agent
platform: describe an outcome, and SEED plans, executes, verifies, and delivers
it — with full visibility and control.

| | |
|---|---|
| Directive | v1.1 — [DIRECTIVE.md](DIRECTIVE.md) |
| Current milestone | M4 Integrated native chat (see [progress](docs/progress.md)) |
| Stack | React + Vite + TS + Tailwind · Python + FastAPI · Docker Compose |

## What works today
- **Sign-in** as the bootstrap administrator (from environment), with signed
  HttpOnly session cookie, server-side role checks, and failed-login rate limiting.
- **SEED Workspace shell:** collapsible sidebar, mobile drawer, command palette
  (`Ctrl/⌘+K`), `G`-then-key navigation, light/dark/system theme with persistence.
- **Command Center** with live host telemetry from the API (memory, load, uptime,
  API RSS) and an honest component status list.
- **Settings:** theme selection, account, system details.
- **Chat (M4):** saved conversations, listed newest first. Each message you send
  runs as a task with the conversation so far, so the answer keeps coming if you
  leave the page, survives a restart, and its steps show up under Tasks. The
  reply streams live with its tool calls, and finished answers render as
  Markdown (no raw HTML). All turns of a conversation share one workspace, so a
  later message can use files an earlier one made. One message at a time: Stop
  cancels the answer in progress, and a failed or stopped last answer can be
  tried again. The model can be changed between messages.
- **Tasks (M3):** create a task, then follow its timeline live: steps, tool calls
  and lifecycle notes (attempts, resumes, retries, interruptions). Tasks run in
  the worker, so they keep going when the page is closed; the timeline is rebuilt
  from stored events on reload and resumes after a dropped connection. Cancel
  and retry appear only in the states that allow them. Needs `SEED_DATABASE_URL`;
  without it the page says so. Task agents can also run shell commands
  (`run_command`) in the sandbox: no network, time/memory/CPU/process limits,
  each task in its own workspace as its own user (ADR-0010).
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
| POST | `/api/v1/conversations` | admin | `{model, prompt}`, optional `Idempotency-Key` → 201 `{conversation, turns[]}` with the first message queued as a task; 200 with the original on a repeated key; 409 `idempotency_conflict`; 503 `provider_not_configured` |
| GET | `/api/v1/conversations` | admin | The caller's conversations, most recently active first: `{id, title, model, turns, last_state, …}`; `?limit=1..200` |
| GET | `/api/v1/conversations/{id}` | admin | `{conversation, turns[]}`, each turn a task (prompt, state, `result_text`, usage, `turn`); 404 `not_found` (also for another user's conversation) |
| POST | `/api/v1/conversations/{id}/turns` | admin | `{prompt, model?}`, optional `Idempotency-Key` → 201 task carrying the earlier completed turns as context; `model` switches the conversation's model; 409 `turn_in_progress` while a turn is unfinished; 404 `not_found` |
| POST | `/api/v1/tasks` | admin | `{model, prompt, title?}`, optional `Idempotency-Key` header → 201 task (`queued`); 200 with the existing task on a repeated key; 409 `idempotency_conflict`; 503 `provider_not_configured` |
| GET | `/api/v1/tasks` | admin | Newest first; `?state=queued\|running\|completed\|failed\|canceled`, `?limit=1..100` |
| GET | `/api/v1/tasks/{id}` | admin | Task: state, attempt, termination, error, result, usage, `last_seq`, `resumable_from_step`, and for a chat turn `conversation_id` and `turn`; 404 `not_found` |
| GET | `/api/v1/tasks/{id}/events` | admin | `{events[], last_seq, state}`; `?after=<seq>&limit=` for incremental reads. Events: `task_created`, `attempt_started`, run events, `cancel_requested`, `task_requeued`, `task_released`, `lease_expired` |
| GET | `/api/v1/tasks/{id}/stream` | admin | `text/event-stream`: each stored event as `id: <seq>` + JSON data, then `event: end` once the task is finished. Resumes after `Last-Event-ID` (or `?after=`); 404 `not_found` |
| POST | `/api/v1/tasks/{id}/cancel` | admin | Queued → `canceled` at once; running → stops at the worker's next heartbeat; 409 `not_cancelable` |
| POST | `/api/v1/tasks/{id}/retry` | admin | Failed/canceled → `queued` as a fresh run; 409 `not_retryable` (also for a chat turn while another turn of its conversation is unfinished) |

Every authenticated request other than GET/HEAD/OPTIONS must send the `seed_csrf`
cookie's value in `X-CSRF-Token`, or it gets 403 `csrf_failed` (ADR-0009). Sign-ins,
sign-outs, user changes, new conversations and task create/cancel/retry (chat turns
included) are recorded in `audit_log`.

Without `SEED_DATABASE_URL` there is no sign-in (503 `auth_not_configured`), so
every protected route answers that.
Tasks, chat turns included, are executed by the worker (`python -m seed_api.flow.worker`),
not by the API; follow a turn's reply on `/api/v1/tasks/{id}/stream`.

Errors are always `{"error": {"code", "message"}}`. OpenAPI at `/api/docs`.

## Run
**Compose:** `cp .env.example .env`, set `SEED_ADMIN_PASSWORD` and
`SEED_POSTGRES_PASSWORD`, then
`docker compose up -d --build` → http://localhost:8080. This starts Postgres, the
API, one worker, the sandbox and the web server.

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
| `SEED_OLLAMA_API_KEY` | unset | Ollama Cloud key; unset disables Chat and new tasks (typed 503) |
| `SEED_OLLAMA_BASE_URL` | `https://ollama.com` | Point at a self-hosted Ollama to use local models |
| `SEED_DEFAULT_MODEL` | unset | Model preselected in Chat |
| `SEED_PROVIDER_TIMEOUT_SECONDS` | `120` | Per-request provider timeout |
| `SEED_RUN_MAX_STEPS` / `SEED_RUN_MAX_RUNTIME_SECONDS` / `SEED_RUN_MAX_TOTAL_TOKENS` | `8` / `300` / `200000` | Per-run limits (each task attempt, chat turns included). The last allowed step gets no tools and is told to answer with what it has |
| `SEED_CHAT_CONTEXT_TURNS` | `20` | How many earlier completed turns a new chat message carries |
| `SEED_WORKSPACE_ROOT` | `/tmp/seed-workspaces` | Worker without a sandbox: workspace dirs (one per task, or per conversation for chat; ephemeral until M6) |
| `SEED_DATABASE_URL` | unset | Postgres URL (`postgresql://user:pass@host/db`); unset disables sign-in, tasks and chat. Compose builds it from `SEED_POSTGRES_PASSWORD` |
| `SEED_TASK_MAX_ATTEMPTS` | `3` | Attempts per task (and per retry) before it is dead-lettered as `failed/abandoned` |
| `SEED_WORKER_LEASE_SECONDS` | `30` | Worker lease; renewed every third of it. A crashed worker's task is resumed after this |
| `SEED_WORKER_POLL_SECONDS` | `2` | Idle worker poll interval |
| `SEED_SANDBOX_URL` | unset | Worker: sandbox address (compose sets `http://sandbox:8100`). Unset: tasks get local file tools and no commands |
| `SEED_SANDBOX_COMMAND_TIMEOUT_SECONDS` | `60` | Longest a command may run (the model may ask for less) |
| `SEED_SANDBOX_MEMORY_MB` / `SEED_SANDBOX_CPU_SECONDS` / `SEED_SANDBOX_MAX_PROCESSES` / `SEED_SANDBOX_MAX_FILE_MB` | `512` / `60` / `64` / `64` | Per-command limits, set on the sandbox service |
| `SEED_SANDBOX_ROOT` | `/workspaces` | Sandbox: where task workspaces live |
| `SEED_SANDBOX_ISOLATE_USERS` | `true` | Sandbox: run each task as its own user (needs root in the container; `false` only for tests) |

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
