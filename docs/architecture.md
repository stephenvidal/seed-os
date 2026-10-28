# Architecture — SEED OS

Status as of Iteration 1. "Built" means it exists and is tested; "planned" is the
ratified target (Directive v1.1, ADRs in `decisions/`).

## Shape: modular monolith + workers (ADR-0001)

```
 Browser ──HTTPS──▶ web (nginx: SPA + /api proxy, CSP)        [built]
                      │
                      ▼
                    api (FastAPI modular monolith)             [built: auth, system]
                      │   ├─ seed_api.auth     sessions, roles
                      │   ├─ seed_api.system   host telemetry
                      │   ├─ core/      SEED Core: providers, agent loop, tools [M2: built]
                      │   ├─ seed_api.runs  /models, /runs (SSE, in-request)  [M2: built]
                      │   ├─ flow/      SEED Flow tasks/events  [M3: store, API built]
                      │   ├─ memory/, studio/, connect/          [M6–M8]
                      ▼
                    postgres (tasks, events, artifacts meta)   [M3: tasks, events built]
                      ▲
                    worker(s) (lease + heartbeat, run loops)   [M3: built, ADR-0008]
                      │
                    sandbox (isolated tool execution)          [M2/M3]
```

Subsystem names (Core, Flow, Studio, Memory, Connect, Control) are **packages in
one deployable**, not services. Workers are the only separately scaled process,
because agent loops are long-running and must not live in request handlers.
Model-generated commands execute only in the sandbox, never in `api`.

## Frontend (ADR-0002)
Vite + React 19 + TypeScript (strict) SPA, Tailwind v4 over semantic CSS tokens,
TanStack Query for server state, React Router, Radix primitives, cmdk, Lucide.
A SPA fits: SEED is an authenticated app with no SEO surface; SSR adds a second
runtime with no benefit. Layout: `src/lib` (api, auth, theme, nav, shortcuts),
`src/components/{ui,shell}`, `src/pages`.

## Backend
Python 3.12+, FastAPI, Pydantic v2, pydantic-settings. App factory in
`seed_api.main`. Every error crosses the boundary as
`{"error": {"code", "message"}}` (`seed_api.errors`). Config comes only from
`SEED_*` environment variables.

## Real-time (ADR-0003, planned M3/M4)
Server-Sent Events with per-task monotonically increasing sequence ids, persisted
before emission, so a reconnecting client sends `Last-Event-ID` and replays
missed events from Postgres. WebSockets are not needed: client→server actions
are ordinary POSTs.

## Auth (ADR-0004)
M1: one bootstrap admin from env; HMAC-SHA256-signed, expiring, HttpOnly,
SameSite=Lax cookie; role claim enforced by backend dependencies
(`require_role`). M3 moves users/roles/sessions into Postgres with revocation.

## Resource envelope (measured, Iteration 1)
`docker stats` after start: api 39.8 MiB, web 5.1 MiB. Production JS bundle
446.7 kB (142.5 kB gzip). No GPU assumed.
