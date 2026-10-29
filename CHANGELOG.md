# Changelog

All notable changes. Format: Keep a Changelog; versions follow the milestones.

## [Unreleased]
### Added
- Execution Inspector (M5 step 2): `/inspector` lists tasks; `/inspector/{id}`
  shows attempts, model steps, tool calls, checkpoints, totals and the event log
  for one task, from its stored events (D-013).
- Event `checkpoint_saved` (`{steps, pending}`), logged each time a run saves
  where a retry would resume.
- Command Center shows live work (M5 step 1): `GET /api/v1/overview` with task
  counts, what needs attention, what is running and recently completed, and
  tokens by model; the page refreshes every 10 s (D-012).
- Approvals: shell commands wait for a person. The task shows as "needs you"
  with the exact command and Approve/Deny in Chat and on the task page; the run
  resumes from its checkpoint after the decision (ADR-0012).
- `POST /api/v1/tasks/{id}/decision`, task state `waiting`, events
  `approval_requested`/`approval_decided`, audit actions `tool_approved`/`tool_denied`.
- `SEED_APPROVAL_REQUIRED_TOOLS` (default `["run_command"]`).
- Rename, delete and search conversations: `PATCH`/`DELETE
  /api/v1/conversations/{id}`, `GET /api/v1/conversations?q=`, a search box in
  the conversation list and rename/delete in the conversation header (D-010).
  Audit actions `conversation_renamed`/`conversation_deleted`.
- Message versions (ADR-0013): `POST /api/v1/conversations/{id}/turns/{turn_id}/versions`
  edits or regenerates any message as a new version, keeping the old ones;
  `PUT /api/v1/conversations/{id}/shown` switches versions; turns carry `versions`.
  Migration 0005 (`tasks.parent_id`, `conversations.head_id`). In Chat: Edit
  under each message, Regenerate under each answer, and version arrows.
### Changed
- A waiting task cancels at once; a chat turn waiting for approval blocks the
  next message like any unfinished turn.
### Fixed
- A run that spent its step limit on tool calls ended with no answer
  ("Stopped: step limit reached"). The last allowed step now gets no tools and is
  told to answer with what it has; it ends `max_steps` only if the model still
  asks for a tool. Found by the owner's manual tests 9 and 10.

## M4 Saved chats (increment 6)
### Added
- Saved conversations (`/api/v1/conversations`). Each message runs as a task
  carrying the earlier completed turns, so replies survive leaving the page and
  restarts, and appear under Tasks (ADR-0011).
- One workspace per conversation: later messages see files earlier ones made.
- Chat page: conversation list, live replies with tool activity, Markdown
  answers (raw HTML is not rendered), Stop, Try again, model switch per message.
- `SEED_CHAT_CONTEXT_TURNS` (default 20).
### Changed
- A chat turn cannot be retried while another turn of its conversation is
  unfinished (409 `not_retryable`).
### Removed
- `POST /api/v1/runs` (in-request runs that stopped when the page closed) and
  `SEED_MAX_CONCURRENT_RUNS`.

## M3 Sandbox (increment 5)
### Added
- `sandbox` service: runs the agent's shell commands and task file operations in a
  container with no network, no secrets and dropped capabilities; each task as
  its own user, with time, memory, CPU, process, file-size and output limits
  (ADR-0010).
- `run_command` tool for tasks; task file tools go through the sandbox.
- CI runs the per-task user tests as root and checks the sandbox container's
  isolation (`backend/scripts/sandbox_smoke.py`).

## M3 Users, sessions and CSRF (increment 4)
### Added
- Users in Postgres with argon2id passwords; the first admin is created from
  `SEED_ADMIN_PASSWORD` when no users exist (ADR-0009).
- Revocable server-side sessions; sign-out revokes, password change and
  disabling a user end all their sessions.
- CSRF token per session, required in `X-CSRF-Token` on state-changing requests.
- `audit_log` of sign-ins, sign-outs, user management and task actions.
- `python -m seed_api.users`: add, set-password, disable, enable,
  revoke-sessions, list.
### Changed
- Sign-in rate limit is per username and stored in Postgres (was in-memory per
  client address). Sign-in needs `SEED_DATABASE_URL`.
- `SEED_SESSION_SECRET` is no longer used; the deploy check no longer requires it.
### Fixed
- Signing out now returns to the sign-in page (the app stayed on screen until a
  reload).
- A queued task's cancel note now appears in the live timeline without a reload.

## M3 Durable tasks (increment 2)
### Added
- `GET /api/v1/tasks/{id}/stream`: live task events over SSE, resuming after
  `Last-Event-ID` (ADR-0003).
- Tasks screen: task list, new-task form (idempotency key per submission), task
  detail with live timeline, cancel and retry.
### Changed
- Command Center lists SEED Core and SEED Flow as built.

## M3 Durable tasks (increment 1)
### Added
- Postgres (psycopg 3) with forward-only SQL migrations.
- Durable tasks: state machine, leased workers with heartbeats and fenced writes,
  step checkpoints and resume after a worker crash, dead-letter, graceful
  shutdown, per-task event log (ADR-0008).
- Worker process `python -m seed_api.flow.worker`; compose gains `db` and `worker`.
- Tasks API: create (idempotency key), list, detail, events, cancel, retry.
### Changed
- Cancelling a run now interrupts a provider request that is in flight.

## M2 Core agent runtime
### Added
- Provider interface with typed errors; Ollama adapter (chat, NDJSON streaming,
  tool calls, model list).
- Typed tool registry and per-run workspace file tools (list/read/write).
- Bounded agent loop (steps, time, tokens, tool calls, retries, cancellation).
- `GET /api/v1/models`, `POST /api/v1/runs` (SSE with keepalives).
- Chat page: model picker, streaming answer, expandable tool activity, usage.

## M0/M1, Iteration 1
### Added
- Directive v1.1 (product definition) and docs set: vision, requirements,
  architecture, design system, security, deployment, model strategy, testing,
  roadmap, ADRs 0001–0005.
- SEED API: health, bootstrap sign-in with signed session cookie, server-side
  role guard, login rate limit, typed errors, real host telemetry.
- SEED Workspace: design tokens (light/dark/system), app shell, collapsible
  sidebar and mobile drawer, command palette, keyboard navigation, Command
  Center with live telemetry, Settings, honest empty states for unbuilt areas.
- Docker Compose stack (api + web/nginx with security headers).
- CI and build-and-deploy workflows for the self-hosted golden-eye runner,
  production compose file (adapted from dustline; deploy off by default).
