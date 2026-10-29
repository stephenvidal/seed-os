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


## D-013 — The Inspector reads the event log, and records checkpoints in it

**Date:** 2026-10-29

**Context:** WS-7 asks for an Execution Inspector: steps, transitions, tool calls
and results, model, timing, tokens, retries, checkpoints, errors, with no
fabricated reasoning. Every run already writes an ordered event log
(`task_events`) with step usage and latency, tool results with durations,
provider retries and lifecycle events. Checkpoints were saved but not logged.

**Options:** a separate trace store written by the worker; or folding the event
log in the browser, plus one new event for checkpoints.

**Choice:** The page folds `GET /api/v1/tasks/{id}/events` (read page by page to
the last event) into attempts, model steps, tool calls and checkpoints.
`save_checkpoint` now logs `checkpoint_saved {steps, pending}` in the same
transaction as the save. Each `attempt_started` is its own row, because a pause
for approval or a shutdown hands the attempt number back and the resumed run
repeats it. A tool result or decision belongs to the newest call with its id,
because Ollama call ids restart at `call_0` every step.

**Reason:** The log is already the record of what happened; a second store could
disagree with it. One new event closes the only gap.

**Consequences:** Tasks that ran before this change show no checkpoint rows (the
summary still shows the stored checkpoint). Very long runs load every event; the
page reads 1000 per request. Not shown: delegation (M7), cost (no prices), and
verification. Open question: which milestone owns verification evidence in the
Inspector; no milestone names it.


## D-014 — Spend comes from Ollama's published prices and balance API

**Date:** 2026-10-29

**Context:** M5 shows no spend because no model prices were configured (D-012,
D-013). Ollama Cloud publishes per-token prices at https://ollama.com/pricing
(USD per million tokens; deepseek-v4.1-flash is $0.30 input, $0.006 cached
input, $1.20 output, half price outside 12:00-18:00 UTC on weekdays and all
weekend). The same API key can read `GET https://ollama.com/api/balance`
(included and purchased USD, plan period; 10 requests a minute) and
`GET https://ollama.com/api/usage?range=24h|7d|30d&group_by=model` (USD, tokens
and request counts). Chat responses carry `prompt_eval_count`,
`prompt_eval_cached_count` and `eval_count`. Read 2026-10-29 from
https://docs.ollama.com/api/balance.md and /api/cloud-usage.md; a read-only
`/api/balance` call with the deploy key returned HTTP 200.

**Options:** keep tokens-only; hard-code prices; configure a per-model price
table and read the balance API.

**Choice:** Plan to estimate each task's cost from its token counts and a
configured per-model price table (including the cached-input rate and the
off-peak window), and show the remaining balance from `/api/balance`, with
`/api/usage` as a cross-check. Not built yet; scheduled as the next step of M5.

**Reason:** The figures are published and queryable, so SEED need not guess.
Prices change, so they are configuration, not code.

**Consequences:** The monthly budget stays an open owner question for hard
stops (docs/model-strategy.md). The balance endpoint is rate limited, so the
server polls it at most once a minute. Legacy plans return session and weekly
percentages instead of USD; the code must handle both shapes.

## D-015 — Which files become artifacts

**Date:** 2026-10-29

**Context:** M6 starts with artifacts. The agent's files live in a scratch
workspace that a sandbox restart wipes. (D-014 is taken by the spend-tracking
plan.)

**Options:** save every file a run creates or changes; or give the agent a
publish tool and save only what it publishes.

**Choice:** Every changed file, per message (owner's choice on 2026-10-29, the
recommended option). Design in ADR-0014.

**Reason:** Nothing the agent makes is lost, it does not depend on the model
remembering to publish, and versions line up with the messages that made them.

**Consequences:** Studio may list scratch files the person does not care about;
filtering or hiding comes with the Studio page if it is needed.

## D-016 — How Studio shows files without trusting them

**Date:** 2026-10-29

**Context:** Studio renders files the agent wrote, including HTML with scripts,
on the app's own origin.

**Options:** a separate preview origin; same origin with every file sandboxed by
CSP; sanitised HTML in the app's DOM.

**Choice:** Same origin, sandboxed by CSP. Saved versions never run; previews of
the latest files run in an opaque origin with no network, through hour-long links.
Details in ADR-0015.

**Reason:** No new domain, tunnel route or certificate per deployment, and the
browser enforces the boundary rather than a sanitiser.

**Consequences:** A preview can draw anything, including look-alike forms, but
cannot submit them or reach SEED. Older versions show as source only.

## D-017 — What a project is, first

**Date:** 2026-10-29

**Context:** WS-5 lists many things a project holds (conversations, tasks, files,
artifacts, repos, instructions, knowledge, milestones, activity, permissions). M6
needs projects before project memory can exist.

**Options:** build the full list at once; or start with a project as a name and
instructions over a group of the owner's conversations, with their saved files,
and add the rest as each is needed.

**Choice:** The second. A conversation belongs to at most one project and can be
moved in or out. Each turn copies the project's instructions when it is sent (as
it copies the conversation context), and the worker appends them to the system
prompt as the owner's instructions. Each chat keeps its own workspace. Deleting a
project keeps its chats.

**Reason:** Instructions are the part of a project that changes what SEED does;
copying them per turn keeps retries and resumed runs identical to the first
attempt. Shared workspaces across a project's chats would change how files and
versions work (ADR-0014) without a stated need.

**Consequences:** Editing instructions does not change answers already sent.
Lone tasks are not in projects yet. Memory (owner's choice on 2026-10-29: the agent
proposes, the owner approves) builds on this.

## D-018 — Project memory: the agent proposes, the owner approves

**Date:** 2026-10-29

**Context:** The requirements ask for project memory with provenance, update,
delete, scope and context budgeting, and "no silent promotion of untrusted
content". The owner chose on 2026-10-29 that the agent proposes and the owner
approves, and that the owner can also add, edit and delete notes.

**Options:** the agent saves freely; only the owner writes; the agent proposes and
the owner approves (chosen).

**Choice:** A `remember` tool, offered only in a project's turns, stores a
proposal with its source chat and task. It does not pause the run (unlike command
approvals, ADR-0012): the proposal waits on the project page, and only approved
notes reach the model. Rejecting deletes the proposal. Each turn copies the
approved notes when it is sent (newest first, whole notes, at most 4,000
characters) like its instructions (D-017), and the worker adds them to the system
prompt as owner-approved notes. A task may propose at most 5 notes; the same note
is proposed once, so a retried run adds nothing.

**Reason:** Nothing the agent read becomes standing context without a person
seeing it, and waiting for review does not hold up the answer.

**Consequences:** A proposal takes effect from the first message after it is
approved. Older notes beyond the budget are not sent; relevance filtering and
searchable knowledge are not built.

## D-019 — Model output is shown rendered first

**Date:** 2026-10-29

**Context:** Chat answers, task results and Studio files showed Markdown tables,
HTML and similar as text. The owner asked for the rendered view first, a switch to
the source, and HTML that is mobile responsive, shown at the viewer's device width
first with a switch to the other.

**Options:** (a) steer the model only, through the system prompt; (b) fix the HTML
on the client only, by injecting a viewport meta tag and base styles; (c) both. For
inline HTML (a fenced block or a whole-page answer): run it with scripts, or
without.

**Choice:** (c). The system prompt asks for one self-contained, responsive page
(viewport meta, fluid layout, media queries, inline styles). The client also puts a
viewport meta and low-specificity base styles into inline HTML so a page that
ignored the prompt still fits a phone. Inline HTML runs in a frame with
`sandbox=""` (no scripts, no same-origin) and a CSP meta placed first (`default-src
'none'`, inline styles, `data:` images and fonts). Studio files keep ADR-0015's
served preview (`allow-scripts allow-modals`, opaque origin, server CSP) in the same
frame component, which now starts the preview on open. The frame's width is the
viewport: 390px for the phone view, a 1024px window scaled to fit for the desktop
view; it opens in the phone view at 640px or narrower and the desktop view above.
Fenced `html`, `svg` and `markdown` blocks render; tables already render as GFM.
While an answer streams, HTML stays code until it is complete.

**Reason:** The prompt alone cannot be trusted; the client alone cannot make a
fixed-width page fluid. Chat HTML is model output with no owner review, so it gets
the stricter frame; Studio files are the owner's saved artifacts behind a short-lived
token.

**Consequences:** Inline HTML cannot run scripts (a chart needing JavaScript shows
in Studio as a file instead). Studio HTML files are not rewritten, so their
responsiveness depends on the page; the phone view lays them out in a 390px frame so
media queries apply. CSV and JSON are not rendered specially.

## D-020 — Raw HTML answers render; the output cap is 16,384 tokens

**Date:** 2026-10-29

**Context:** On the live site, asking for "an html story" gave answers with the
Rendered / Source switch and an empty body. The Markdown renderer drops raw HTML
(`skipHtml`), and the model had answered with HTML that was not inside a fence and
not a whole `<!doctype>` page (a fragment, or prose followed by a page), so nothing
was left to show. A second answer stopped at exactly 4,096 output tokens, the
per-step cap (`RunLimits.max_output_tokens_per_step`), which a full HTML page or a
long essay can exceed.

**Choice:** An answer that opens with an HTML tag renders in the frame whole; a page
that follows prose renders as the prose, then the frame. The cap is 16,384 tokens per
step; the 200,000-token run total still bounds a run.

**Reason:** Showing nothing is the worst outcome; dropping raw HTML stays right for
the inline Markdown path. 4,096 tokens cut off pages mid-document.

**Consequences:** Raw HTML tags in the middle of a Markdown answer are still dropped.
A step that hits the cap still ends as `length`; the page shows what arrived.

## D-021 — Chat links to the files an answer saved, and opens them in a dialog

**Date:** 2026-10-29

**Context:** The owner asked that a chat message that saves a Studio artifact show a
link to it, opening a dialog that displays it, so it can be reviewed without leaving
the conversation.

**Options:** (a) add the saved artifact ids to the task or conversation API; (b) read
them in the browser from what exists: the chat's file list
(`GET /api/v1/artifacts?conversation_id=`) and the task's `artifacts_saved` event.

**Choice:** (b). A finished answer looks up its chat's files once; only if the chat
has any, it reads that task's events and links each file the task saved and did not
delete, matched by path. The dialog reuses Studio's viewer unchanged (served HTML
preview, Rendered / Source switch, Markdown, images, text) and links to Studio.

**Reason:** No backend or migration change, and a chat without files costs one
request. The viewer is moved, not copied, so Studio and chat cannot drift.

**Consequences:** A link opens the version that answer saved. If a later answer
changed the file, that version shows as source only (previews run the latest saved
files, ADR-0015); Studio has the versions. A file deleted with its chat gives "no
longer exists". Opening a long chat with files reads every completed turn's events.

## D-021 — Project knowledge is full-text search over text documents

**Date:** 2026-10-29

**Context:** The memory requirements list "searchable knowledge". The owner chose
on 2026-10-29 to finish M6 (knowledge, then summaries) before M7. The deployment
is one small VPS with no GPU, and the requirements ask for low idle memory and no
GPU assumption.

**Options:** embeddings with pgvector (needs an extension and an embedding model,
local or paid per call); Postgres full-text search; the agent reading whole
documents with file tools.

**Choice:** Postgres full-text search. The owner adds text documents (.md,
.markdown, .txt, .csv, .json, up to 256 KiB) on the project page; each is split
into passages of up to 1,500 characters on paragraph breaks and indexed with
`to_tsvector('english', …)` (a generated column with a GIN index). A
`search_knowledge` tool, offered in a project's turns, returns the five best
passages by `ts_rank` for a `websearch_to_tsquery` query. Passages are tool
results, so the model treats them as data.

**Reason:** No new service, extension, model or cost; it runs in the Postgres
already deployed, and word search with stemming suits notes and documentation.

**Consequences:** Search matches words, not meaning: a question phrased with
different words than the document can miss. Embeddings can be added later behind
the same tool if that proves a problem. PDFs and Word files are not accepted.
Uploads go through nginx, which now accepts request bodies up to 2 MiB.

## D-022 — Session summaries roll forward, per turn, made by the worker

**Date:** 2026-10-29

**Context:** The memory requirements list "session summaries" and say "no
unbounded history". A chat message carries its last `SEED_CHAT_CONTEXT_TURNS`
(20) answered turns; older ones were silently dropped. The owner chose on
2026-10-29 to finish M6 (knowledge, then summaries) before M7. Conversations are
trees (ADR-0013): a new version of a message shares the turns before it.

**Options:** (1) summarize when a turn finishes, in the background; (2) summarize
in the worker just before the turn that first needs it; (3) summarize per
conversation instead of per turn; (4) keep dropping old turns.

**Choice:** Option 2, stored per turn. Sending a message records `summary_of`, the
newest answered turn left out of its context. Before the run, the worker gets the
summary of the path through that turn: stored on that turn if it exists, otherwise
made from the newest earlier summary on the path plus the turns after it, at most
10 turns per model call, with the turn's own model, and stored on the turns it
runs through. The summary (at most 250 words asked, 4,000 characters kept) goes in
the system prompt as background. Its tokens are added to that turn's usage; the
timeline gets `context_summarized` or, if it fails, `summary_failed`, and the turn
runs without it.

**Reason:** A summary stored on a turn covers a fixed path, so every version built
on that turn can reuse it, which a per-conversation summary (3) cannot. Making it
just before the run (2) needs no extra job, never races the next message, and
costs nothing for chats that stay inside the window. Rolling keeps each call
bounded however long the chat gets.

**Consequences:** The first message past the window waits for one extra model
call. A summary loses detail; the turns stay in the database and the chat. A run
resumed from a checkpoint already holds its summary in its messages, so no new
summary is made; if a turn pauses for an approval after summarizing, the
summary's tokens are not added to its usage (the checkpoint keeps the run's own).
The owner cannot edit a summary yet.

## D-023 — A task started outside a chat can run in a project

**Date:** 2026-10-29

**Context:** WS-5 lists a project's tasks. Chats could be in a project (D-017),
but tasks started from the Tasks page could not, so they never got a project's
instructions, memory or knowledge. The owner chose on 2026-10-29 to finish M6
with this before M7.

**Options:** (1) a project on lone tasks, copied like a chat turn's; (2) moving
tasks into and out of projects after they are created; (3) leave lone tasks out of
projects.

**Choice:** Option 1. `POST /api/v1/tasks` takes `project_id`; the task copies the
project's instructions and approved memory when it is created, exactly as a chat
turn does, and its run gets the `remember` and `search_knowledge` tools. A task
cannot change project afterwards. `GET /api/v1/tasks?project_id=` lists the
project's tasks started outside a chat (its chats' turns are listed with the
chats); projects count them as `tasks`. Deleting a project keeps its tasks and
takes them out of it, as with chats.

**Reason:** It reuses the turn's copy-on-send rule, so a task behaves like a
one-message chat in the project and nothing new has to be explained. Moving a
finished task (2) would change nothing about how it ran, so it is not built.

**Consequences:** A task sees the project's instructions and memory as they were
when it was created. A queued task in a project that is then deleted runs without
the memory and knowledge tools.

## D-024 — Agent definitions, with three starters given once

**Date:** 2026-10-29

**Context:** M7 adds specialists SEED can delegate to. The requirements ask for
configurable agent definitions (role, model, tool permissions) and real separate
execution contexts, not personas. The owner chose on 2026-10-29 that the Agents
page starts with three editable starter specialists rather than empty.

**Options:** definitions in a config file; in the database, edited on the Agents
page; for the starters, seeding them in a migration, at admin bootstrap, or the
first time each owner lists agents.

**Choice:** In the database, per owner: a name (1-40 characters, unique ignoring
case, since the assistant will name the agent it delegates to), what it is for
(read by the assistant to choose), instructions, a model (blank: the delegating
task's) and allowed tools from `list_files`, `read_file`, `write_file`,
`run_command`, `search_knowledge`. `remember` is not offered: memory proposals
stay with the assistant the owner talks to. The starters, Researcher (read and
search), Coder (files and commands) and Reviewer (read only), are inserted the
first time an owner lists agents, recorded in `agent_starters` so deleting them
does not bring them back; an agent of the owner's with the same name is kept.

**Reason:** Owners change agents from the app, like projects. Seeding on first
list works for every owner, not just the bootstrap admin, and needs no migration
data.

**Consequences:** Changing an agent affects delegations started afterwards only
(step 2 copies the definition into the delegated task). `run_command` still waits
for approval under `SEED_APPROVAL_REQUIRED_TOOLS`. Nothing delegates yet; the
Agents page says so.

## D-025 — Delegation is a deferred tool call answered by a child task

**Date:** 2026-10-29

**Context:** The requirements ask that delegation be "real separate execution
contexts, not personas", with explicit inputs, outputs and ownership, and that
the primary assistant integrates and delivers. Tasks must survive restarts.

**Options:** (1) run the agent inline inside the parent's tool call (one worker,
one process, lost on a crash, no own timeline); (2) the parent's tool call starts
a child task and the parent waits for it like it waits for an approval; (3) a
separate orchestration service.

**Choice:** Option 2. The `delegate` tool (`{agent, task, deliverable}`) is
offered when the owner has agents, listing each with its purpose and tools. It is
*deferred*: the loop checkpoints and pauses on the call (termination
`awaiting_delegation`). The worker then, in one transaction, parks the parent
(`waiting`, `awaiting_delegation`) and inserts the child: prompt = task + "Report
back: deliverable", the agent's definition copied (`agent`), its model or else
the parent's, the parent's workspace and project, `parent_task_id` and the call
id. An unknown agent is answered at once with the list of names. The child runs
with a system prompt naming the agent, its owner-given instructions, and only its
allowed tools (`search_knowledge` only in a project; never `remember` or
`delegate`, so depth is 1). Whenever the child ends (finished, failed, canceled,
or swept as dead), the same transaction writes its result into the parent's
`delegations` and queues the parent, whose resumed run gives the call that
result. Canceling a task cancels its children; a child cannot be retried. A
task waiting for a child is not "waiting on you": the overview counts it as
`delegating` and lists it as active; the chat list says "with an agent".

**Reason:** It reuses the durable pause/resume already proven for approvals, so a
delegation survives worker and server restarts, has its own task page, events,
limits and usage, and needs no new service.

**Consequences:** One delegation runs at a time per parent (parallel sub-tasks
are M7 step 3); agents share the parent's workspace. The agent's tokens are its
own task's usage, not added to the parent's. The first listing of agents, from
the Agents page or from a run, gives an owner the starters (D-024).

## D-026 — Parallel delegation, with limits, and several tasks per worker

**Date:** 2026-10-29

**Context:** The requirements list "parallel subtasks" as a delegation mode and
"delegation depth, concurrent workers" as configurable limits. Under D-025 a
step that asked for three agents started one, waited, then started the next,
and an agent could not delegate at all. A worker process ran one task at a
time, so a single-worker install made agents queue behind each other.

**Options:** (1) start every delegate call of a step at once; (2) start them in
order up to a limit on agents working at once, and start the rest as earlier
ones report back; (3) a scheduler service that assigns agent tasks to workers.

**Choice:** Option 2. When the run pauses on a delegate call, the worker reads
the step's remaining calls from the checkpoint and, in one transaction, starts
an agent task for each valid delegate call not already working or answered,
while fewer than `SEED_DELEGATION_MAX_PARALLEL` (default 3) of this task's
agents are working; the call the run waits on always starts. Calls naming no
agent, and calls past `SEED_DELEGATION_MAX_PER_TASK` (default 10, refusals
included) in one run, are answered at once with the reason. The scan stops at a
call that needs approval, since a person decides before anything after it
happens, and at the loop's per-step call cap. A result that arrives while the
parent is queued or running is kept; the parent is queued only when it is the
call it waits for. Each task records `delegation_depth` (0 when a person
started it); `delegate` is offered while it is below `SEED_DELEGATION_MAX_DEPTH`
(default 1, so agents still do not delegate unless the owner raises it). A task
that ends cancels the agent tasks it still has working, so a retried task never
mistakes an old agent task for one of its own. One worker process runs
`SEED_WORKER_CONCURRENCY` (default 2) workers, each its own claim loop and lease.

**Reason:** It reuses the D-025 pause and report-back unchanged for each call,
needs no new service, and bounds the cost of one request in agents, model calls
and worker slots.

**Consequences:** The run still waits for its calls in order: a step's results
reach the model together once all are in, never one by one. Calls after the
one the run waits for show in the live answer as agents working, but their
tool call events appear when the run reaches them. Agents share the parent's
workspace, so two agents writing the same file race; the owner chooses which
agents get `write_file`. The database pool grows with the concurrency (2 + 2
per worker).

## D-027 — Worker concurrency default of 4

**Date:** 2026-10-29

**Context:** The live check of D-026 showed Researcher and Coder overlapping but
Reviewer starting only when one finished, though `SEED_DELEGATION_MAX_PARALLEL` is
3. A task waiting for its agents already gives up its worker (the worker returns
once it has parked the task), so it was not holding a slot. The cause was the
default of 2 workers per process: only two agent tasks could run at once.

**Choice:** `SEED_WORKER_CONCURRENCY` defaults to 4, above the parallel limit of 3,
so the three agents and the resumed parent can each have a slot. A test fails if
the default is not above the parallel limit. An owner who raises the parallel
limit raises concurrency with it; the README says so.

**Consequences:** One worker process may run four model calls at once. Each
worker's pool use grows the pool to 10 connections. Agents of different tasks
share the same slots, so heavy use still queues the oldest task first.
