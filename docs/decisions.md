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
