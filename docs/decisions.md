# Decisions — SEED OS

Append-only. Newest at the bottom. Each entry: context, options considered,
choice, reason, consequences.

---

## D-001 — Repository initialized under Directive v1.0 with product scope deferred

**Date:** 2026-10-28

**Context:** Directive v1.0 fixes the execution environment (Claude Code), the
approach (greenfield, production-oriented, iterative delivery), and the
repository, but carries no product definition. Implementation had to either wait
for the product spec or start on the frame alone.

**Options:**
1. Wait for a full product spec before creating anything.
2. Create the repository and governing documents now, deferring product scope to
   Directive v1.1.
3. Infer a plausible product from the name "SEED OS" and build a scaffold.

**Choice:** Option 2.

**Reason:** The frame is fully specified by the directive as given; the product is
not. Building the repository and method now makes the next step concrete, while
option 3 would have manufactured requirements the owner never ratified.

**Consequences:** The repository contains method, not product. The first real
implementation iteration cannot start until Directive v1.1 defines scope,
non-goals, and the first milestone.

---

## Open questions

1. **What is SEED OS?** Purpose, target user, core capability set, and non-goals.
   Blocking Directive v1.1.
2. **Technology envelope** — language/runtime/storage. Not ratifiable before (1).
3. **Operational target** — local-first, self-hosted, or hosted. Not ratifiable
   before (1).

---

## D-002 — Directive v1.1 ratified; recommended stack adopted

**Date:** 2026-10-28

**Context:** The owner supplied the full SEED OS master directive in the project
thread, defining the product, its milestones, and a recommended architecture.
Open questions 1–3 above are answered by it.

**Options:** (1) adopt the recommended stack as-is; (2) re-evaluate every layer
before writing code; (3) adopt it, validating each layer with an ADR as it is
built.

**Choice:** Option 3.

**Reason:** The directive says "validate choices before implementation" and also
"do not substitute lengthy planning for implementation". ADRs 0001–0005 record
the validated choices for what Iteration 1 builds; later layers get ADRs when
they are built.

**Consequences:** Open questions 1–3 are closed. The product scope lives in
`docs/product-vision.md`, `docs/requirements.md`, `docs/roadmap.md`. CLAUDE.md's
"no toolchain ratified" note is superseded. Host reality differs from CLAUDE.md
(Node 22 / Python 3.13, not Node 20 / 3.14); code targets Python ≥ 3.12, Node ≥ 20.

## Open questions (as of Iteration 1)

4. **CSRF strategy** before any internet-facing deployment — double-submit token
   vs. Origin check. Due with M3 auth.
5. **Default model routing** (which provider/model per task class) — needs owner
   input on budget; due M2.
6. **Self-hosted CI runner** — hosted Actions minutes are blocked; verification is
   local until the owner decides.

---

## D-003 — Reuse dustline's CI/deploy pipeline

**Date:** 2026-10-28

**Context:** Hosted Actions minutes are blocked (open question 6). The owner said
seed-os may borrow deploy code from `stephenvidal/dustline`, which already runs CI
and deploys on a self-hosted runner on golden-eye, pushes to GHCR, and deploys to
a VPS over SSH behind a Cloudflare tunnel.

**Options:** (1) keep local-only verification; (2) write a new pipeline; (3)
adapt dustline's.

**Choice:** Option 3, with deploy gated off (`DEPLOY_ENABLED`) until the owner
prepares the runner, VPS folder, secrets, and tunnel route.

**Reason:** Proven on the same account and hosts; avoids a second design. Changes:
two images (api, web) instead of one, port 8091, required secrets checked before
deploy, SSH config files namespaced so they do not clobber dustline's on a shared
runner.

**Consequences:** Open question 6 becomes an owner action (register a runner for
seed-os). Production deploys stay off until explicitly enabled.

## D-004 — M3 starts with durable task execution; auth migration and sandbox follow

**Date:** 2026-10-28

**Context:** M3 ("Durable Task Infrastructure") also carries the Postgres-backed
auth (ADR-0004) and the sandbox. Together that is several reviewable diffs.

**Options:** one large M3 PR; split by concern.

**Choice:** Split. Increment 1: Postgres, task store, worker, Tasks API (ADR-0008).
Next: live task events over SSE with replay and the Tasks UI; then Postgres-backed
users and sessions with CSRF; then the sandbox and exec tool.

**Reason:** CLAUDE.md requires reviewable increments; task durability is what the
other parts build on.

**Consequences:** Until the next increments land, tasks are API-only (no UI) and
production has no database. Tasks answer 503 `database_not_configured` there.

## D-005 — Auth moves to Postgres; CSRF uses a session-bound token (closes open question 4)

**Date:** 2026-10-28

**Context:** Production has Postgres since PR #6, and Stephen confirmed the
multi-user auth and CSRF increment could start. Open question 4 asked for a CSRF
strategy (double-submit vs. Origin check).

**Options:** double-submit cookie; Origin check alone; synchronizer token stored
with a server-side session.

**Choice:** Server-side sessions with a synchronizer CSRF token, argon2 users,
audit log and a per-username rate limit, as recorded in ADR-0009 (supersedes
ADR-0004).

**Reason:** Server-side sessions were needed anyway for revocation; storing the
CSRF token with them costs nothing and, unlike plain double-submit, is not
defeated by a cookie planted from a sibling subdomain of nsystems.live.

**Consequences:** Open question 4 is closed. `SEED_SESSION_SECRET` is no longer
used. Sign-in requires the database. New open questions: roles beyond `admin`
(the requirements ask for RBAC but name no roles), a per-client sign-in limit
(needs a trusted client address through the tunnel), and audit log retention.

## D-006 — Commands run in a separate sandbox container

**Date:** 2026-10-29

**Context:** M3's last part is the sandbox. Two designs were put to the owner:
one locked-down sandbox container that runs commands for the worker, or a fresh
container per command started through the Docker socket.

**Options:** separate sandbox container; container per command.

**Choice:** Separate sandbox container (owner's choice on 2026-10-29), with a
user per task inside it. Details in ADR-0010.

**Reason:** The Docker socket is root on a VPS that also hosts other services;
per-task users give the separation between tasks that one tenant needs.

**Consequences:** Workspaces are ephemeral (tmpfs) until M6. Open questions:
per-task disk quota; a stronger kernel boundary (gVisor) before multi-tenant use.

## D-007 — Chat turns are tasks

**Date:** 2026-10-29

**Context:** M4 asks for persistent conversations with streaming, task integration
and continuation. Chat ran inside the HTTP request and was lost when the page
closed. The owner agreed to start M4 with saved chats on durable tasks.

**Options:** keep a separate chat runner with its own storage; make every message
a task that carries the conversation.

**Choice:** Every message is a task (ADR-0011). Conversations are a small table;
turns are tasks with a conversation id, a turn number, a fixed context snapshot,
and the conversation's workspace.

**Reason:** Tasks already have leases, checkpoints, recovery, cancel, retry,
the event stream and the audit log. A second runner would duplicate all of it.

**Consequences:** `/api/v1/runs` is gone. Turns of one conversation run one at a
time. Failed turns are left out of later context. Open questions: whether
conversations are private to their owner once there are roles besides admin
(today they are listed per owner, while the Tasks list shows every task); how much
context to carry once answers get long (now a turn count, not tokens).

## D-008 — The last step of a run answers without tools

**Date:** 2026-10-29

**Context:** In the owner's manual tests, two writing requests ("a 600-word story",
"a 1500-word essay") on deepseek-v4.1-flash used all 8 steps on tool calls and ended
`max_steps` with no answer, after 22k and 32k input tokens.

**Options:** raise the step limit; make the last allowed step answer.

**Choice:** On the last allowed step the model gets no tools and a system note to
answer now (`WRAP_UP` in `core/agent.py`); the note is sent only on that request and
is not kept in the history. If the model still asks for a tool, the run ends
`max_steps` as before. Runs limited to one step keep their tools.

**Reason:** A higher limit only moves the cliff and costs tokens; a forced final
answer always gives the user something and says what is unfinished.

**Consequences:** A run that hits the limit now usually ends `completed`, so the
limit is visible only as a `wrap_up` flag on the last `step_started` event. Open
question: whether the default of 8 steps suits command-heavy tasks.

## D-009 — Shell commands wait for approval by default

**Date:** 2026-10-29

**Context:** M4 asks for approvals, and the requirements ask for approval of
destructive or sensitive operations. The tools today are list/read/write files in
a disposable workspace and `run_command` in the sandbox.

**Options:** commands only; commands and file writes; nothing until riskier tools exist.

**Choice:** Commands only (owner's choice on 2026-10-29). The list is a setting,
`SEED_APPROVAL_REQUIRED_TOOLS`; a tool can also mark itself as always needing approval.

**Reason:** Commands are the open-ended action; file writes stay inside the workspace,
and approving each one would interrupt most tasks.

**Consequences:** Every command pauses its task until someone answers; there is no
"approve all for this chat" yet. Open questions: per-conversation or per-command
allow lists; who may approve once there are roles besides admin.

## D-010 — Deleting, renaming and searching conversations

**Date:** 2026-10-29

**Context:** M4 lists rename, delete and search for chat. Turns are tasks with
events, and a conversation's files live in a sandbox workspace that only the worker
can reach.

**Options:** delete: hard delete vs. a hidden "deleted" flag; refuse vs. cancel an
unfinished turn first. Search: `ILIKE` scan vs. a full-text index.

**Choice:** Hard delete of the conversation, its turns and their events, refused
with 409 `turn_in_progress` while a turn is queued, running or waiting (the person
stops it first). The audit log keeps the deletion. Rename also retitles the turns,
so the Tasks list matches, and does not move the conversation up the list. Search is
a case-insensitive substring match over titles, prompts and answers, with `%` and
`_` taken literally.

**Reason:** Delete means gone; a hidden flag would keep data the person asked to
remove. Refusing keeps delete from racing a worker mid-turn. One person's
conversations are few enough that a scan is fast; an index can come when it is not.

**Consequences:** Workspace files of a deleted conversation stay until the sandbox
restarts (tmpfs). Open questions: deleting workspace files with the conversation
(needs a worker-side path, or M6 artifact storage); search snippets and ranking.

## D-011 — Editing and regenerating keep every version

**Date:** 2026-10-29

**Context:** M4 step 3b: edit and regenerate messages. Turns are tasks with their
own answers and timelines.

**Options:** last message only, replacing it; any message, dropping later ones;
any message, keeping versions to switch between.

**Choice:** Any message, keep versions (owner's choice on 2026-10-29, over the
recommended "last message only"). Built as a tree of turns; details in ADR-0013.

**Reason:** Nothing the person or the model produced is lost by editing, and an
earlier line of the conversation stays one click away.

**Consequences:** Built as two commits (the tree and its API, then the Chat
controls) in one PR, since both were ready together. Workspace files are shared by all versions. Open question: whether the Tasks list
should group a message's versions.

## D-012 — What the Command Center shows, and what it does not

**Date:** 2026-10-29

**Context:** M5 asks for real metrics: active and queued tasks, approvals,
failures, model usage, spend. Everything SEED has run is a task row with its
state, times and token usage.

**Options:** a metrics store fed by the worker; or reading the task table on
each request.

**Choice:** `GET /api/v1/overview` reads the task table: counts, short lists and
tokens by model for tasks that finished in a window (24 h by default). The page
polls every 10 s. It covers every user's tasks, like the Tasks list (D-007), and
is admin-only. Spend is not shown: no model prices are configured, and SEED does
not guess them.

**Reason:** The task table already holds the truth; a second store would be one
more thing to keep in step. A handful of aggregate queries over one person's
tasks is cheap, and polling every 10 s is light next to the task stream.

**Consequences:** Spend needs prices per model (and the monthly budget, still an
open owner question). Long histories may need an index on `finished_at`.
Agent activity, artifacts and notifications stay as their milestones (M7, M6, M8).

