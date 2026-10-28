# Progress — SEED OS

Append-only, one block per session. Format: changed / tested / not tested / open.

---

## 2026-10-28 — Iteration 0: repository frame

**Intent:** Establish the repository, the governing directive (v1.0), and the
execution rules for Claude Code.

**Changed**
- `README.md` — project frame, repository map, ground rules.
- `DIRECTIVE.md` — Directive v1.0: scope, execution environment, approach,
  definition of done, gate, non-negotiables, change control.
- `CLAUDE.md` — Claude Code session protocol, hard rules, production bar,
  verification checklist.
- `docs/decisions.md` — D-001 and the open-questions register.
- `.gitignore` — editor/OS noise, environment files, dependency and build
  directories, language-agnostic so no toolchain is prejudged.

**Tested**
- `git status --short` clean after commit; `git ls-remote origin` reports the
  pushed commit SHA (see commit on `main`).
- Repository visibility read back from the GitHub API: private, owner
  `stephenvidal`.

**Not tested**
- Nothing is executable yet, so no runtime verification exists for this iteration
  beyond repository state. That is the correct state for Iteration 0.

**Open**
- Directive v1.1 (product definition) is the blocker for Iteration 1.

---

## 2026-10-28 — Iteration 1: Milestone 0 + Milestone 1 foundation

**Current milestone:** M1 Premium application foundation (M0 complete).

**Intent (stated before editing):** Ratify the owner's master directive as v1.1,
record the architecture, and ship a running, signed-in SEED Workspace shell
(design system, navigation, themes, command palette, auth foundation) backed by a
real API — no fake data.

**Definition of done:** (1) `docker compose up` serves the app and API from a
clean build; (2) backend and frontend checks pass and can fail; (3) light, dark,
and mobile layouts inspected in a real browser; (4) docs describe the shipped
behaviour.

**Changed**
- `DIRECTIVE.md` — v1.1 amendment appended (v1.0 text untouched).
- `CLAUDE.md` — v1.1 pointer, commands, environment reality.
- `docs/` — product-vision, requirements, roadmap, architecture, design-system,
  security, deployment, model-strategy, testing, ADRs 0001–0005, D-002.
- `backend/` — FastAPI app: `/healthz`, auth (login/logout/me), `/api/v1/system`.
- `frontend/` — tokens, UI primitives, shell, palette, Command Center, Settings,
  sign-in, empty-state pages for every other area.
- `compose.yaml`, Dockerfiles, nginx config, `.env.example`, `CHANGELOG.md`.

**Tested (observed output)**
```
backend$ ruff check . && ruff format --check . && mypy && pytest -q
All checks passed!
9 files already formatted
Success: no issues found in 6 source files
11 passed, 1 warning in 0.13s

frontend$ npm run typecheck && npm run lint && npm run format:check && npm test && npm run build
All matched files use Prettier code style!
 Test Files  3 passed (3)
      Tests  12 passed (12)
dist/assets/index-B3WYoWvz.js   446.68 kB │ gzip: 142.50 kB
```
- Tests can fail: forcing `valid = True` in `verify_token` → `1 failed, 10 passed`;
  breaking `resolveTheme` → `1 failed | 11 passed`.
- Browser (Playwright/Chromium, dev servers): wrong password shows alert; correct
  password enters shell; palette "task"+Enter → `/tasks`; `g` `,` → `/settings`;
  `Ctrl+B` collapses sidebar; 390px mobile: drawer opens, no horizontal overflow
  (`scrollWidth > innerWidth` = false). Only console errors were the expected 401s.
- Compose: `api Up (healthy)`; `/healthz` → `{"status":"ok","version":"0.1.0"}`;
  login via nginx → `{"username":"admin","role":"admin"}`; `/api/v1/system`
  returns host data; `/tasks` → 200 with CSP and `X-Frame-Options: DENY`;
  `docker stats`: api 39.81 MiB, web 5.07 MiB.

**Not tested / caveats**
- Compose build was verified in a scratch copy with this sandbox's proxy CA
  injected (pip/npm otherwise fail TLS here, and Docker Hub returned 429 so base
  images came from `mirror.gcr.io`). The committed Dockerfiles are the same minus
  those two lines; they have not been built on a normal host.
- The final "Search or jump to…" label change was not re-screenshotted.
- No CI (hosted Actions blocked). No E2E or visual-regression suite yet.
- Contrast ratios were checked by axe in jsdom only (axe cannot compute colors
  there); a real-browser contrast audit is still owed.

**Known defects / gaps**
- No CSRF token (SameSite=Lax mitigates); inline theme script forces CSP
  `'unsafe-inline'`; per-process login limiter; no session revocation.
- Resizable panels, context menus, toasts not built (no screen needs them yet).

**Blockers:** none.

**Next recommended actions:** M2 — provider adapter interface + first adapter,
typed tool registry, isolated execution worker, real model + tool call shown in
the UI. Owner input needed on default models/budget (open question 5).

---

## 2026-10-28 — Iteration 1 addendum: CI/deploy pipeline from dustline

**Intent:** Adopt the owner-approved dustline CI/deploy pattern (D-003) without
enabling any production deploy.

**Changed:** `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`,
`.github/actionlint.yaml`, `deploy/compose.yaml`, OCI source labels in both
Dockerfiles, `docs/deployment.md`, `docs/decisions.md` (D-003), `CLAUDE.md`,
`README.md`, `CHANGELOG.md`.

**Tested**
```
$ actionlint            # with golden-eye declared as a self-hosted label
ACTIONLINT_OK
$ docker compose config (deploy/, sample .env)
image: ghcr.io/stephenvidal/seed-api:sha-abc1234
image: ghcr.io/stephenvidal/seed-web:sha-abc1234
host_ip: 127.0.0.1   published: "8091"   SEED_COOKIE_SECURE: "true"
$ docker compose up (deploy/compose.yaml, locally built images retagged sha-test)
api Up (healthy) · web 127.0.0.1:8091->8080/tcp
/healthz -> {"status":"ok","version":"0.1.0"}
login -> HTTP/1.1 200 OK; set-cookie: seed_session=…; HttpOnly; …; SameSite=lax; Secure
```
Both images rebuilt and carry `org.opencontainers.image.source=https://github.com/stephenvidal/seed-os`.

**Not tested**
- The workflows have not run: no runner is registered for seed-os yet. GHCR push,
  SSH deploy, `gha` cache, and `setup-python` on golden-eye are unverified.
- shellcheck was not available to actionlint, so inline shell was not linted.

**Blockers (owner actions):** register a seed-os runner on golden-eye; prepare
`/opt/seed/.env`, tunnel route, repo secrets/variables (`docs/deployment.md`).

---

## 2026-10-28 — CI fix: backend checks in a container

**Context:** First CI run on the new seed-os runner on golden-eye failed in
`actions/setup-python@v5`: `./python: CPU ISA level is lower than required`
(the prebuilt CPython for that OS needs a newer x86-64 level than the host CPU).

**Changed:** `.github/workflows/ci.yml` runs backend checks inside
`python:3.13-slim` (the production base image) instead of setup-python; source is
mounted read-only and copied, so no root-owned files land in the runner workspace.

**Tested:** the exact step script, run locally in `python:3.13-slim`
(sandbox-only additions: proxy CA and host network for pip):
```
11 passed, 1 warning in 0.12s
```
(ruff check, ruff format --check, mypy ran first under `set -e` and passed.)
`actionlint` → clean.

**Not tested:** the step on golden-eye itself; the re-run on the PR will show it.

---

## 2026-10-28 — CI: frontend checks in a container

**Context:** Re-run on golden-eye (head 5735d3d): backend step passed on the
runner (`All checks passed!`, `9 files already formatted`, `Success: no issues
found in 6 source files`, `11 passed`). Then `actions/setup-node` spent ~6 min in
"Adding to the cache ..." and the job ended with "The runner has received a
shutdown signal" — runner-side, before any frontend command ran.

**Changed:** frontend checks run in `node:22-alpine` (the web build image), same
read-only-mount-and-copy pattern as the backend; no tool-cache writes.

**Tested:** exact step script locally (sandbox-only: proxy CA, host network):
`added 307 packages`, Prettier clean, `Test Files 3 passed (3)`,
`Tests 12 passed (12)`, `✓ built`. actionlint clean.

**Not tested:** on golden-eye. If the runner shuts down again without a heavy
step, the cause is on the host (runner service/watchdog), not the workflow.

---

## 2026-10-28 — Iteration 1 correction: vitest must not load Tailwind

**Context:** with checks now containerised (see above), the remaining unverified step
was `npm test`. Reproduced the failure outside Actions, on golden-eye, against a clean
`npm ci`:

```
Error [vitest-pool]: Failed to start forks worker for .../src/lib/api.test.ts
Caused by: Error: [vitest-pool-runner]: Timeout waiting for worker to respond
Test Files  no tests      Tests  no tests      Errors  3 errors
```

**Cause:** `vitest` inherited `vite.config.ts`, which loads the Tailwind v4 plugin.
On a loaded 4-vCPU box with a rotational disk, worker startup exceeded vitest's
60s pool timeout, so no test file was ever collected. Not a test defect — the same
tree passes when the plugin is not in the way.

**Changed:** `frontend/vitest.config.ts` (test-only config, `react()` only, no
Tailwind, `pool: threads` + `singleThread: true`); `frontend/tsconfig.json` includes
it. `vite.config.ts` is untouched, so dev/build still compile Tailwind.

**Tested (golden-eye, host toolchain, clean `npm ci`)**
```
tsc -b --noEmit            -> clean
eslint .                   -> clean
prettier --check           -> clean
npm test                   -> Test Files 3 passed (3) | Tests 12 passed (12) | 67s
npm run build              -> dist/assets/index-*.js 446.67 kB | gzip 142.50 kB
```
For comparison, the same tree under the Tailwind-loading config: 3 errors, no tests.

**Not tested:** the corrected `npm test` inside `node:22-alpine` in Actions, and the
`Build images (not pushed)` step. Also unresolved: an earlier run ended with "The
runner has received a shutdown signal" before any frontend command ran — that is a
host/runner-side event (memory pressure on golden-eye), not a workflow fault.

---

## 2026-10-28 — Iteration 1 decision: repository public, CI back on hosted runners

**Context:** the owner chose to make `stephenvidal/seed-os` public in exchange for
unmetered standard GitHub-hosted runners, accepting the exposure and asking for fork
tracking. Every previous CI compromise in this PR traced back to the private-repo
spending block plus golden-eye's 4-vCPU Pentium (no AVX), so both workarounds can go.

**Changed**
- `.github/workflows/ci.yml` — `runs-on: ubuntu-latest`, `actions/setup-python@v5`
  (3.13) and `actions/setup-node@v4` (22) restored, container wrappers removed,
  `permissions: contents: read` added. Fork guard and timeouts kept.
- `.github/workflows/deploy.yml` — both jobs on `ubuntu-latest`; SSH, host-key
  pinning, `DEPLOY_ENABLED` gate and image cleanup unchanged.
- `.github/actionlint.yaml` — deleted (it only declared the self-hosted label).
- `docs/deployment.md` — staging status, secrets handling, tunnel/DNS detail.

**Pre-public audit (observed, not asserted)**
```
grep -rInE '31\.187\.72\.46|100\.|192\.168\.|srv1388017|cfargotunnel|BEGIN .*PRIVATE KEY|ghp_|gho_|github_pat_|sk-' <tree>   -> no matches
git ls-files | grep -E '^\.env$'                                  -> only .env.example
git log -p main..HEAD | grep -E 'PRIVATE KEY|ghp_|password'      -> only test fixtures ("correct-horse")
```

**Not tested**
- No CI or deploy run has executed on a hosted runner yet.
- Fork monitoring is not automated yet; it is tracked separately from the repository.

---

## 2026-10-28 — CI fix: vitest.config.ts failed typecheck

**Context:** CI on fb42489 (golden-eye) failed at `npm run typecheck`:
```
vitest.config.ts(24,5): error TS2769: No overload matches this call.
  'poolOptions' does not exist in type 'InlineConfig'.
```
Vitest 5 removed `poolOptions`; vitest ignored the key at runtime (tests passed),
but `tsc` now covers the config. afcc8aa did not touch the file, so the hosted run
would fail the same way.

**Changed:** `frontend/vitest.config.ts` — `poolOptions.threads.singleThread` →
`maxWorkers: 1` (same effect, supported key). Reproduced the error locally first.

**Tested (local, clean tree at afcc8aa + fix):**
```
tsc -b --noEmit -> clean · eslint -> clean · prettier -> All matched files use Prettier code style!
Test Files  3 passed (3) · Tests  12 passed (12) · ✓ built
actionlint (hosted-runner workflows) -> clean
```
**Not tested:** the hosted-runner run itself; it starts on push.

---

## 2026-10-28 — CI green on hosted runners; repository hardened for public exposure

**Changed**
- `docs/deployment.md` — staging status (steps 1–4 done), hosted-runner rationale,
  secrets handling and rotation path.
- `frontend/vitest.config.ts` — comment corrected: the pool timeout happened on the
  retired self-hosted runner, not on the current CI host.

**Tested (observed)**
```
run 40769170969 (pull_request, 0ae85a2) -> completed / success, 1m25s
run 40769163771 (push,         0ae85a2) -> completed / success, 1m23s
gh pr view 1 -> mergeStateStatus CLEAN, statusCheckRollup: checks SUCCESS x2
```
Both runs executed the hosted workflow (setup-python, setup-node, docker build) that
the earlier runs could not: the self-hosted equivalent spent 15 minutes failing on
toolchain startup. The seed-os self-hosted runner has been deregistered from GitHub
and its unit and install directory removed from golden-eye; dustline's runner is
untouched.

**Repository hardening after going public**
- Secret scanning and push protection: enabled (verified via `security_and_analysis`).
- Vulnerability alerts and Dependabot security updates: enabled (HTTP 204).
- Fork tracking: `~/.hermes/scripts/seed-os-fork-watch.py` on a 6-hourly cron,
  silent unless a new fork appears or a known fork pushes. Logic verified against a
  stub `gh` (baseline message, silence when unchanged, "New fork of …" when a record
  is removed from state); the live repo currently has 0 forks.

**Not tested**
- `deploy.yml` has still never executed. `DEPLOY_ENABLED` remains unset, so the deploy
  job is skipped by design; the first image build needs a merge to `main`.
- Nothing has been deployed to `seed.nsystems.live`; the hostname answers 502 because
  no container is listening on `127.0.0.1:8091` yet.

## 2026-10-28 — Milestone 1 shipped: hosted CI green, first production deploy live

**Changed**
- `docs/deployment.md` — staging status marked done, hosted-runner rationale, secrets
  handling and rotation path.
- `frontend/vitest.config.ts` — comment corrected (the pool timeout belonged to the
  retired self-hosted runner, not to today's CI host).

**Pipeline result (observed)**

| Step | Evidence |
|---|---|
| CI on hosted runners | runs 40769170969 (pull_request) and 40769163771 (push) — `success` in 1m25s / 1m23s, versus 15-minute toolchain failures on the retired runner. PR #1 merged with `mergeStateStatus: CLEAN`. |
| Images published | `ghcr.io/stephenvidal/seed-api` and `seed-web`, tags `latest` + `sha-f68de47` |
| Deploy | run 40770378699 — "Build and push images" `success`, "Deploy to VPS" `success` after `DEPLOY_ENABLED=true` |
| Containers | `seed-api-1`, `seed-web-1` on `ghcr.io/stephenvidal/seed-web:sha-f68de47`, both healthy, listening `127.0.0.1:8091` |
| Public surface | `https://seed.nsystems.live/healthz` → `{"status":"ok","version":"0.1.0"}`; `/` → 200; CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin` present |
| Sign-in | `POST /api/v1/auth/login` → 200, cookie `seed_session=…; HttpOnly; Max-Age=43200; Path=/; SameSite=lax; Secure`; `/api/v1/auth/me` → `{"username":"admin","role":"admin"}`; `/api/v1/system` returns live telemetry |

**Public-repository hardening** (the repository is public by owner decision, so that
standard GitHub-hosted minutes are unmetered)
- Secret scanning + push protection: enabled.
- Vulnerability alerts + Dependabot security updates: enabled; dependency graph
  already publishing (`Graph Update: pip in /backend`).
- Fork tracking: `seed-os-fork-watch.py` on a 6-hourly schedule, silent unless a new
  fork appears or a known fork pushes new commits. Logic verified against a stub
  `gh`; the repository currently has no forks.
- The seed-os self-hosted runner was deregistered and its install removed from
  golden-eye once hosted runners were proven.

**Secrets:** `SEED_ADMIN_PASSWORD` and `SEED_SESSION_SECRET` exist only in the
encrypted vault and in `/opt/seed/.env` (mode 600, owner `deploy`). They are not in
the repository, the workflow logs, or any chat transcript.

**Not tested**
- No rollback has been exercised. The documented path (set `SEED_TAG` to an earlier
  `sha-…` and `docker compose up -d` in `/opt/seed`) is untried.
- Multi-user auth, CSRF tokens and everything in M2+ do not exist yet, so the only
  account is the bootstrap admin.

---

## 2026-10-28 — Iteration 2: Milestone 2 core runtime (stub-verified)

**Current milestone:** M2 Core agent runtime.

**Intent (stated before editing):** Give SEED its own agent runtime — provider
interface, Ollama adapter, typed tools, bounded loop — exposed as a streaming run
API and wired into Chat. **Definition of done for this increment:** each piece
tested against stubs and can fail; Chat renders a streamed run in a real browser;
docs updated. Real-model verification is a separate step (key not visible here).

**Changed:** `backend/src/seed_api/core/` (messages, providers/base, providers/ollama,
tools, workspace_tools, agent), `backend/src/seed_api/runs.py`, config, main;
`frontend/src/lib/runs.ts`, `pages/Chat.tsx`, api client; nginx SSE timeout;
ADR-0006; README, roadmap, requirements, architecture, testing, CHANGELOG,
`.env.example`.

**Tested (observed)**
```
backend$ ruff check . && ruff format --check . && mypy && pytest -q
All checks passed! · Success: no issues found in 15 source files · 43 passed
frontend$ tsc, eslint, prettier clean · Test Files 5 passed (5) · Tests 16 passed (16)
build: index-*.js 454.37 kB │ gzip 144.84 kB
```
- Tests can fail: removing the workspace confinement check → `1 failed`;
  disabling the max-steps check → `test_stops_at_max_steps` fails.
- Browser (Chromium, dev servers, API pointed at a **local stub that speaks
  Ollama's wire format with a fixed script** — UI verification only, not model
  capability): run streamed, `write_file` executed and the file existed on disk in
  the run workspace, final text and `completed · 2 steps · 933 in / 69 out tokens`
  rendered; dark/light 1440px and 390px, no horizontal overflow.
- The browser check caught a real bug the jsdom tests could not: Chromium's
  `scrollIntoView` returns a Promise, and an expression-bodied `useEffect`
  returned it, blanking the page. Fixed with block-bodied effects.

**Not tested**
- **No call to a real model yet.** This session cannot see `SEED_OLLAMA_API_KEY`
  (environment changes reach new sessions only; ollama.com returns Unauthorized).
  The model comparison and first live run happen in the "Pick the Ollama Cloud
  model" thread.
- SSE through nginx + Cloudflare in production (keepalive and 600s read timeout
  are in place, untested there).

**Known gaps:** runs are in-request and unsaved; no Markdown rendering; no
approval UI (approval-required tools are refused); no exec/shell tool until the
sandbox.

**Next:** live verification + model pick (ADR), then M3 durable tasks.

## Live model verification (2026-10-28)

**Changed:** `spikes/model-bench/bench.py` (disposable); `docs/model-strategy.md`
gains the comparison section.

**Tested:** the key works: authorized `POST https://ollama.com/api/chat`
(`gemma4:31b`) returned HTTP 200. Live runs through `OllamaProvider` + `run_agent`
on 6 models × 3 trials; results and table in `docs/model-strategy.md`
(e.g. `deepseek-v4.1-flash` 3/3, `gemma4:31b` 0/3 wrong arithmetic).

**Not tested:** the HTTP `/api/v1/runs` SSE endpoint and Chat UI against a real
model; per-token pricing (not published by the API); larger tasks.

**Open:** confirm Ollama Cloud plan limits; ADR for default model after real workloads.

## Review of live model verification (2026-10-28)

**Changed:** `.env.example` now sets `SEED_DEFAULT_MODEL=deepseek-v4.1-flash` per
ADR-0007. The code default stays unset, so Chat still asks for a model when the
variable is absent.

**Correction:** the entry above lists `spikes/model-bench/bench.py`, but that file
was never committed (merged PR #3 changed 3 docs files only). The bench script is
not reproducible from the repo; the table in `docs/model-strategy.md` is the only
record.

**Tested:** backend and frontend checks after merging PR #3 (output in CI on PR #2).

**Not tested:** `/api/v1/runs` SSE and Chat UI against a real model (this sandbox's
proxy blocks ollama.com).

## Iteration 3: Milestone 3, increment 1 — durable tasks (2026-10-28)

**Iteration:** make agent work durable: tasks persisted in Postgres, executed by a
separate worker, surviving a worker crash and an API restart.
**Definition of done:** create/list/get/cancel/retry tasks over the API; a worker
claims and runs them; a SIGKILLed worker's task is resumed by another worker from
its last checkpoint without redoing finished steps; a task survives an API restart;
cancel stops a running task; checks green.

**Changed:**
- `seed_api/flow/`: `db.py` (pool, SQL migrations), `migrations/0001_tasks.sql`,
  `store.py` (state machine, leases, fenced writes, event log), `worker.py`, `api.py`.
- `core/agent.py`: checkpoints after each completed tool round, `resume=`; cancel
  now interrupts a provider request in flight (it used to wait for the next chunk).
- `compose.yaml` adds `db` (postgres:17) and `worker`; CI runs a Postgres service.
- ADR-0008, D-004, README API/config, roadmap, requirements, CHANGELOG.

**Tested:**
- Backend with a real Postgres 16 (`SEED_TEST_DATABASE_URL` set):
  `ruff check` → `All checks passed!`; `mypy` → `Success: no issues found in 20
  source files`; `pytest -q` → `63 passed, 1 warning in 2.58s` (17 new DB tests,
  2 new agent tests). Without a DB: `46 passed, 17 skipped`.
- Mutation checks: removing the lease fence from `append_event` →
  `1 failed, 9 passed` (test_flow); removing the checkpoint call → `3 failed`.
- Real processes, real Postgres: uvicorn API + `python -m seed_api.flow.worker`
  against a scripted Ollama-wire stub (not a model). Worker 1 was `kill -9`ed
  during step 2; worker 2 resumed:
  ```
  --- before kill:
  running attempt 1 resumable_from_step 1
  worker 1 killed (SIGKILL)
  --- after:
  completed attempt 2 completed 'Wrote report.txt' {'input_tokens': 250, 'output_tokens': 15}
  2 1 attempt_started {'worker': 'vm:4790:392fed', 'resumed_at_step': None}
  6 1 tool_call {'name': 'write_file', 'step': 1}
  8 1 step_started {'step': 2}
  9 2 attempt_started {'worker': 'vm:4802:6a5862', 'resumed_at_step': 1}
  10 2 run_started {'resumed_at_step': 1}
  14 2 run_finished {'termination': 'completed'}
  ```
  (excerpt; `write_file` ran once, usage = 100+150 input tokens across attempts.)
  SIGTERM on worker 2 logged `worker … stopped`.
- `docker compose config` validates; it refuses to start without
  `SEED_POSTGRES_PASSWORD`. The built wheel contains `migrations/0001_tasks.sql`.

**Not tested:**
- The compose stack was not brought up (images not built here); CI builds them.
- Frontend unchanged and not re-run this iteration.
- A real model through the worker; the run above used a stub.
- Production: `deploy/compose.yaml` is unchanged, so the live site has no
  database and `/api/v1/tasks` answers 503 there until Postgres is added to the
  deploy (needs a password in `/opt/seed/.env`).

**Open:** deploy Postgres on the VPS (owner sets the password); next increment is
live task events over SSE with replay plus the Tasks UI.

## Iteration 4: Milestone 3, increment 2 — live Tasks screen (2026-10-28)

**Iteration:** let the owner create and follow durable tasks in the UI.
**Definition of done:** a task event stream that resumes without gaps after a
disconnect; a Tasks page (list, create, detail with live timeline, cancel, retry);
a task followed in the browser through a worker crash and recovery; checks green.

**Changed:**
- `GET /api/v1/tasks/{id}/stream` (SSE, `id:` = seq, `Last-Event-ID`/`?after=`
  resume, `event: end` when finished, 15 s keepalive, 0.5 s DB poll).
- Frontend: `lib/tasks.ts` (client, EventSource follower, event → timeline fold),
  `pages/Tasks.tsx` (list + new task, detail), routes `/tasks`, `/tasks/:id`.
- Command Center component list: SEED Core and Flow now say "Built" (they said
  "not built", which was no longer true).

**Tested:**
- Backend with Postgres: `ruff check` → `All checks passed!`; `mypy` → `Success:
  no issues found in 20 source files`; `pytest -q` → `66 passed, 1 warning`.
  New: replay+end for a finished task, resume after `Last-Event-ID`, and a stream
  opened before any work that then receives the worker's events. Mutation (stream
  ends whenever it has caught up) → `1 failed, 20 passed`.
- Frontend: typecheck and lint clean, prettier clean, `npm test` → `Tests 21
  passed (21)`, `npm run build` → `✓ built`. Mutation (drop the seq dedupe) →
  `Tests 1 failed | 2 passed (3)` in Tasks.test.tsx.
- Browser (Playwright, Chromium) against the real API, real worker processes,
  Postgres and the Ollama-wire stub (not a model): created a task in the UI,
  saw step 1's `write_file` live, SIGKILLed the worker, reloaded the page, started
  a second worker. Timeline as rendered:
  ```
  Created | Attempt 1 started | Step 1 · 100 in / 10 out | write_file | {"path":"report.txt","content":"total 541"}
  | Step 2 | interrupted | Attempt 2 resumed after step 1 | Step 2 · attempt 2 · 150 in / 5 out
  | Wrote report.txt | Finished
  details: Model stub Attempt 2 of 3 Tokens 250 in / 15 out tokens
  ```
  390 px detail and list: horizontal overflow `0`. Dark and light checked by
  screenshot. Only console error: the expected 401 from `/auth/me` before sign-in.

**Not tested:** a real model through the worker; the stream through nginx and
Cloudflare in production (no database there yet); many concurrent streams (each
polls the DB every 0.5 s).

**Open:** production Postgres (owner sets `SEED_POSTGRES_PASSWORD`); next
increment is Postgres-backed users/sessions with CSRF, then the sandbox.

## Iteration 5: Milestone 3, increment 3 — tasks on the production stack (2026-10-28)

**Iteration:** make the production compose run Postgres and the worker so tasks
work on the live site once the owner adds a database password.
**Definition of done:** `deploy/compose.yaml` brings up db, api, worker and web
from the published images; tasks persist across `down`/`up`; the deploy job fails
early and clearly without `SEED_POSTGRES_PASSWORD`; a missing provider key does
not crash-loop the worker.

**Changed:** `deploy/compose.yaml` (db, worker, shared env, `seed_pgdata` volume);
`deploy.yml` checks the required `.env` values (now including
`SEED_POSTGRES_PASSWORD`) in its own step, before the compose file is copied;
`docs/deployment.md` (VPS setup, backup/restore commands, measured resources).

**Tested** (local Docker 29.9.2; API image built from this branch, web image an
earlier local build; `.env` with random secrets, provider pointed at a closed port):
- `docker compose config` valid with the password; without it:
  `required variable SEED_POSTGRES_PASSWORD is missing a value`.
- `docker compose up -d` → `api running healthy`, `db running healthy`,
  `worker running`, `web running`.
- Through nginx on 127.0.0.1:8091: sign-in, `POST /api/v1/tasks`, the worker
  claimed it and failed it as expected (`failed 1 provider_error unavailable:
  transport error: ConnectError`); the stream returned `task_created …
  run_finished event: end`.
- `docker compose down` then `up -d`: `tasks after down/up: ['failed']` (data kept).
- Without `SEED_OLLAMA_API_KEY`: worker `state=exited restarts=5 exit=1`, log
  `No model provider is configured. Set SEED_OLLAMA_API_KEY.`
- `docker stats`: api 47.67 MiB, db 23.26 MiB, web 4.742 MiB.
- The check step's script, run locally against a temp `.env`: without the
  password `exit 1 ::error::…/.env must set SEED_POSTGRES_PASSWORD`; with it `exit 0`.

**Not tested:** the deploy workflow itself (runs only on `main`); the VPS's disk
headroom for the 424 MB Postgres image; a real model in the container.

**Open:** the owner must add `SEED_POSTGRES_PASSWORD` (and the provider key) to
`/opt/seed/.env` before merging, or the deploy job stops at the check before
changing anything on the VPS.
