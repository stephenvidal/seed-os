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
- **Command Center (M5):** live from the task store, refreshed every 10 s:
  counts of running, queued and waiting tasks and of tasks completed or failed in
  the last 24 hours; what needs you (commands waiting for approval, recent
  failures), what is in progress, what finished recently, and tokens by model.
  Spend is not shown because no model prices are configured. Also host telemetry
  (memory, load, uptime, API RSS) and an honest component status list.
- **Settings:** theme selection, account, system details.
- **Chat (M4):** saved conversations, listed newest first. Each message you send
  runs as a task with the conversation so far, so the answer keeps coming if you
  leave the page, survives a restart, and its steps show up under Tasks. The
  reply streams live with its tool calls, and finished answers render as
  Markdown (no raw HTML). All turns of a conversation share one workspace, so a
  later message can use files an earlier one made. One message at a time: Stop
  cancels the answer in progress, and a failed or stopped last answer can be
  tried again. The model can be changed between messages. Conversations can be
  renamed, deleted (after a confirm, and not while a message is being answered)
  and searched by title, message or answer. Any message can be edited, and any
  answer regenerated; each becomes a new version, the old ones are kept, and the
  arrows under a message switch between its versions (ADR-0013).
- **Projects (M6):** group chats under a name with instructions SEED follows in
  every one of them (D-017). A project's page edits its name and instructions and
  lists its chats and the files they saved; "New chat" starts one in the project,
  and a chat's header moves it in or out. Each message copies the instructions
  when it is sent, so a change applies from the next message. Deleting a project
  keeps its chats.
- **Project memory (M6):** short notes SEED is given in every chat of a project
  (D-018). In a project's chats the agent has a `remember` tool that only proposes
  a note; it waits on the project page ("Waiting for you") until you approve, edit
  or reject it, and the projects list and the chat header say when proposals wait.
  You can add, edit and delete notes yourself. Each message copies the approved
  notes, newest first, up to 4,000 characters.
- **Project knowledge (M6):** text documents (.md, .markdown, .txt, .csv, .json,
  up to 256 KiB each) added on a project's page (D-021). In the project's chats the
  agent has a `search_knowledge` tool that returns the five best matching passages
  (Postgres full-text search, English stemming; "quoted phrases" and -excluded
  words work). Documents are split into passages of up to 1,500 characters.
- **Approvals (M4):** before the agent runs a shell command, the task stops as
  "needs you" and Chat and the task page show the exact command with Approve and
  Deny. The run carries on from where it stopped; a denied command is reported
  to the model and never runs. The waiting chat is marked in the conversation
  list. Which tools wait is `SEED_APPROVAL_REQUIRED_TOOLS` (ADR-0012).
- **Saved files (M6):** after every answer or task run, each file it created,
  changed or deleted in its workspace is saved as a new version, kept on a
  persistent volume. If the sandbox restarts and a workspace comes back empty,
  the next run puts the saved files back first (ADR-0014).
- **Studio (M6):** every saved file, grouped by the chat or task that made it.
  A file's page shows each version (who made it, size, a link to its run in the
  Inspector), its text or image, and a download. HTML can be run as a preview of
  the latest files, in a sandbox with no access to your session, its storage, the
  page around it or the network (ADR-0015). Task timelines say which files were
  saved, skipped or put back.
- **Rendered output:** answers, task results and Studio files show Markdown,
  tables and HTML rendered, with a Rendered / Source switch on each answer, block
  and file. HTML (a fenced `html`/`svg` block or a whole-page answer) runs in a
  sandboxed frame with no scripts and no network, in the phone layout on a phone and
  the desktop layout otherwise, with a switch for the other. Studio's HTML preview
  starts when the file opens (D-019).
- **Tasks (M3):** create a task, then follow its timeline live: steps, tool calls
  and lifecycle notes (attempts, resumes, retries, interruptions). Tasks run in
  the worker, so they keep going when the page is closed; the timeline is rebuilt
  from stored events on reload and resumes after a dropped connection. Cancel
  and retry appear only in the states that allow them. Needs `SEED_DATABASE_URL`;
  without it the page says so. Task agents can also run shell commands
  (`run_command`) in the sandbox: no network, time/memory/CPU/process limits,
  each task in its own workspace as its own user (ADR-0010).
- **Inspector (M5):** pick any task or chat message and see how it actually
  ran, folded from its stored events: attempts (worker, resumed step, how each
  ended), model steps (time, tokens, finish reason, provider retries), tool
  calls (arguments, result, time, approval), checkpoints, and the raw event log
  (streamed text chunks are counted, not listed). A running task refreshes every
  3 s. Model reasoning is never stored, so it is never shown.
- Agents, Projects, Studio, Models, Tools: page structure with empty states
  naming the milestone that delivers each.

## API (as built)
| Method | Path | Auth | Result |
|---|---|---|---|
| GET | `/healthz` | none | `{status, version}` |
| POST | `/api/v1/auth/login` | none | `{username, role}` + `seed_session` (HttpOnly) and `seed_csrf` cookies; 401 `invalid_credentials`, 429 `rate_limited` (per username), 503 `auth_not_configured` (no database or no users), 422 `invalid_request` |
| POST | `/api/v1/auth/logout` | session | 204; revokes the session server-side and clears both cookies |
| GET | `/api/v1/auth/me` | session | `{username, role}`; 401 `unauthenticated` |
| GET | `/api/v1/system` | session | host/process telemetry |
| GET | `/api/v1/models` | admin | `{provider, default_model, models[]}` from the provider; 503 `provider_not_configured`, 502 `provider_<kind>` |
| POST | `/api/v1/conversations` | admin | `{model, prompt, project_id?}`, optional `Idempotency-Key` → 201 `{conversation, turns[]}` with the first message queued as a task; 200 with the original on a repeated key; 409 `idempotency_conflict`; 503 `provider_not_configured`; 404 `project_not_found` |
| GET | `/api/v1/conversations` | admin | The caller's conversations, most recently active first: `{id, title, model, turns, last_state, …}`; `?limit=1..200`; `?q=` (1–200 chars) keeps those whose title, messages or answers contain it, ignoring case; `?project_id=` keeps one project's |
| GET | `/api/v1/conversations/{id}` | admin | `{conversation, turns[]}`: the shown path, each turn a task (prompt, state, `result_text`, usage, `turn`) with `versions` (ids of that message's versions, oldest first); 404 `not_found` (also for another user's conversation) |
| PATCH | `/api/v1/conversations/{id}` | admin | `{title}` (whitespace collapsed, 1–80 chars) → the conversation; its turns take the new title; 404 `not_found`; 422 |
| POST | `/api/v1/conversations/{id}/turns/{turn_id}/versions` | admin | `{prompt?, model?}`, optional `Idempotency-Key` → 201 task: a new version of that message (edited with `prompt`, asked again without), carrying the turns above it; it ends the shown path and older versions are kept; 200 on a repeated key; 409 `turn_in_progress` while any turn is unfinished; 404 `not_found` |
| PUT | `/api/v1/conversations/{id}/shown` | admin | `{turn_id}` → `{conversation, turns[]}` showing that version and its newest replies; 409 `turn_in_progress` while a turn is unfinished; 404 `not_found` |
| PUT | `/api/v1/conversations/{id}/project` | admin | `{project_id}` (or `null` to take it out) → the conversation; messages sent from now on get that project's instructions; 404 `not_found`, `project_not_found` |
| GET | `/api/v1/projects` | admin | The caller's projects, most recently changed first: `{id, name, instructions, conversations, proposed_memories, documents, …}` |
| POST | `/api/v1/projects` | admin | `{name, instructions?}` (name: whitespace collapsed, 1–80 chars; instructions up to 20,000) → 201 project; 422 |
| GET | `/api/v1/projects/{id}` | admin | The project; 404 `not_found` (also for another user's) |
| PATCH | `/api/v1/projects/{id}` | admin | `{name?, instructions?}` → the project; 404 `not_found`; 422 |
| DELETE | `/api/v1/projects/{id}` | admin | 204; its conversations are kept and leave the project; 404 `not_found` |
| GET | `/api/v1/projects/{id}/memories` | admin | The project's notes, proposals first, then approved, newest first: `{id, content, status, created_by, source_task_id, source_conversation_id, approved_by, approved_at, …}`; `?status=proposed\|approved`; 404 `not_found` |
| POST | `/api/v1/projects/{id}/memories` | admin | `{content}` (whitespace collapsed, 1–500 chars) → 201 note, approved as written; 404; 422 |
| PATCH | `/api/v1/projects/{id}/memories/{memory_id}` | admin | `{content?, approve?}` → the note; `approve: true` makes a proposal reach the model; 404 `not_found` |
| GET | `/api/v1/projects/{id}/documents` | admin | The project's knowledge documents by name: `{id, name, chars, chunks, created_by, created_at}`; 404 `not_found` |
| POST | `/api/v1/projects/{id}/documents` | admin | `{name, content}` (a file name ending .md, .markdown, .txt, .csv or .json; text up to 256 KiB, no NUL) → 201 document; 409 `name_taken`; 404; 422 |
| DELETE | `/api/v1/projects/{id}/documents/{document_id}` | admin | 204; removes the document and its passages; 404 `not_found` |
| DELETE | `/api/v1/projects/{id}/memories/{memory_id}` | admin | 204; deletes a note or rejects a proposal; 404 `not_found` |
| DELETE | `/api/v1/conversations/{id}` | admin | 204; removes the conversation, its turns and their events; 409 `turn_in_progress` while a turn is queued, running or waiting; 404 `not_found` |
| POST | `/api/v1/conversations/{id}/turns` | admin | `{prompt, model?}`, optional `Idempotency-Key` → 201 task continuing the shown path, carrying its completed turns as context; `model` switches the conversation's model; 409 `turn_in_progress` while a turn is unfinished; 404 `not_found` |
| POST | `/api/v1/tasks` | admin | `{model, prompt, title?}`, optional `Idempotency-Key` header → 201 task (`queued`); 200 with the existing task on a repeated key; 409 `idempotency_conflict`; 503 `provider_not_configured` |
| GET | `/api/v1/overview` | admin | `?hours=1..720` (default 24) → `{window_hours, generated_at, counts, attention[], active[], recent[], usage[]}`: queued/running/waiting now; completed/failed/canceled, recent work and per-model tokens for tasks finished in the window; `attention` is every waiting task then failures in the window (10 max), `active` running then queued (10 max), `recent` 5 max; all users' tasks |
| GET | `/api/v1/artifacts` | admin | Saved files, most recently changed first: `{id, path, media_type, conversation_id, source_title, task_id, versions, latest{version, task_id, size, deleted, created_at}, …}`; `?conversation_id=`, `?project_id=`, `?limit=1..500` |
| GET | `/api/v1/artifacts/{id}` | admin | `{artifact, versions[]}` (newest first); 404 `not_found` |
| GET | `/api/v1/artifacts/{id}/versions/{n}/content` | admin | The version's bytes, sandboxed by CSP (never runs); `?download=true` as an attachment; 410 `deleted`; 503 `artifacts_not_configured` without `SEED_ARTIFACT_ROOT` |
| POST | `/api/v1/artifacts/{id}/preview` | admin | 201 `{url, expires_in}`: a link, valid 1 h, that serves the latest saved files of the file's workspace; 410 `deleted` |
| GET | `/api/v1/previews/{token}/{path}` | link | A previewed file, sandboxed (scripts run; no same-origin access, no network); 404 for an unknown path or an expired link |
| GET | `/api/v1/tasks` | admin | Newest first; `?state=queued\|running\|waiting\|completed\|failed\|canceled`, `?limit=1..100` |
| GET | `/api/v1/tasks/{id}` | admin | Task: state, attempt, termination, error, result, usage, `last_seq`, `resumable_from_step`, `awaiting_approval` (`{id, name, arguments}` while `waiting`), and for a chat turn `conversation_id` and `turn`; 404 `not_found` |
| GET | `/api/v1/tasks/{id}/events` | admin | `{events[], last_seq, state}`; `?after=<seq>&limit=` for incremental reads. Events: `task_created`, `attempt_started`, run events, `checkpoint_saved` (`{steps, pending}`), `artifacts_saved` (`{saved[{path, version, deleted}], skipped[{path, reason}], truncated}`), `workspace_restored` (`{files}`), `artifacts_failed` (`{stage, error}`), `cancel_requested`, `task_requeued`, `task_released`, `lease_expired` |
| GET | `/api/v1/tasks/{id}/stream` | admin | `text/event-stream`: each stored event as `id: <seq>` + JSON data, then `event: end` once the task is finished. Resumes after `Last-Event-ID` (or `?after=`); 404 `not_found` |
| POST | `/api/v1/tasks/{id}/cancel` | admin | Queued or waiting → `canceled` at once; running → stops at the worker's next heartbeat; 409 `not_cancelable` |
| POST | `/api/v1/tasks/{id}/decision` | admin | `{call_id, approve}` for the call in the task's `awaiting_approval` → task `queued` to resume; event `approval_decided`; audited as `tool_approved`/`tool_denied` with the tool and its arguments; 409 `not_waiting` |
| POST | `/api/v1/tasks/{id}/retry` | admin | Failed/canceled → `queued` as a fresh run; 409 `not_retryable` (also for a chat turn while another turn of its conversation is unfinished) |

Every authenticated request other than GET/HEAD/OPTIONS must send the `seed_csrf`
cookie's value in `X-CSRF-Token`, or it gets 403 `csrf_failed` (ADR-0009). Sign-ins,
sign-outs, user changes, new, renamed, moved and deleted conversations, new,
changed and deleted projects, added, changed, approved and deleted memory notes, added and deleted documents, task
create/cancel/retry (chat turns included) and approval decisions are recorded in
`audit_log`.

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
| `SEED_APPROVAL_REQUIRED_TOOLS` | `["run_command"]` | JSON list of tools that wait for a person's approval before each call; `[]` turns approvals off |
| `SEED_WORKSPACE_ROOT` | `/tmp/seed-workspaces` | Worker without a sandbox: workspace dirs (one per task, or per conversation for chat); scratch space, kept as artifacts when `SEED_ARTIFACT_ROOT` is set |
| `SEED_ARTIFACT_ROOT` | unset | Where saved task files live (compose: the `artifacts` volume; the worker writes it, the API reads it). Unset on the worker: files are not saved; on the API: Studio lists files but cannot show them (ADR-0014) |
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
