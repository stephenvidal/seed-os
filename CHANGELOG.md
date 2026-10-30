# Changelog

All notable changes. Format: Keep a Changelog; versions follow the milestones.

## [Unreleased]
### Fixed
- HTML answers that were not fenced or a whole page showed as an empty answer;
  they now render (D-020). The per-step output cap is 16,384 tokens, up from 4,096.

### Changed
- `list_files` says "No such directory" for a path that does not exist, and that
  a path is a file when it is one.
- Tools page (M8): usage is a stacked list that reads at 390 px (the table's headings
  ran together and "offered in" was cut off); each tool's time and output limits show
  on its row; `GET /api/v1/tools` usage gains `reasons`, each tool's three commonest
  error messages, so a failure rate can be read.

### Added
- Notification bell (M8): in the top bar on every page, with the unread count;
  opening one marks it read and goes to its task (or to Schedules); mark all read.
  It checks every 30 seconds.
- Notifications (M8, D-030): `/api/v1/notifications` (list with unread count, mark
  read, mark all read); written when a task you started on its own completes or
  fails, when a task waits for your approval, and when a schedule skips a run;
  migration 0017.
- Schedules page (M8): list, create, edit, pause or resume, run now and delete schedules;
  the time zone defaults to the browser's.
- Schedules (M8, D-029): `/api/v1/schedules` (list, create, replace, delete, run
  now); a saved task starting every N minutes or daily at a time in a timezone,
  started by the workers exactly once per due time; migration 0016; new
  dependency `tzdata`.
- Tools & Skills (M8, D-028): the page lists the worker's tools with permission,
  approval policy, limits, arguments and where each is offered, and how often each
  was used and failed, from recorded results. `GET /api/v1/tools`; migration 0015
  (index on tool results).
- Delegation in the Inspector and Command Center (M7): the Inspector lists a
  task's hand-offs and links agent tasks to their parent and back; the overview
  gains `agents` and the Command Center an Agent activity panel; tasks in
  progress name their agent.
- Lasting delegation links (M7): a finished turn lists its agents' tasks under
  "Show activity"; an agent's task page names the agent and links back to the task
  that handed it over; a task's page lists the agent tasks it handed work to.
  Moving between tasks no longer carries the earlier task's events over.
- Parallel delegation (M7, D-026): the delegate calls of one step start
  together, up to `SEED_DELEGATION_MAX_PARALLEL` working at once; at most
  `SEED_DELEGATION_MAX_PER_TASK` per run, the rest refused with the reason;
  `SEED_DELEGATION_MAX_DEPTH` levels of hand-off. A task that ends cancels the
  agents it still has working. A worker process runs `SEED_WORKER_CONCURRENCY`
  tasks at once. The chat lists every agent working on a turn. Migration 0014
  (`delegation_depth`).
- Delegation (M7, D-025): the `delegate` tool hands a sub-task to one of the
  owner's agents as a task of its own (agent's instructions, model and tools,
  same workspace and project); the turn waits durably and resumes with the
  report however the agent's task ends; canceling cascades. Task fields
  `parent_task_id`, `agent`, `awaiting_delegation`; overview `delegating`;
  conversation `last_state` `delegating`; events `delegated`,
  `delegation_finished`, `delegation_refused`; migration 0013.
- Agent definitions (M7, D-024): the Agents page and `/api/v1/agents` (list,
  create, replace, delete); name, purpose, instructions, model and allowed tools;
  starter Researcher, Coder and Reviewer given once per owner; migration 0012.
  Nothing delegates to them yet.
- Tasks in projects (M6, D-023): `project_id` on `POST /api/v1/tasks` and as a
  filter on `GET /api/v1/tasks`; such a task gets the project's instructions,
  memory and knowledge tools. A Project picker on Tasks, a Tasks panel on the
  project page, the project on the task page, `tasks` on projects.
- Session summaries (M6, D-022): completed turns older than the chat context
  window reach the model as a rolling summary instead of being dropped; the chat
  marks where the summary starts. `summary_of` and `summary` on tasks, events
  `context_summarized` and `summary_failed`; migration 0011.
- Chat links to the files an answer saved (D-021): each appears under the answer
  and opens in a dialog with the same viewer as Studio (sandboxed preview, Source
  switch, Phone / Desktop frame), with a link on to Studio.
- Project knowledge (M6, D-021): text documents on a project's page, split into
  passages and indexed with Postgres full-text search; the `search_knowledge` tool
  in the project's turns. API `/api/v1/projects/{id}/documents`, `documents` on
  projects; migration 0010. nginx accepts request bodies up to 2 MiB.
- Rendered output (D-019): chat answers, task results and Studio files show
  Markdown, tables and HTML rendered first, with a Rendered / Source switch.
  Fenced `html`, `svg` and `markdown` blocks and whole-page HTML answers appear in a
  sandboxed frame (no scripts, no network) that opens at the viewer's device width,
  with a Phone / Desktop switch. Studio's HTML preview starts on open and uses the
  same frame; Markdown files render. The system prompt asks for responsive HTML.
- Project memory (M6, D-018): the `remember` tool (in a project's turns only)
  proposes a note; the owner approves, edits or rejects it on the project page,
  and can add, edit and delete notes. Approved notes are copied into each turn and
  added to the system prompt. API `/api/v1/projects/{id}/memories`,
  `proposed_memories` on projects; migration 0009.
- Projects (M6, D-017): `/projects` and `/projects/{id}` (name, instructions, the
  project's chats and files); new chats start in a project from its page; a chat's
  header moves it in or out. API `/api/v1/projects`, `PUT
  /api/v1/conversations/{id}/project`, `project_id` on starting a conversation and
  as a filter on conversations and artifacts; migration 0008. The worker adds the
  instructions a turn was sent with to the system prompt.
- Studio (M6, ADR-0015): `/studio` lists saved files by chat or task;
  `/studio/{id}` shows versions, text or images, downloads, and runs HTML as a
  sandboxed preview of the latest files. API `GET /api/v1/artifacts`,
  `/{id}`, `/{id}/versions/{n}/content`, `POST /{id}/preview`,
  `GET /api/v1/previews/{token}/{path}`; migration 0007. Task timelines note saved,
  skipped and restored files.
- Artifacts (M6, ADR-0014): after every run, each file it created, changed or
  deleted is saved as a version (migration 0006, `SEED_ARTIFACT_ROOT`, compose
  volume `artifacts`); an emptied workspace is refilled before the next run.
  Events `artifacts_saved`, `workspace_restored`, `artifacts_failed`; sandbox file
  ops `snapshot`, `read_bytes`, `write_bytes`.
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
### Fixed
- HTML answers that were not fenced or a whole page showed as an empty answer;
  they now render (D-020). The per-step output cap is 16,384 tokens, up from 4,096.

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
### Fixed
- HTML answers that were not fenced or a whole page showed as an empty answer;
  they now render (D-020). The per-step output cap is 16,384 tokens, up from 4,096.

### Added
- `sandbox` service: runs the agent's shell commands and task file operations in a
  container with no network, no secrets and dropped capabilities; each task as
  its own user, with time, memory, CPU, process, file-size and output limits
  (ADR-0010).
- `run_command` tool for tasks; task file tools go through the sandbox.
- CI runs the per-task user tests as root and checks the sandbox container's
  isolation (`backend/scripts/sandbox_smoke.py`).

## M3 Users, sessions and CSRF (increment 4)
### Fixed
- HTML answers that were not fenced or a whole page showed as an empty answer;
  they now render (D-020). The per-step output cap is 16,384 tokens, up from 4,096.

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
### Fixed
- HTML answers that were not fenced or a whole page showed as an empty answer;
  they now render (D-020). The per-step output cap is 16,384 tokens, up from 4,096.

### Added
- `GET /api/v1/tasks/{id}/stream`: live task events over SSE, resuming after
  `Last-Event-ID` (ADR-0003).
- Tasks screen: task list, new-task form (idempotency key per submission), task
  detail with live timeline, cancel and retry.
### Changed
- Command Center lists SEED Core and SEED Flow as built.

## M3 Durable tasks (increment 1)
### Fixed
- HTML answers that were not fenced or a whole page showed as an empty answer;
  they now render (D-020). The per-step output cap is 16,384 tokens, up from 4,096.

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
### Fixed
- HTML answers that were not fenced or a whole page showed as an empty answer;
  they now render (D-020). The per-step output cap is 16,384 tokens, up from 4,096.

### Added
- Provider interface with typed errors; Ollama adapter (chat, NDJSON streaming,
  tool calls, model list).
- Typed tool registry and per-run workspace file tools (list/read/write).
- Bounded agent loop (steps, time, tokens, tool calls, retries, cancellation).
- `GET /api/v1/models`, `POST /api/v1/runs` (SSE with keepalives).
- Chat page: model picker, streaming answer, expandable tool activity, usage.

## M0/M1, Iteration 1
### Fixed
- HTML answers that were not fenced or a whole page showed as an empty answer;
  they now render (D-020). The per-step output cap is 16,384 tokens, up from 4,096.

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
