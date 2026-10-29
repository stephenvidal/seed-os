# Requirements — SEED OS

Distilled from Directive v1.1. IDs are stable; each feature needs explicit
acceptance criteria before it is built (Directive v1.0 §3). "Status" is the truth
as of the last `docs/progress.md` entry.

## Workspace (functional areas)
| ID | Area | Summary | Status |
|---|---|---|---|
| WS-1 | Command Center | Active/queued tasks, agent activity, approvals, failures, health, resources, model usage, spend, artifacts, notifications; drill-down | Page structure only (M1); data in M5 |
| WS-2 | Native Chat | Persistent conversations, streaming, Markdown/code, attachments, artifact refs, search, model select, edit/regenerate, approvals, tool activity, task-vs-chat distinction | Built (M2, M4): saved conversations whose turns are tasks, streaming, Markdown, model select, tool activity, usage, approvals, rename/delete/search, edit/regenerate as versions. Not built: attachments, artifact refs |
| WS-3 | Task Operations | States: draft, queued, running, waiting-for-input, paused, completed, failed, canceled; list/detail/timeline; pause/resume/cancel/retry/redirect only when implemented | Built (M3): queued/running/completed/failed/canceled, list, detail, live timeline, cancel, retry. Draft/waiting/paused not built |
| WS-4 | Agent Workforce | Orchestrator + configurable specialists, models, tool permissions, workloads, delegation view, metrics | Page structure only; M7 |
| WS-5 | Projects | Overview, conversations, tasks, files, artifacts, repos, instructions, knowledge, milestones, activity, permissions | Page structure only; M6 |
| WS-6 | SEED Studio | Artifact browsing/preview/versions/downloads/metadata/validation; HTML isolated from privileged origin | Page structure only; M6 |
| WS-7 | Execution Inspector | Steps, transitions, tool calls/results, delegation, model, timing, tokens, cost, errors, retries, checkpoints, verification. No fabricated private reasoning | Page structure only; M5 |
| WS-8 | Models & Providers | Connections, credentials, discovery, capabilities, defaults, per-agent/task overrides, routing, fallback, budgets, limits, usage | Page structure only; M2 |
| WS-9 | Tools & Skills | Tools, skills, permissions, policies, integration status, history, diagnostics | Page structure only; M2/M8 |
| WS-10 | Settings & Admin | Profiles, auth, roles, security, notifications, appearance, storage, backups, health, gateway, runtime, logs, updates | Appearance (theme) + system health only |

## SEED Core (runtime)
Pipeline: Request → Interpretation → Planning → Authorization → Execution →
Observation → Reassessment → Verification → Delivery. Simple requests skip
planning. Needs structured messages, provider abstraction, streaming, tool
calling, multi-step loops, context assembly, bounded retries, cancellation,
deadlines, delegation, approvals, persistent state, structured events,
completion verification. Configurable limits: steps, runtime, tokens, spend,
delegation depth, concurrent workers. Explicit termination conditions.

## SEED Flow (durability)
Tasks survive refresh, tab close, disconnect, timeout, worker crash, provider
failure, server restart. Needs state machines, leases, heartbeats, checkpoints
(resume-safe, not merely "step happened"), retry policy, idempotency keys,
cancellation, graceful shutdown, recovery, dead-letter, audit. Side effects must
not duplicate on retry; distinguish resumable from manual-reconcile work.

## Delegation
Modes: direct, single-agent tools, structured multi-step, delegated specialist,
parallel subtasks, human-supervised. Do not use many agents where one suffices.
Agent definitions configurable. Delegated tasks have explicit inputs, outputs,
ownership, completion criteria; the primary assistant integrates and delivers.
Delegation is real separate execution contexts, not personas.

## Models
Adapters for Anthropic, OpenAI, DeepSeek, OpenRouter, OpenAI-compatible, local,
behind one internal interface; differences in tool calling, structured output,
streaming, context, token accounting, capabilities, errors. Cheap models for
routine work, strong for planning/architecture/hard coding/security/verification.
Per-task and per-model accounting; observable, configurable routing.

## Tools
Typed registry; each tool declares id, description, input/output schema,
permissions, timeout, resource limits, error behavior, audit metadata. Initial:
files, dirs, terminal, git, code edit, HTTP, web retrieval, artifact generation,
structured data. **Model-generated shell never runs in the API process**:
isolated workers/sandboxes with fs/net/CPU/mem/time bounds; approval for
destructive/sensitive ops; untrusted-content handling and prompt-injection defenses.

## Memory
Layers: conversation, session summaries, project memory, approved preferences,
task history, searchable knowledge, artifact refs. Provenance, relevance
filtering, update, delete, scope, context budgeting. No unbounded history; no
silent promotion of untrusted content.

## Security & governance
Secure auth, sessions, RBAC enforced in backend, protected secrets, transport
encryption, audit logs, tool approval policies, fs isolation, network
restrictions, safe artifact rendering, input validation, rate limiting,
dependency auditing, backup/recovery. Side effects attributable to task, agent,
authorization decision. Secrets never in logs, model context, or artifacts.

## Efficiency
Low idle memory, bounded concurrency, lazy loading, efficient queries, minimal
polling, resource-aware scheduling, controlled logging, configurable retention.
Document expected CPU/RAM/storage/network. No GPU assumption.

## Engineering standards
Type checking, lint, format, unit/integration/e2e/migration/security/a11y/visual
regression tests, structured logging, ADRs. Avoid monolithic files, circular
deps, duplicated logic, hardcoded creds, fake telemetry, placeholder interactions.

## Mandatory acceptance test (first integrated release)
"Build me a responsive project dashboard with a task list and progress tracking."
Must: accept via native chat; persist conversation; create durable task; plan;
request authorization; generate files; run tools isolated; validate; produce
artifact/preview; stream progress; record history; survive restart; accept a
modification; continue in same project. Real model, real tools, no scripts.
Not yet attempted (M2–M6 prerequisites).
