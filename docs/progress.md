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

## Deploy check covers the provider key (2026-10-28)

**Changed:** the deploy job's settings check also requires `SEED_OLLAMA_API_KEY`
in `/opt/seed/.env`. Without it the deploy used to succeed while tasks could not
run (API refuses to create them; worker exits after 5 restarts), as the owner
pointed out after verifying the first production task.

**Tested:** the check step's script, extracted from the workflow and run against
temp `.env` files (output below).
```
no key line         → exit 1 ::error::/opt/seed/.env must set SEED_OLLAMA_API_KEY (see docs/deployment.md)
SEED_OLLAMA_API_KEY= → exit 1 ::error::/opt/seed/.env must set SEED_OLLAMA_API_KEY (see docs/deployment.md)
key set              → exit 0
```

**Not tested:** the workflow itself (runs on `main` only). The VPS already has the
key (owner-verified), so the next deploy passes the check.

## M3 increment 4 — Postgres users, revocable sessions, CSRF, audit log (2026-10-28)

**Iteration:** replace the M1 bootstrap auth (ADR-0004) with Postgres-backed auth
(ADR-0009), closing open question 4. **Done when:** users with argon2 hashes in
Postgres; sessions revocable server-side; a session-bound CSRF token is required
on state-changing requests and sent by the web app; sign-ins and task actions
are audited; the rate limit survives restarts; a CLI manages users; an existing
production database upgrades and its admin can still sign in.

**Changed**
- Migration `0002_auth`: `users`, `sessions`, `audit_log`.
- `seed_api/auth.py` rewritten: `AuthStore`, argon2id (dummy verify for unknown
  users, rehash on sign-in), session rows keyed by SHA-256 of the cookie token,
  `seed_csrf` cookie + `X-CSRF-Token` check (403 `csrf_failed`), per-username
  rate limit counted from `audit_log`, bootstrap admin when `users` is empty.
- `python -m seed_api.users`: add, set-password, disable, enable,
  revoke-sessions, list.
- Tasks API audits create/cancel/retry. `SEED_SESSION_SECRET` removed from
  settings, `.env.example`, docs and the deploy check.
- Web app: every request echoes the CSRF cookie in `X-CSRF-Token`.
- Two bugs found by the browser check, fixed in their own commits: signing out
  left the app on screen until a reload (`qc.clear()` detached the session
  query's observers); a queued task's cancel note did not reach the live
  timeline (the stream closed as soon as the task state turned final, before the
  event arrived; it now closes when the server ends it).
- ADR-0009, D-005, README, security, architecture, deployment, roadmap, CHANGELOG.

**Tested**
```
backend:  ruff check → All checks passed! · ruff format --check → 32 files already formatted
          mypy → Success: no issues found in 21 source files
          pytest (SEED_TEST_DATABASE_URL set) → 73 passed in 8.22s
frontend: typecheck ok · lint ok · format:check → All matched files use Prettier code style!
          vitest → Test Files 7 passed (7) · Tests 25 passed (25) · build ✓
```
Mutation checks (each change made to `auth.py`, suite run, change reverted):
```
no csrf check                 → 3 failed, 70 passed
revoked sessions accepted     → 2 failed, 71 passed
disabled users' sessions live → 2 failed, 71 passed
expiry ignored                → 1 failed, 72 passed
rate limit off by one         → 1 failed, 72 passed
disabled user can sign in     → 1 failed, 72 passed
logout does not revoke        → 1 failed, 72 passed
set-password keeps sessions   → 1 failed, 72 passed
raw token stored as id        → 19 failed, 54 passed
web: request() without CSRF header → 1 failed | 21 passed
web: old sign-out code             → 2 failed | 23 passed
web: old stream-close condition    → 1 failed | 22 passed
```
Browser (Playwright, Vite → API → Postgres):
```
cookies: seed_session httpOnly=true sameSite=Lax; seed_csrf httpOnly=false sameSite=Strict
create without token: [ 403, 'csrf_failed' ] with token: 201
cancel via app UI: timeline shows "Canceled before it started"
after sign-out, /me -> 401        (and the sign-in page shows, from / and /tasks)
```
CLI against the same database:
```
Added alice (admin).                               exit 0
error: Passwords need at least 12 characters.      exit 1
Signed admin out of 6 session(s).
Disabled alice.
admin	admin	active
alice	admin	disabled
login as alice → {"error":{"code":"invalid_credentials",…}}
audit_log (newest first): login_failed alice · user_disabled · sessions_revoked · user_added · logout
```
Production upgrade path (database with only `0001_tasks` and an existing task,
started with a short `SEED_ADMIN_PASSWORD` as a stand-in for an unknown length):
```
applied migrations: 0002_auth
WARNING SEED_ADMIN_PASSWORD is shorter than 12 characters
created bootstrap admin admin
login 200 {'username': 'admin', 'role': 'admin'}
old tasks ['old']
```

**Not tested:** the Docker images with argon2-cffi (CI builds them); the CLI
inside the read-only API container (`docker compose exec api python -m
seed_api.users …`); the deploy itself. Existing production sessions (HMAC
cookies) stop working after the deploy, so everyone signs in once more.

**Open questions:** roles beyond `admin`; a per-client sign-in limit (needs
`CF-Connecting-IP` passed through nginx); audit log retention (D-005).

## M3 increment 5 — Sandbox for the agent's commands (2026-10-29)

**Iteration:** give task agents a shell, run only in an isolated sandbox
(requirements: "model-generated shell never runs in the API process"; fs, net,
CPU, memory, time bounds). The owner picked the isolation model: one locked-down
sandbox container, not a container per command (D-006, ADR-0010). **Done when:**
the worker's tasks can run commands and use files only through the sandbox; the
sandbox has no network, no secrets and minimal privileges; tasks cannot reach
each other's files or leave processes behind; limits hold; CI checks it.

**Changed**
- `seed_api/sandbox/`: `runner` (limits, user switch, cleanup of the process
  group and every process of the task's uid), `server` (HTTP service, per-task
  workspace 0700 owned by the task's uid), `fileops` (file tools run as the task
  user), `client` (`run_command` + file tools for the worker), `protocol`.
- File operations in `core/workspace_tools.py` split out so the local tools and
  the sandbox share them.
- Worker uses sandbox tools when `SEED_SANDBOX_URL` is set.
- Both compose files: `sandbox` service (internal network only, no env file,
  `cap_drop: ALL` + SETUID/SETGID/CHOWN/KILL, no-new-privileges, read-only root,
  256 MiB tmpfs workspaces, 768 MiB / 1 CPU / 256 pids); worker joins its network.
- CI: root-only tests under sudo; container isolation check via
  `backend/scripts/sandbox_smoke.py`.
- Settings page: account hint no longer says multi-user arrives later.
- ADR-0010, D-006, README, architecture, security, deployment, roadmap, CHANGELOG.

**Tested**
```
backend: ruff check → All checks passed! · mypy → Success: no issues found in 27 source files
         pytest (DB + SEED_REQUIRE_ROOT_TESTS=1, as root) → 90 passed, 1 skipped
         (the skip is the "refuses to start without root" test, which runs only as non-root)
frontend: typecheck ok · lint ok · format ok · 25 passed
```
Found while testing and fixed: commands that left a background process behind
kept the output pipes open (now the group and the uid are killed when the
command ends); uvloop rejects `user=` (the service runs with `--loop asyncio`
and refuses to start under uvloop); the server could not `chdir` into a task's
0700 directory without `DAC_OVERRIDE` (it now changes directory after switching
user, so the server keeps no way to read workspaces).

Mutation checks (each made in `runner.py`/`server.py`, suite run, reverted):
```
no cleanup after a command    → 4 failed
no sweep of the task's uid    → 1 failed
no user switch                → 2 failed
no process limit              → 1 failed
no memory limit               → 1 failed
no CPU limit                  → 1 failed
no file-size limit            → 1 failed
environment inherited         → 1 failed
server ignores timeout cap    → 1 failed
```
Real container, from `compose.yaml` with a locally built image
(`docker compose exec -T sandbox python - < backend/scripts/sandbox_smoke.py`):
```
ok   commands run as an unprivileged per-task user
ok   commands have no capabilities
ok   no network route out
ok   no DNS resolution of outside names
ok   file write
ok   another task cannot read the file
ok   workspace root cannot be listed
ok   server's environment is unreadable
ok   root filesystem is read-only
ok   process count is capped
ok   background processes end with the command
```
Full stack (db, api, worker, sandbox):
```
worker -> sandbox: 0 hi from 28773232
api -> sandbox: unreachable URLError
sandbox env has secrets: False
sandbox -> db: unreachable gaierror
```

**Not tested:** a real model choosing to call `run_command` (the flow test uses
a scripted model through the real sandbox app); the VPS deploy; the new CI steps
themselves until this PR's run.

**Open questions:** per-task disk quota; gVisor or similar before any
multi-tenant use; which tools beyond Python and coreutils the image should carry.

## 2026-10-29 — Increment 6: M4 step 1, saved chats on durable tasks

**Iteration:** M4 step 1. Definition of done: conversations and their messages are
stored in Postgres; each message runs as a task carrying the conversation so far;
replies stream through the Tasks SSE; answers render as Markdown; the in-request
`/runs` path is removed. The owner agreed to start here ("Starting with step 1 is
fine with me").

**Changed**
- Migration `0003_conversations`: `conversations` table; `tasks` gains
  `conversation_id`, `turn`, `context` and `workspace_id` (ADR-0011).
- `seed_api/chat/`: store (start, send with a conversation row lock and
  `turn_in_progress`, list, get, turns) and `/api/v1/conversations` routes, with
  idempotency keys shared with tasks and audit entries.
- Worker: sends system + context + prompt; file tools and the sandbox use the
  task's workspace (the conversation's for a turn). Task retry is refused while
  another turn of the same conversation is unfinished.
- `runs.py` → `models.py` (provider config, system prompt, `/models`);
  `POST /api/v1/runs` and `SEED_MAX_CONCURRENT_RUNS` removed;
  `SEED_CHAT_CONTEXT_TURNS` added.
- Chat page rewritten: conversation list, `/chat/:id`, live reply from the task
  stream, past activity on demand, Markdown via react-markdown + remark-gfm (no
  raw HTML, links open with `noopener`), Stop, Try again, model switch. Chat is
  loaded lazily so other pages don't carry the Markdown code.
- ADR-0011, D-007, README, architecture, roadmap, CHANGELOG.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 44 files already formatted
         mypy → Success: no issues found in 30 source files
         pytest (DB, SEED_REQUIRE_ROOT_TESTS=1, as root) → 98 passed, 1 skipped
frontend: typecheck ok · lint ok · format ok · vitest → Tests 26 passed (26)
build: index-*.js 461.78 kB │ gzip 146.80 kB · Chat-*.js 174.93 kB │ gzip 53.12 kB
       (main before this change: 467.50 kB │ gzip 147.77 kB)
```
Mutation checks (each change made, suite run, reverted):
```
backend
worker drops the context                         → CAUGHT (1 failed)
worker uses the task id as workspace             → CAUGHT (1 failed)
retry ignores unfinished sibling turns           → CAUGHT (1 failed)
send ignores an unfinished turn                  → CAUGHT (1 failed)
failed turns included in context                 → CAUGHT (1 failed)
context not limited to the last N turns          → CAUGHT (1 failed)
get ignores the owner                            → CAUGHT (1 failed)
list ignores the owner                           → CAUGHT (1 failed)
replay accepts a lone task's key                 → CAUGHT (1 failed)
replay accepts another conversation's key        → CAUGHT (1 failed)
/tasks replay accepts a chat turn's key          → CAUGHT (1 failed)
frontend
stream duplicates not dropped                    → CAUGHT (1 failed)
links without rel=noopener                       → CAUGHT (1 failed)
model switch not sent                            → CAUGHT (1 failed)
live text not rendered as Markdown               → CAUGHT (1 failed)
stream end does not refresh the conversation     → CAUGHT (1 failed)
Enter sends while an answer is running           → CAUGHT (1 failed)
```
Browser (Chromium via Playwright; API, one worker, Postgres, Vite dev server,
and an Ollama-wire stub that streams Markdown, not a model):
```
url /chat/a84fd407-9120-469d-8143-d2831bd4e69d
live: stop button visible = true
meta: 250 in / 50 out tokens
turn 1: Done | I can see 0 earlier messages in this conversation. | first point | second point | code block |
heading tag: Done | strong: 0 earlier messages
turn 2: Done | I can see 2 earlier messages in this conversation. | first point | second point | code block |
list: Make a file notes.md with my checklist
turns after reload: 2
horizontal overflow at 390px: 0
errors: ["Failed to load resource: the server responded with a status of 401 (Unauthorized)"]
```
The second message was sent, then the page went to Tasks for 6 s and came back:
the answer had arrived meanwhile. The 401 is the signed-out `/auth/me` before
sign-in. Database afterwards: both turns `completed`, turn 2 carried 2 context
messages, `workspace_id` equals the conversation id, and `notes.md` written by
turn 1 sits in `<workspace_root>/<conversation id>/`.

**Not tested:** a real model (this session has no Ollama key); chat turns through
the sandbox container (the sandbox API is unchanged and the flow test covers a
task through the real sandbox app); the deploy.

**Open questions:** in D-007 (conversation privacy once there are other roles;
token-based context limits). If you press Enter before the model list has
loaded, nothing is sent and the text stays in the box.

## 2026-10-29 — Fix: the last step of a run answers without tools

**Iteration:** fix for the owner's manual tests 9 and 10 (runbook), which ended
"Stopped: step limit reached" with no answer (22005 in / 4679 out and 31607 in /
7777 out tokens on deepseek-v4.1-flash). Definition of done: a run that spends
its steps on tools still ends with an answer; tested and able to fail.

**Changed:** `core/agent.py`: on the last allowed step (when `max_steps` > 1) the
request carries no tools and a `WRAP_UP` system note, not stored in the history;
`step_started` carries `wrap_up: true`; a tool call on that step ends the run
`max_steps` without running it. Tests in `test_agent.py`; README, CHANGELOG, D-008.

**Tested**
```
backend: ruff check → All checks passed! · mypy → Success: no issues found in 30 source files
         pytest (DB, SEED_REQUIRE_ROOT_TESTS=1, as root) → 100 passed, 1 skipped
```
Mutation checks on `core/agent.py`:
```
never wrap up                          → 2 failed
wrap up on a one-step run too          → 1 failed
run tool calls on the wrap-up step     → 1 failed
```

**Not tested:** the real model on the wrap-up step (no key in this session). Which
tools the failed runs used is not confirmed yet; asked the owner for their timeline.

## 2026-10-29 — Increment 7: M4 step 2, approvals for commands

**Iteration:** M4 step 2. Definition of done: a gated tool call pauses its task in a
"waiting" state that holds no worker; Chat and the task page show the exact call with
Approve/Deny; the run resumes from its checkpoint after the decision; a denied call
never runs. The owner picked "Commands only" as the default (D-009).

**Changed**
- `core/agent.py`: `approvals` argument; pause at the first undecided gated call
  (`approval_requested` event, checkpoint with `pending`, termination
  `awaiting_approval`); on resume run the pending calls (denied → `denied` result).
- `core/tools.py`: a gated tool runs only with `approved=True`.
- Migration `0004_approvals`: state `waiting`, `awaiting_approval`, `approvals`.
- `flow/store.py`: `pause`, `decide`; cancel ends waiting tasks; retry and chat
  treat waiting as unfinished. `flow/worker.py`: gates tools from
  `SEED_APPROVAL_REQUIRED_TOOLS`, passes decisions, parks the task.
- `POST /api/v1/tasks/{id}/decision` (audited with tool and arguments).
- Web: `ApprovalPrompt` in Chat and on the task page, "needs you" badges in the
  task list and conversation list, timeline notes; a step's paused call now gets
  its result after the decision in the timeline.
- ADR-0012, D-009, README, security, roadmap, CHANGELOG.

**Tested**
```
backend: ruff check → All checks passed! · mypy → Success: no issues found in 30 source files
         pytest (DB, SEED_REQUIRE_ROOT_TESTS=1, as root) → 109 passed, 1 skipped
frontend: typecheck ok · lint ok · format ok · vitest → Tests 31 passed (31)
```
Mutation checks (each made, suite run, reverted):
```
agent never pauses                       → CAUGHT     registry ignores approval   → CAUGHT
denied call runs anyway                  → CAUGHT     pause counts the attempt    → CAUGHT
paused call announced twice              → CAUGHT     decide ignores the call id  → CAUGHT
checkpoint drops pending calls           → CAUGHT     retry ignores waiting turn  → CAUGHT
cancel leaves waiting tasks waiting      → CAUGHT     chat ignores waiting turn   → CAUGHT
worker ignores the setting               → CAUGHT     worker drops decisions      → CAUGHT
pendingApproval ignores decisions        → CAUGHT     Deny sends approve          → CAUGHT
buttons stay enabled after deciding      → CAUGHT
```
Browser (Chromium; API, worker, the real sandbox server as root with per-workspace
users, Postgres, an Ollama-wire stub that always asks to run one command):
```
card: SEED wants to run a command | echo built > out.txt && id -u && cat out.txt | It runs in the sandbox for this workspace, with no network access. Nothing happens until you choose. | Approve | Deny
list badge: yes
sandbox files before approval: []
card survives reload: yes
answer 1: Tool said: {"exit_code": 0, "signal": null, "stdout": "533142801\nbuilt\n", ...
tasks list shows needs you: yes
timeline: ... Step 1 · 50 in / 5 out | run_command | 0 ms | {"command":"echo built > out.txt && id -u && cat out.txt"} | The user denied this action. Do not try it again; continue without it. | Waiting for your approval to run run_command | Paused for your approval | Denied by admin | Attempt 1 resumed after step 1 | Step 2 ... | Finished
errors: []
```
Audit log afterwards: `tool_approved` and `tool_denied` rows, each with
`{"tool": "run_command", "arguments": {"command": "echo built > out.txt && id -u && cat out.txt"}}`.
The command ran as uid 533142801 (the workspace's user) only after Approve.

**Not tested:** a real model's reaction to a denial (no key here); the compose stack
and the deploy.

**Open questions:** "approve all for this chat"; per-command allow lists; who may
approve once roles exist (D-009).

## 2026-10-29 — Increment 8: M4 step 3a, rename, delete and search conversations

**Iteration:** M4 step 3a (step 3 split: edit/regenerate is 3b). Definition of done:
a conversation can be renamed (its turns follow), deleted with its turns and events
after a confirm, never while a turn is unfinished, and found by a word in its title,
messages or answers; each is audited and owner-scoped.

**Changed**
- `chat/store.py`: `rename`, `delete` (conversation lock, refuses unfinished turns),
  `list(query=)` with literal `%`/`_`.
- `chat/api.py`: `PATCH` and `DELETE /api/v1/conversations/{id}`, `?q=` on the
  list; audit `conversation_renamed` (title) and `conversation_deleted` (turn count).
- Web: search box in the conversation list (250 ms pause before searching), title
  header with Rename and Delete (inline confirm; disabled while answering).
- D-010, README, security (workspace files outlive a deleted conversation),
  roadmap, requirements WS-2, CHANGELOG.

**Tested**
```
backend: ruff check → All checks passed! · mypy → Success: no issues found in 30 source files
         pytest (DB) → 115 passed, 1 skipped
frontend: typecheck ok · lint ok · format ok · vitest → Tests 35 passed (35)
```
Mutation checks (each made, suite run, reverted):
```
search wildcards not escaped        → CAUGHT     rename leaves turn titles   → CAUGHT
rename bumps updated_at             → CAUGHT     delete ignores busy turns   → CAUGHT
delete ignores the owner            → CAUGHT     search skips answers        → CAUGHT
title over 80 chars accepted        → CAUGHT     delete not audited          → CAUGHT
delete without the confirm          → CAUGHT     search on every keystroke   → CAUGHT
title whitespace not collapsed      → CAUGHT     delete enabled while busy   → CAUGHT
```
Browser (Chromium; API, worker without sandbox, Postgres, Ollama-wire stub):
```
delete disabled while answering: true
renamed survives reload: yes
tasks list shows new title: yes
search "earlier messages": Lisbon trip | Plan a garden
search "garden": Plan a garden
search "50%": Lisbon trip
search "zzz": No conversations match “zzz”.
confirm: Delete this conversation and its 1 message? Their timelines go too. This cannot be undone. | Delete | Keep
after delete list: Lisbon trip
deleted url shows: No such conversation
390px horizontal overflow px: 0
errors: [401 before sign-in, 404 for the deleted conversation — both expected]
```

**Not tested:** the compose stack and the deploy; search speed with many
conversations (a sequential scan, D-010).

**Open questions:** delete a conversation's workspace files with it; search
snippets and ranking (D-010).

## 2026-10-29 — Increment 9: M4 step 3b (part 1), message versions in the API

**Iteration:** M4 step 3b, first of two PRs. The owner chose "any message, keep
versions" (D-011). Definition of done: any message can be edited or regenerated as
a new version that keeps the turns above it and leaves older versions intact; the
conversation shows one path and can switch to any version; existing conversations
migrate unchanged; the one-unfinished-turn rule holds across versions. Chat
controls are the next PR, so the UI here is unchanged (it shows the path).

**Changed**
- Migration `0005_versions`: `tasks.parent_id`, `conversations.head_id`, backfill,
  `UNIQUE(conversation_id, turn)` replaced by a parent/turn CHECK.
- `chat/store.py`: `send` continues the shown path; `add_version`, `show`;
  `turns` returns the shown path with each turn's versions; listing by head.
- `chat/api.py`: `POST …/turns/{turn_id}/versions`, `PUT …/shown`, `versions` on
  turns; the new version is audited as `task_created` with `{version_of, edited}`.
- ADR-0013, D-011, README, CHANGELOG, roadmap.

**Tested**
```
backend: ruff check → All checks passed! · mypy → Success: no issues found in 30 source files
         pytest (DB) → 119 passed, 1 skipped
```
Migration on a database holding 0004-era chats (the e2e database plus a
three-turn conversation inserted the old way), then read through the new store:
```
applied: ['0005_versions']
Old three-turn chat | turns 3 completed | path [(1, 'p1', 1), (2, 'p2', 1), (3, 'p3', 1)]
Lisbon trip | turns 1 completed | path [(1, 'Holiday in Lisbon 50', 1)]
```
Mutation checks (each made, suite run, reverted):
```
version's context includes the old answer → CAUGHT   send ignores the shown path      → CAUGHT
show follows the oldest reply             → CAUGHT   show while a turn is unfinished  → CAUGHT
version while a turn is unfinished        → CAUGHT   turns report no other versions   → CAUGHT
list counts every version                 → CAUGHT   version nested under its target  → CAUGHT
new version not made the head             → CAUGHT
```
(The first run let "send ignores the shown path" survive; the test now sends after
switching back to an older version.)

**Not tested:** the migration inside the compose stack and the deploy; the backfill
has no automated test (checked by hand above).

**Open questions:** whether the Tasks list should group a message's versions (D-011).

## 2026-10-29 — Increment 9 (part 2): version controls in Chat

**Iteration:** M4 step 3b, second part. Definition of done: Edit under every
finished message and Regenerate under every answer create a new version; arrows
with "n / m" switch versions; nothing can be edited, regenerated or switched while
a message is being answered; the choice survives a reload.

**Changed**
- `lib/chat.ts`: `Turn` (task + `versions`), `addVersion`, `show`.
- `pages/Chat.tsx`: `Versions` arrows, inline edit (Escape cancels; "Sent as a new
  version; this one is kept."), Regenerate; a new version stays pending until the
  conversation is refetched, so the controls stay locked until it shows.
- README, CHANGELOG, roadmap, requirements WS-2, D-011 note (one PR, two commits).

**Tested**
```
frontend: typecheck ok · lint ok · format ok · vitest → Tests 37 passed (37)
build: Chat chunk 182.85 kB (55.17 kB gzip); main bundle unchanged at 147.48 kB gzip
```
Mutation checks (each made, suite run, reverted):
```
arrows work while answering     → CAUGHT     Edit on an unfinished message   → CAUGHT
regenerate sends a prompt       → CAUGHT     Previous shows the next version → CAUGHT
controls unlocked while answering → CAUGHT   Regenerate only on the last one → CAUGHT
Escape does not cancel the edit → CAUGHT
```
Browser (Chromium; API with migration 0005, worker, Postgres, Ollama-wire stub
whose answer states how many earlier messages it was sent):
```
before edit, earlier-message counts: [ '0', '2' ]
while answering: edit buttons = 1 all disabled = true | prev disabled = true
after edit: Version 2 of 2 | counts: [ '0', '2' ] | tomatoes shown: 0
switched back: Version 1 of 2
after reload still shows: Add tomatoes
regenerated first: Version 2 of 2 | turns shown: 1 | counts: [ '0' ]
back to first version follows newest reply: Add peppers
tasks list rows: 4
390px horizontal overflow px: 0
errors: [401 before sign-in, expected]
```
The edited second message was sent with the two messages before it, not the old
answer; the regenerated first message was sent with none.

**Not tested:** a real model; the compose stack and the deploy.

## 2026-10-29 — Increment 10: M5 step 1, Command Center from live tasks

**Iteration:** M5 step 1. Definition of done: the Command Center shows only real
data from the task store: counts, what needs a person (waiting approvals, recent
failures), running and queued work, recent completions and tokens by model, with
honest empty states and no spend figure (no prices exist); it refreshes itself.

**Changed**
- `flow/overview.py`: `GET /api/v1/overview?hours=` (one database clock per
  snapshot; capped lists).
- Web: `lib/overview.ts`, Command Center stat tiles and panels; `StateBadge` moved
  to `components/tasks` and shared with Tasks.
- D-012, README, CHANGELOG, roadmap, requirements WS-1.

**Tested**
```
backend: ruff check → All checks passed! · mypy → Success: no issues found in 31 source files
         pytest (DB) → 123 passed, 1 skipped
frontend: typecheck ok · lint ok · format ok · vitest → Tests 40 passed (40)
```
Mutation checks (each made, suite run, reverted):
```
old failures not filtered out        → CAUGHT   waiting not listed first          → CAUGHT
usage counts unfinished tasks        → CAUGHT   completed ignores the window      → CAUGHT
queued listed newest first           → CAUGHT   lists not capped                  → CAUGHT
window ignores ?hours                → CAUGHT   chat turn links to the task page  → CAUGHT
approval row hides the tool name     → CAUGHT   "x ago" not computed              → CAUGHT
token counts not formatted           → CAUGHT
```
(The first run of "completed ignores the window" had no old completed task to
catch it; the test now has one.)

Browser (Chromium; API, worker, Postgres, Ollama-wire stub). Two chats answered
for real; the waiting and failed states were then set by SQL, because this
environment has no sandbox and no failing model:
```
empty: Running | 0 | Queued | 0 | Need you | 0 | Completed (24h) | 0 | Failed (24h) | 0
in progress while answering: In progress | Long job | stub · started just now | queued
after auto-refresh, in progress: In progress | No active work | Running and queued tasks appear here.
stats: Running | 0 | Queued | 0 | Need you | 1 | Completed (24h) | 1 | Failed (24h) | 1
attention: Needs attention | 2 | Plan a garden | Wants to run run_command | needs you | Write a packing list | provider_error: auth: Unauthorized | failed
recent: Recently completed | Long job | stub · 190 tokens · just now | completed
usage: Model usage (24h) | Model Tasks In tokens Out tokens | stub 2 300 80 | Spend is not shown: no model prices are configured.
db usage: stub|2|300|80
approval row opens: /chat/76672ddf-3e7f-45e1-9084-5c1909823e6c
390px horizontal overflow px: 0
```

**Not tested:** a real failed run or real approval on this page (states were set
by SQL); the compose stack and the deploy; query time with a long task history.

**Open questions:** model prices and the monthly budget, needed for spend (D-012).

## 2026-10-29 — Increment 11: M5 step 2, Execution Inspector

**Iteration:** M5 step 2. Definition of done: `/inspector` lists tasks and
`/inspector/{id}` shows, from recorded events only, a task's attempts, model
steps (time, tokens, finish reason, retries), tool calls (arguments, result,
time, approval), checkpoints and its event log; no reasoning is shown; a running
task refreshes; checkpoints are logged as events.

**Changed**
- `flow/store.py`: `save_checkpoint` logs `checkpoint_saved {steps, pending}` in
  the same transaction as the save.
- Web: `lib/inspector.ts` (`inspect()` folds events), `tasksApi.allEvents`
  (reads every page), `pages/Inspector.tsx` (list and task pages); the Inspector
  placeholder is gone.
- D-013, README, CHANGELOG, roadmap, requirements WS-7.
- Found while testing: provider retries are logged after `step_started`, so they
  are charged to the step in progress; Ollama call ids repeat per step, so
  results match the newest call with that id (a first draft de-duplicated calls by
  id and would have hidden later steps' calls).

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 46 files already formatted
         mypy → Success: no issues found in 31 source files
         pytest (DB) → 123 passed, 1 skipped (test_sandbox.py:208, checks the non-root refusal)
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 9 passed (9), Tests 49 passed (49)
```
Mutation checks (each made, tests run, reverted):
```
allEvents stops after one page                     → CAUGHT
event log lists text deltas                        → CAUGHT
result matched to the first call with a reused id  → CAUGHT
retry charged to no step                           → CAUGHT
ending applied to first run with that number       → CAUGHT
tool result ignored                                → CAUGHT
approval decision ignored                          → CAUGHT
checkpoint pending count dropped (web)             → CAUGHT
pending count dropped (backend)                    → CAUGHT
checkpoint not logged                              → CAUGHT
seq not bumped (event collides)                    → CAUGHT
```
(The first mutation run had two survivors, a tool-call de-dupe and the web
pending count; the de-dupe was the bug above, and the tests now cover both.)

Browser (Chromium; API, worker, Postgres, Ollama-wire stub that answers 429 once,
then writes two files, lists files, and replies):
```
empty list: No executions recorded
Summary: Model | stub | Attempts | 1 of 3 | Duration | 1s | Model steps | 3 | Tool calls | 3 | Tokens | 200 in / 21 out | Time in model | 7 ms | Time in tools | 0 ms | Provider retries | 1 | Checkpoint | after step 2 | Ended | completed
Attempts: 1	05:41:00 AM	vm:28672:ef01f5	—	05:41:01 AM	completed
Model steps: 1 1 4 ms 50 7 tool_calls 2 1 | 1 2 1 ms 70 7 tool_calls 1 0 | 1 3 2 ms 80 7 stop 0 0
Tool calls: 1 write_file {"path":"a.txt","content":"alpha"} ok | 1 write_file {"path":"b.txt","content":"beta"} ok | 2 list_files {} ok
Checkpoints: 05:41:01 AM 1 1 0 | 05:41:01 AM 1 2 0
event log types: task_created attempt_started run_started step_started provider_retry step_completed tool_call tool_result tool_call tool_result checkpoint_saved step_started step_completed tool_call tool_result checkpoint_saved step_started step_completed run_finished
db tool_call ids: 8|1|call_0|write_file · 10|1|call_1|write_file · 15|2|call_0|list_files
390px horizontal page scroll: false
console errors: one 401 from the sign-in check before login
```

**Not tested:** in the browser, a crashed or paused-and-resumed run (covered by
unit tests on a recorded-shape log, and by the backend checkpoint tests); the
compose stack and the deploy; load time for a task with many thousands of events.

**Open questions:** which milestone owns verification evidence in the Inspector
(D-013); model prices for cost.


## 2026-10-29 — Research: Ollama Cloud pricing and spend API (docs only)

**Definition of done:** find out whether Ollama Cloud costs are published and
whether spend can be read by API; record it.

**Changed:** `docs/decisions.md` (D-014), `docs/roadmap.md` (M5 row). No code.

**Tested:** read https://ollama.com/pricing and the Ollama docs pages for
balance and cloud usage. One read-only call with the deploy key:
```
GET https://ollama.com/api/balance -> HTTP 200
{"included":{"balance_usd":12.24676,"allowance_usd":60,"period":{"from":"2026-10-11T07:31:35Z","until":"2026-11-11T07:31:35Z"}},"purchased":{"balance_usd":0}}
```

**Not tested:** `/api/usage` (not called); that the token counts SEED stores
reproduce Ollama's billed figures; the legacy-plan response shape.

**Open questions:** the monthly budget; with about $12 of $60 left, whether to
top up before heavier testing.

## 2026-10-29 — Increment 12: M6 step 1 (part 1), saved files with versions

**Iteration:** M6 step 1, part 1. Definition of done: after every run the worker
saves each file the run created, changed or deleted as a new version on
persistent storage, without touching the task's outcome when saving fails; a
workspace that comes back empty is refilled before the next run; this works
through the sandbox as the task's own user.

**Changed**
- `studio/` (new): `files.py` (snapshot, read/write bytes), `workspace.py`
  (sandbox and local adapters), `store.py` (blobs by SHA-256, versions in
  Postgres), `capture.py` (save changes, restore).
- Migration `0006_artifacts`; worker saves after each run and restores before it;
  sandbox file ops `snapshot`, `read_bytes`, `write_bytes`; `SEED_ARTIFACT_ROOT`.
- Compose files: `artifacts` volume on the worker; Dockerfile creates its mount
  point owned by the app user.
- `workspace_tools._resolve` renamed `resolve` (now shared).
- ADR-0014, D-015, README, CHANGELOG, roadmap, requirements WS-6, deployment.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 52 files already formatted
         mypy → Success: no issues found in 36 source files
         pytest (DB) → 129 passed, 1 skipped (test_sandbox.py:208, the non-root check)
```
Mutation checks (each made, tests/test_artifacts.py run, reverted):
```
unchanged files saved again                 → CAUGHT   deletions never recorded                  → CAUGHT
deletions recorded from a cut-off listing   → CAUGHT   large files saved without a report        → CAUGHT
restore into a non-empty workspace          → CAUGHT   restore brings back deleted files         → CAUGHT
version numbers not incremented             → CAUGHT   latest picks the oldest version           → CAUGHT
blob stored under the wrong name            → CAUGHT   snapshot lists symlinks                   → CAUGHT
save skipped by the worker                  → CAUGHT   restore skipped by the worker             → CAUGHT
save failure fails the task                 → CAUGHT   write_bytes skips base64 validation       → CAUGHT
logs an event when nothing changed          → CAUGHT
```
(The first run had "blob stored under the wrong name" surviving; the test now
checks the on-disk layout.)

Sandbox with real per-task users (run as root, `SEED_SANDBOX_ISOLATE_USERS=true`):
```
owner uid: 851968396 expected 851968396
snapshot a: [('dir/x.bin', 6)]
read back ok: True
snapshot b (symlink into a): []
read through symlink refused: Path escapes the workspace.
```
Docker named volume on the image's mount point, as the non-root user (uid 10001),
read-only root filesystem:
```
10001
-rw-r--r-- 1 10001 999 3 Oct 29 09:02 x
hi            (read back through a :ro mount)
```
Real API + worker + Postgres with the Ollama-wire stub, local workspaces:
```
turn 1: completed | artifacts_saved: [{'saved': [{'path': 'a.txt', 'deleted': False, 'version': 1}, {'path': 'b.txt', 'deleted': False, 'version': 1}], 'skipped': [], 'truncated': False}]
blobs on disk: ['8ed3f6ad685b', 'f44e64e75f39']
workspace wiped (as a sandbox restart would)
turn 2: completed | workspace_restored: [{'files': 2}] | artifacts_saved: []
files now: ['a.txt', 'b.txt']
db versions: a.txt v1 8ed3f6ad685b | b.txt v1 f44e64e75f39
```

**Not tested:** the full compose stack (the images were not built here); a real
sandbox container restart; save time for a workspace near the 500-file cap.

**Open questions:** cleanup of content left by deleted conversations (ADR-0014).

## 2026-10-29 — Increment 13: M6 step 1 (part 2), Studio

**Iteration:** M6 step 1, part 2. Definition of done: Studio lists saved files by
chat or task; a file's page shows its versions (with the run that made each), its
text or image, and downloads; HTML runs as a preview of the latest files without
access to SEED's session, storage, page or network; saved versions opened
directly never run; task timelines say which files were saved.

**Changed**
- `studio/api.py` (artifacts list, detail, version content, preview links,
  preview files), `ArtifactStore` reads, migration `0007_previews`.
- Web: `lib/studio.ts`, `pages/Studio.tsx` (list and file pages; the Studio
  placeholder is gone), timeline notes for `artifacts_saved`,
  `workspace_restored`, `artifacts_failed`; `mockApi` can return raw text.
- nginx: `/api/v1/previews/` gets its own headers. Compose: the API mounts the
  artifact volume read-only; `SEED_ARTIFACT_ROOT` moved to the shared env.
- ADR-0015, D-016, README, CHANGELOG, roadmap, requirements WS-6, deployment.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 54 files already formatted
         mypy → Success: no issues found in 37 source files
         pytest (DB) → 134 passed, 1 skipped (test_sandbox.py:208, the non-root check)
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 10 passed (10), Tests 56 passed (56)
nginx -t (nginx:alpine) → syntax is ok, test is successful
```
Mutation checks (each made, tests run, reverted):
```
preview sent without its sandbox CSP            → CAUGHT   preview CSP shares SEED's origin       → CAUGHT
version content can run scripts                 → CAUGHT   expired preview links still work       → CAUGHT
preview reaches other workspaces                → CAUGHT   token stored in plain                  → CAUGHT
download served inline                          → CAUGHT   deleted version served                 → CAUGHT
listing ignores the conversation filter         → CAUGHT   listing shows the oldest as latest     → CAUGHT
preview of a deleted file allowed               → CAUGHT   iframe shares SEED's origin            → CAUGHT
preview offered for old versions                → CAUGHT   download link opens inline             → CAUGHT
timeline hides deletions                        → CAUGHT   deleted version offered for download   → CAUGHT
```
(The first run had "preview offered for old versions" surviving: the frame from
the earlier preview stayed up. The test now checks the frame is gone too.)

Browser (Chromium) against the built app served by nginx with the committed
config, real API, worker and Postgres, and an Ollama-wire stub that writes a
small site (`index.html` linking `style.css` and `app.js`), then changes its
heading. `app.js` tries to read cookies, use storage, reach its parent and fetch
`/api/v1/auth/me`:
```
empty: No saved files yet
studio list: Build a garden planner site | Open chat | site/index.html | 2 versions · 212 B | site/app.js | 1 version · 619 B | site/style.css | 1 version · 29 B
versions: v2 10/29/2026, 9:15:26 AM 212 B Inspect run | v1 10/29/2026, 9:15:24 AM 209 B Inspect run Show v1
preview heading: Garden planner v2 | colour: rgb(200, 0, 0)
preview script: script ran | cookie blocked | storage blocked | parent blocked
preview network: fetch blocked
preview origin: null
download name: index.html
direct open CSP: <nginx app CSP>, sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'
direct open script ran: script did not run
v1 shows old heading: yes
390 px overflow: artifact page 0, list 0 (first run: 44 px, from the versions
table's screen-reader label escaping its scroller; fixed)
```
Console errors: the expected CSP blocks from the preview's fetch, the 401 from the
sign-in check before login, and a `data:` font blocked by nginx's `font-src
'self'` on every page. That font block predates this change and is not fixed here.

**Not tested:** previews in Firefox and Safari; the deployed stack behind the
Cloudflare tunnel; a preview link after it expires, in the browser (the API test
covers it).

**Open questions:** whether to allow `data:` fonts in the app's CSP (the existing
block above).

## Session: Command Center overflow on narrow screens

**Iteration:** Fix horizontal overflow of the Command Center at ~390 px (reported from a phone screenshot). Done = no horizontal overflow at 390 px on the Command Center, and other pages checked.

**Changed**
- `frontend/src/pages/CommandCenter.tsx`: the page grid and the work-panels grid now use an explicit single column (`grid-cols-1`) and the column wrappers have `min-w-0`. Cause: a grid without `grid-template-columns` gets an `auto` track, which grows to its widest child's min-content (long task titles), so `<main>` was 621 px wide inside a 390 px viewport.

**Tested**
```
Chromium 390x844, vite dev, API mocked (long task titles, failed/completed rows):
before: / main scrollWidth 621 (viewport 390)
after:  / main scrollWidth 390; /tasks /chat /studio /settings /inspector /memory /agents all 390 (no overflow)
frontend: typecheck ok · lint ok · format ok · vitest passes (see run in PR)
```

**Not tested:** other widths (320, tablets); real data on the live site; Safari/Firefox. No automated regression test: jsdom has no layout, so it cannot fail on this bug. `/tasks` and `/chat` have no `<main>` measured in the script's mock (empty/loading state); the page-level scrollWidth was 390.

**Open questions:** none.

## 2026-10-29 — Increment 14: M6 step 2 (part 1), projects

**Iteration:** M6 step 2, part 1. Definition of done: projects can be created,
renamed and deleted (their chats kept); a project has instructions that reach the
model on every message sent in it, fixed per message so retries see the same; a
chat can start in a project or be moved in and out; a project's page lists its
chats and their saved files.

**Changed**
- Migration `0008_projects` (projects, `conversations.project_id`,
  `tasks.instructions`); `projects/` (store, API); chat start/move/list take a
  project; Studio's listing filters by project; the worker's system prompt adds
  the turn's instructions (`models.system_prompt`).
- Web: `lib/projects.ts`, `pages/Projects.tsx` (list and project pages; the
  Projects placeholder is gone), Chat starts in `?project=` and its header moves a
  chat.
- D-017, README, CHANGELOG, roadmap, requirements WS-5.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 58 files already formatted
         mypy → Success: no issues found in 40 source files
         pytest (DB) → 139 passed, 1 skipped (test_sandbox.py:208: checks the non-root refusal)
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 11 passed (11), Tests 63 passed (63)
```
Mutation checks (each made, tests run, reverted), backend 14/14 caught:
```
worker ignores the turn's instructions     → CAUGHT   new turns skip the instructions       → CAUGHT
another owner's project instructions used  → CAUGHT   move skips the project check          → CAUGHT
conversation list ignores the project      → CAUGHT   Studio ignores the project filter     → CAUGHT
rename wipes the instructions              → CAUGHT   delete reaches another owner's        → CAUGHT
get reaches another owner's                → CAUGHT   deleting a project deletes its chats  → CAUGHT
system prompt leaves instructions out      → CAUGHT   instructions not trimmed              → CAUGHT
name over 80 characters accepted           → CAUGHT   start ignores project_id              → CAUGHT
```
Frontend 12/12 caught: new chat drops the project; move always sends null;
instructions saved as the name; box not refreshed after save; Save always enabled;
files list shows every file; delete without a confirm; chat links lose their id;
"New chat" loses the project; name sent untidied; chats list ignores the project;
delete confirm says chats are deleted.

Browser (Chromium) on the Vite dev server with the real API, worker, Postgres and
artifact store, and an Ollama-wire stub that writes `note.txt` and then answers
with the project instructions it received:
```
turn 1 answer: Instructions seen: Answer in French.
project select: Launch site
turn 2 answer (moved out): Instructions seen: none
chats: Chats | New chat | Write a note | 2 messages
files: Files | note.txt | Write a note | 2 B
overflow at 390px on /projects/<id>: 0
overflow at 390px on /projects: 0
chat header overflow at 390: 0
errors: the 401 from the sign-in check before login
```

**Not tested:** the nginx build and compose stack (no nginx or compose change in
this increment); Firefox and Safari.

**Open questions:** none new. Memory follows (agent proposes, owner approves).

## 2026-10-29 — Increment 15: M6 step 2 (part 2), project memory

**Iteration:** M6 step 2, part 2. Definition of done: in a project's chats the
agent can propose a memory note but not save one; the owner approves, edits or
rejects proposals and adds, edits and deletes notes on the project page; only
approved notes reach the model, in that project only, within a budget; a retried
run proposes nothing twice; the owner can see that proposals wait.

**Changed**
- Migration `0009_memory` (`project_memories`, `tasks.project_id`, `tasks.memory`);
  `projects/memory.py` (store, `remember` tool, prompt budget); owner endpoints
  under `/api/v1/projects/{id}/memories`; `proposed_memories` on projects; turns
  copy approved notes; the worker offers `remember` in project turns and adds the
  notes to the system prompt.
- Web: Memory panel on the project page, "to review" badge on the projects list,
  "Memory to review" link in a project chat's header.
- D-018, README, CHANGELOG, roadmap, requirements WS-5.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 60 files already formatted
         mypy → Success: no issues found in 41 source files
         pytest (DB) → 145 passed, 1 skipped (test_sandbox.py:208: checks the non-root refusal)
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 11 passed (11), Tests 67 passed (67)
```
Mutation checks (each made, tests run, reverted), backend 16/16 caught:
```
proposals reach the model                  → CAUGHT   prompt budget ignored                 → CAUGHT
no per-task proposal limit                 → CAUGHT   duplicate proposals stored            → CAUGHT
agent notes saved as approved              → CAUGHT   agent note whitespace not tidied      → CAUGHT
owner adds to another owner's project      → CAUGHT   delete reaches other projects' notes  → CAUGHT
any edit approves                          → CAUGHT   proposals not listed first            → CAUGHT
remember offered outside projects          → CAUGHT   worker leaves memory out              → CAUGHT
turns copy no memory                       → CAUGHT   proposal count includes approved      → CAUGHT
approval audited as an update              → CAUGHT   owner note whitespace not tidied      → CAUGHT
```
Frontend 10/10 caught: Approve sends nothing; "Save and approve" does not approve;
proposals hidden; Approve shown on approved notes; added note not tidied; input
not cleared; "to review" badge missing; provenance line missing; chat header link
missing; Reject sends PATCH instead of DELETE.

Browser (Chromium) on the Vite dev server with the real API, worker and Postgres,
and an Ollama-wire stub that calls `remember` on "remember …" and otherwise
answers with the memory notes and tools it was sent:
```
turn 1: Tool said: {"status": "proposed", "note": "Waiting for the owner to approve it on the project page."}
chat header shows: Memory to review
turn 2 (before approval): Memory seen: none | tools: list_files,read_file,write_file,remember
waiting: Waiting for you (1) | The site uses plain CSS. | Proposed by SEED in its chat | Approve | Edit | Reject
remembered: Stephen prefers short answers. | Added by admin | Edit | Delete | The site uses plain CSS. | Proposed by SEED in its chat | Edit | Delete
turn 3 (after approval): Memory seen: - Stephen prefers short answers. - The site uses plain CSS. | tools: list_files,read_file,write_file,remember
chat outside project: Memory seen: none | tools: list_files,read_file,write_file
overflow at 390 on project page: 0
errors: the 401 from the sign-in check before login
```

**Not tested:** a real model choosing to call `remember` (the stub calls it on
cue); the compose stack (no compose or nginx change); Firefox and Safari.

## 2026-10-29 — Increment 16: rendered output by default

**Iteration:** outside the roadmap, requested by the owner (D-019). Definition of
done: Markdown, tables and HTML in chat answers, task results and Studio show
rendered first with a switch to the source; HTML is responsive and opens at the
viewer's device width with a switch to the other; Studio's frame keeps its
isolation.

**Changed**
- `lib/render.ts` (fence kinds, HTML preparation, frame layout),
  `components/ui/Rendered.tsx` (switches, `HtmlFrame`), `Markdown` (fenced blocks,
  whole-page HTML, `toggle`, `live`); Chat and Tasks results use it; Studio's HTML
  preview starts on open and Markdown files render.
- System prompt asks for responsive, self-contained HTML. D-019, README, CHANGELOG.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 58 files already formatted
         mypy → Success: no issues found in 40 source files
         pytest tests/test_projects.py (no DB here) → 1 passed, 5 skipped
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 13 passed (13), Tests 81 passed (81)
```
Mutation checks (each made, tests run, reverted), all caught:
```
inline frame gets allow-same-origin → 1 failed   CSP drops default-src 'none' → 2 failed
device default inverted             → 2 failed   streaming answer still renders frames → 1 failed
```

**Not tested:** the DB-backed backend suite (no database in this session; the only
backend change is a prompt string); a real browser, so the phone/desktop scaling
and iframe look are unchecked beyond unit tests; whether the model follows the new
prompt; Firefox and Safari.

**Open questions:** none new.

## 2026-10-29 — Increment 17: blank HTML answers and the output cap

**Iteration:** fix for a bug the owner hit on the live site (D-020). Done when an
answer that is raw HTML, or prose then a page, renders; and the per-step output
cap no longer truncates ordinary pages.

**Changed:** `isHtmlDocument` accepts a leading HTML tag, `splitHtmlPage` splits
prose from a page, `Markdown` uses both; `max_output_tokens_per_step` 4096 → 16384.

**Tested**
```
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 13 passed (13), Tests 90 passed (90)
backend: ruff ok · mypy → Success: no issues found in 41 source files
         pytest (no DB) → 57 passed, 90 skipped
```
Mutation check: HTML_START narrowed to doctype/html only → fragment tests failed.

**Not tested:** the real model's output (the cause is inferred from the screenshot,
the two answers' text was not available to me); a real browser.

**Open questions:** none.

---

## 2026-10-29 — Increment 18: open Studio files from chat

**Iteration:** owner request (D-021). Done when a finished answer that saved files
shows a link per file, and a click opens the file in a dialog with Studio's viewer.

**Changed:** `Viewer` and its helpers moved from `pages/Studio.tsx` to
`components/studio/ArtifactViewer.tsx`; new `Modal`, `ArtifactLinks`; `savedFiles`
and `studioApi.inConversation` in `lib/studio.ts`; `TurnView` renders the links.
No backend change.

**Tested**
```
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 13 passed (13), Tests 92 passed (92)
```
New tests: links + dialog (preview frame, Open in Studio, Escape closes, deleted
file gets no link); a chat with no files shows none. Mutation check: ignoring
`deleted` in `savedFiles` → "links the files an answer saved…" failed.

**Not tested:** a real browser (dialog sizing on a phone, focus return, the live
preview inside the dialog); against the live API; very long chats.

**Open questions:** none.

## 2026-10-29 — Increment 16: M6 step 3, project knowledge

**Iteration:** M6 step 3. Definition of done: the owner adds text documents to a
project and deletes them on its page; in that project's chats (and only there) the
agent can search them and gets the best matching passages with their document
name; another project's or another owner's documents are never reachable.

**Changed**
- Migration `0010_knowledge` (`knowledge_documents`, `knowledge_chunks` with a
  generated `tsvector` and GIN index); `projects/knowledge.py` (chunking, store,
  `search_knowledge` tool); endpoints under `/api/v1/projects/{id}/documents`;
  `documents` count on projects; the worker offers the tool in project turns.
- nginx: `client_max_body_size 2m` on `/api/` (the default 1 MiB could refuse a
  256 KiB document once JSON-escaped).
- Web: Knowledge panel on the project page (add several files, list, delete).
- D-021 (D-019 and D-020 were taken by another thread meanwhile), README,
  CHANGELOG, roadmap, requirements WS-5.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 62 files already formatted
         mypy → Success: no issues found in 42 source files
         pytest (DB) → 151 passed, 1 skipped (test_sandbox.py:208: checks the non-root refusal)
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 13 passed (13), Tests 91 passed (91)
nginx -t (nginx:1.27-alpine, committed config) → syntax is ok, test is successful
```
Mutation checks (each made, tests run, reverted), backend 15/15 caught (the first
run had two survivors: ranking, because the test query matched one passage only,
and hard cuts, because the test's words divided the chunk size exactly; both tests
were tightened):
```
search crosses projects                    → CAUGHT   results not ranked                    → CAUGHT
long paragraphs not split                  → CAUGHT   chunks packed past the size           → CAUGHT
long words not cut on spaces               → CAUGHT   add reaches another owner's project   → CAUGHT
delete ignores the owner                   → CAUGHT   list ignores the owner                → CAUGHT
tool missing from project turns            → CAUGHT   any file type accepted                → CAUGHT
NUL bytes accepted                         → CAUGHT   paths accepted as names               → CAUGHT
no stemming                                → CAUGHT   chunks outlive their document         → CAUGHT
documents count missing                    → CAUGHT
```
Frontend 6/6 caught: size check skipped; content altered before upload; upload
errors hidden; wrong document deleted; passage count missing; content not sent.

Browser (Chromium) on the Vite dev server with the real API, worker and Postgres,
and an Ollama-wire stub that calls `search_knowledge` on "search …" and repeats the
result:
```
documents: guide.md | 107 characters · 1 passage
in project: Found: {"results": [{"document": "guide.md", "part": 1, "text": "# Garden guide\n\nTomatoes need full sun and deep watering twice a week.\n\nBasil grows well next to tomatoes."}]}
outside project: No search tool. tools: list_files,read_file,write_file
overflow at 390: 0
errors: the 401 from the sign-in check before login
```

**Not tested:** a real model choosing to search; an upload through the deployed
nginx (config checked with `nginx -t` only); Firefox and Safari.

**Open questions:** none new. Session summaries are next.

## Increment 17 — Session summaries (M6 step 4)

**Iteration:** M6 step 4, session summaries. **Done when:** a chat turn whose
earlier answered turns exceed the context window gives the model a summary of the
ones left out instead of dropping them; the summary rolls forward, is reused by
versions, counts toward usage, survives a provider failure, and the chat shows
where it applies — each shown by a test that fails when the behavior breaks, and
in a browser.

**Changed**
- Migration `0011_summaries`: `tasks.summary` (≤ 4,000 chars) and
  `tasks.summary_of` (FK to tasks, `ON DELETE SET NULL`).
- `chat/store.py`: `left_out()`; send and add-version record `summary_of`.
- `chat/summary.py` (new): `summary_through()` — reuse, or roll forward from the
  newest stored summary in batches of 10 turns; stored per turn.
- Worker: summary before the run (not on a checkpoint resume), into the system
  prompt (`system_prompt(…, summary)`), events `context_summarized` /
  `summary_failed`, summary tokens added to the turn's usage.
- `TaskView`: `summary_of`, `summary`. Web: the chat note at the cut, timeline
  notes for both events.
- Test fake: `ScriptedProvider.complete()` now follows the script (it raised).
- D-022, README, CHANGELOG, roadmap. Requirements WS-5 no longer lists knowledge
  as not built (Increment 16 left it in both lists).

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 64 files already formatted
         mypy → Success: no issues found in 43 source files
         pytest (DB) → 156 passed, 1 skipped
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 13 passed (13), Tests 93 passed (93)
```
Mutation checks (each made, tests run, reverted), backend 14/14 caught (the first
run had one survivor, the guard for a turn that has no answer; a test for it was
added):
```
window counted one short (>=)             → CAUGHT   wrong turn left out               → CAUGHT
versions record no summary_of             → CAUGHT   summary not in the system prompt  → CAUGHT
summary tokens not added                  → CAUGHT   provider error not caught         → CAUGHT
stored summaries ignored (no rolling)     → CAUGHT   no batching                       → CAUGHT
summary not cut to its limit              → CAUGHT   stored on the wrong turn          → CAUGHT
empty summary accepted                    → CAUGHT   unanswered turn summarized        → CAUGHT
system_prompt drops the summary           → CAUGHT   API hides the summary             → CAUGHT
```
Frontend 4/4 caught: note shown at every summarized turn; note text not shown;
reuse/made wording swapped; failure note missing.

Browser (Chromium) on the Vite dev server with the real API, worker and Postgres,
`SEED_CHAT_CONTEXT_TURNS=1`, and an Ollama-wire stub whose summaries list what the
person said and whose answers repeat what the model was given:
```
turn 1: Summary given: none. In full: nothing.
turn 2: Summary given: none. In full: My cat is Miso.
turn 3: Summary given: The person said: My cat is Miso. In full: I live in Lyon.
turn 4: Summary given: The person said: My cat is Miso; I live in Lyon. In full: I like tea.
notes shown: 1
note text: The person said: My cat is Miso; I live in Lyon
overflow at 390: 0
errors: the 401 from the sign-in check before login
```
Turn 3's usage showed 11 in / 5 out (4/2 for the answer plus 7/3 for the summary).

**Not tested:** summary quality with a real model; a turn resumed from a
checkpoint (the code skips summarizing then; no test drives it); Firefox and
Safari.

**Open questions:** none new. M6 has lone tasks in projects left.

## Increment 18 — Tasks in projects (M6 step 5)

**Iteration:** M6 step 5, lone tasks in projects. **Done when:** a task created
from the Tasks page can name a project, copies its instructions and memory, gets
its memory and knowledge tools, is listed on the project page, links back to the
project, and leaves the project when it is deleted — each shown by a test that
fails when the behavior breaks, and in a browser.

**Changed**
- `POST /api/v1/tasks` takes `project_id` (404 `project_not_found` for a missing
  or someone else's project; the idempotency check includes it);
  `GET /api/v1/tasks?project_id=`; `project_id` in the task view; `tasks` on
  projects; deleting a project takes its lone tasks out of it.
- `chat/store.py`: `_project` is now `project_context`, shared with tasks.
- Web: Project picker on Tasks (preselected from `?project=`), project link in
  the task's details, Tasks panel on the project page.
- D-023, README, CHANGELOG, roadmap (M6 built), requirements WS-5.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 65 files already formatted
         mypy → Success: no issues found in 43 source files
         pytest (DB) → 158 passed, 1 skipped
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 13 passed (13), Tests 96 passed (96)
```
Mutation checks (each made, tests run, reverted), backend 9/9 caught: project not
stored on the task; project not copied by the API; idempotency ignores the
project; project filter includes chat turns; project filter ignored; project
missing from the view; `tasks` counts chat turns; delete keeps tasks in the
project; `project_id` ignored. Frontend 6/6 caught: project not sent; `?project=`
not preselected; no project link; no Tasks panel; New task loses the project;
list not filtered.

Browser (Chromium) on the Vite dev server with the real API, worker and Postgres,
and the knowledge stub (calls `search_knowledge` on "search …"):
```
tasks panel: Tasks | New task | No tasks yet. A task started here runs in the background with the project's instructions, memory and knowledge.
project picked: Garden
result: Found: {"results": [{"document": "guide.md", "part": 1, "text": "# Garden guide\n\nTomatoes need full sun and deep water…
details project link: /projects/baf58196-85b8-45f8-ad8f-1a5e4ffe4a19
project tasks: search watering tomato | completed
overflow at 390: 0
errors: the 401 from the sign-in check before login
```

**Not tested:** a real model in a project task; Firefox and Safari.

**Open questions:** none new. M6's planned steps are done; M7 is next.

## Increment 19 — Agent definitions (M7 step 1)

**Iteration:** M7 step 1, agent definitions. **Done when:** an owner can list,
create, change and delete agents (name, purpose, instructions, model, allowed
tools) through the API and the Agents page; names are unique per owner ignoring
case; input is validated; the three starters appear once and stay deleted; other
owners' agents are invisible — each shown by a test that fails when it breaks,
and in a browser.

**Changed**
- Migration `0012_agents` (`agents`, `agent_starters`); `agents/store.py`,
  `agents/api.py` (`/api/v1/agents`, audited).
- Web: `/agents` is now the Agents page (list, create, edit, delete with a
  confirm; a note that delegation is not built yet), replacing the planned page.
- D-024, README, CHANGELOG, roadmap, requirements WS-4.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 69 files already formatted
         mypy → Success: no issues found in 46 source files
         pytest (DB) → 162 passed, 1 skipped
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 14 passed (14), Tests 99 passed (99)
```
Mutation checks (each made, tests run, reverted), backend 13/13 caught: list
crosses owners; get crosses owners; delete crosses owners; update crosses owners;
tools not deduplicated or ordered; starters given again; starters overwrite the
owner's agent; any name accepted; blank model kept; blank purpose accepted;
purpose whitespace kept; name clash not answered with 409; any tool name
accepted. Frontend 8/8 caught: tools not sent; empty form submittable; errors
hidden; model choice ignored; delete without confirm; model badge wrong; purpose
not tidied; PATCH instead of PUT. The frontend test also caught a real bug before
commit: editing sent the whole agent (id, owner, dates) instead of the definition.

Browser (Chromium) on the Vite dev server with the real API and Postgres:
```
starters: Coder · …· task's model · List files · Read files · Write files · Run commands · instructions
          Researcher · … · List files · Read files · Search project knowledge · instructions
          Reviewer · … · List files · Read files · instructions
duplicate: You already have an agent called coder.
after reload: [ 'Coder', 'Researcher', 'Reviewer', 'Writer' ]
overflow at 390: 0
errors: the 401 from the sign-in check before login; the 409 the duplicate check asked for
```

**Not tested:** Firefox and Safari.

**Open questions:** none new. Step 2 (delegation) is next.

## Increment 20 — Delegation (M7 step 2)

**Iteration:** M7 step 2, delegation. **Done when:** SEED can hand a sub-task to
an agent, which runs as its own task with the agent's instructions, model and
tools only; the parent waits durably and resumes with the report however the
child ends (completed, failed, canceled, dead); canceling the parent cancels the
child; unknown agents and bad arguments are answered without a child; the chat
and task lists say a task is with an agent rather than waiting on you — each
shown by a test that fails when it breaks, and in a browser.

**Changed**
- Core: `Tool.deferred`; `run_agent(delegated=…)`, termination
  `awaiting_delegation`, event `delegation_requested`.
- Migration `0013_delegation` (`parent_task_id`, `delegated_call`, `agent`,
  `awaiting_delegation`, `delegations`; the waiting check now allows either
  wait).
- `TaskStore.delegate`, `refuse_delegation`; children report to their parent in
  `finish`, `sweep` and cancel; cancel cascades; children cannot be retried.
- `agents/delegation.py` (tool, prompts); worker offers `delegate`, filters an
  agent's tools, saves an agent's files under the parent's chat.
- Overview `delegating`; chat list `last_state` `delegating`; task view fields.
- Web: "with an agent" badges; "Researcher is working on part of this. Follow
  it" in the live answer; timeline notes for the new events; Agents page note.
- D-025, README, CHANGELOG, roadmap, requirements WS-4.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 71 files already formatted
         mypy → Success: no issues found in 47 source files
         pytest (DB) → 169 passed, 1 skipped
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 14 passed (14), Tests 103 passed (103)
```
Mutation checks (each made, tests run, reverted), backend 23 of 24 caught.
Caught: returned results ignored; invalid arguments paused on; pause reported as
an approval; agent tools not filtered; agents may delegate; results not passed to
the run; agent system prompt not used; agent model ignored; workspace not
shared; project not inherited; finish, sweep or cancel not reporting to the
parent; cancel not cascading; children retryable; result text dropped; agent
names case-sensitive; deliverable dropped from the prompt; overview `waiting`
counting delegations; delegations missing from `active`; chat list
`delegating` missing; refusal replaced by a release. Survived: dropping
`state = 'waiting'` from the parent update in `_report_to_parent`. That one is
equivalent: the table's check makes `awaiting_delegation` non-null only while
`waiting`. Frontend 7/7 caught: badge, chat-list badge, follow link, the two ways
a pending delegation ends, the refusal note, the outcome tone.

Browser (Chromium) on the Vite dev server with the real API, worker and Postgres,
and an Ollama-wire stub that delegates "delegate …" to Researcher:
```
while waiting: Researcher is working on part of this. Follow it
list badge: 1
answer: SEED says: Researcher report on: find the open questions in the brief (tools: list_files,read_file)
agent task: Researcher: find the open questions in the brief
agent task prompt: find the open questions in the brief |  | Report back: a one-line summary
overflow at 390: 0
errors: the 401 from the sign-in check before login
```
The first browser run showed two faults that are now fixed: the agent task's title
included "Report back: …", and the chat list did not refresh to "with an agent"
until the turn ended.

**Not tested:** a real model choosing to delegate; an agent asking for command
approval mid-delegation (the approval path is unchanged and tested on its own);
Firefox and Safari; the live site (this session cannot reach it).

**Open questions:** none new. Step 3 (parallel sub-tasks, depth and concurrency
limits) is next.

## Increment 21 — Several agents at once (M7 step 3)

**Iteration:** M7 step 3, parallel delegation. **Done when:** the delegate calls
of one step start together; limits on agents working at once, per task and on
depth hold, with refusals that say why; results arriving out of order are kept;
a task that ends cancels its working agents and a retry hands off afresh; one
worker process runs several tasks; the chat shows every working agent — each
shown by a test that fails when it breaks, and in a browser.

**Changed**
- Settings `worker_concurrency`, `delegation_max_parallel`,
  `delegation_max_per_task`, `delegation_max_depth`; migration
  `0014_delegation_depth`.
- `TaskStore.delegate(lease, starts=, refusals=, wait_for=)` replaces `delegate`
  and `refuse_delegation`: one transaction starts several children and answers
  refusals. `delegation_status` (working and answered calls). `_report_to_parent`
  keeps a result while the parent is queued or running and requeues only for the
  call it waits on. `_ended`: a task that ends cancels its working children.
- Worker: `_delegate` scans the step's pending calls from the checkpoint (stops at
  an approval and at the per-step cap); `delegate` offered by depth; `main` runs
  `worker_concurrency` workers in a task group; pool sized to fit.
- Web: `pendingDelegations` (a list); the live answer lists each working agent.
- D-026, README, CHANGELOG, roadmap, requirements WS-4.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 71 files already formatted
         mypy → Success: no issues found in 47 source files
         pytest (DB) → 176 passed, 1 skipped
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 14 passed (14), Tests 103 passed (103)
```
New backend tests: three hand-offs start together and report in any order; at
most N at once, the next starting when one reports (and a result arriving while
the parent is queued is kept); refusals past the per-task limit, each call
answered once; depth 2 lets an agent delegate once more and no further; a task
whose worker died cancels its working agent and its retry hands off afresh with
the same call ids; a second delegate call waits for its own approval; calls past
the step cap get no agent.

Mutation checks (each made, tests run, reverted), backend 16/16 caught: parallel
limit always or never reached; per-task limit off by one; depth off by one;
approval stop removed; step cap removed; "already working" or "already answered"
skip removed; refusals not counted; child depth fixed; children of an ended task
not canceled; finished children counted as working; parent requeued by any
result; results dropped unless the parent waits; parent never queued after a
refusal; only the first event logged. The first run had 3 survivors (step cap,
"already answered", result while queued); the tests were tightened until each
failed. Frontend 6/6 caught: a report clearing all agents or none; only the last
agent kept; run end and cancel not clearing; the chat showing only one agent.

Browser (Chromium) on the Vite dev server with the real API, one worker process
(`worker_concurrency` 2) and Postgres, and an Ollama-wire stub that, for "team …",
delegates to Researcher (6 s), Coder (3 s) and Reviewer (9 s) in one step:
```
worker vm:21503:9cde62 started / worker vm:21503:849462 started
while waiting: ["Researcher is working on part of this. Follow it", "Coder is …", "Reviewer is …"]
after the first reports: ["Researcher is …", "Reviewer is …"]
answer: SEED says: Researcher done (started 20:56:16, finished 20:56:22) / Coder done (started 20:56:18, finished 20:56:21) / Reviewer done (started 20:56:21, finished 20:56:30)
overflow at 390: 0
errors: the 401 from the sign-in check before login
```
Researcher and Coder ran at the same time in one process; Reviewer started when
Coder's slot freed.

**Not tested:** the worker process's signal handling with several workers (no
test drives `main`; the stop path of each worker is unchanged and tested); a real
model asking for several agents; two agents writing the same file; the live site
(this session cannot reach it).

**Open questions:** none new. Step 4 (delegation views in chat, Inspector and
Command Center) is next; the live answer shows "Used 1 tool" until the run
reaches the other calls, which step 4 should address.

## Increment 22 — Worker slots for the parallel limit (D-027)

**Iteration:** fix found in the live check of #31. **Done when:** with default
settings three agents of one task run at the same time.

**Changed:** `worker_concurrency` default 2 → 4; README row; D-027; a settings test.

**Checked:** a waiting task does not hold a slot (the worker returns after parking
it), so the cap was the worker count: the 2-worker run in Increment 21 started
Reviewer only when Coder's slot freed.

**Tested**
```
ruff check → All checks passed!
test_a_worker_process_has_a_slot_for_every_agent_the_limit_allows → 1 passed; with the default put back to 2 → 1 failed
browser, default settings (4 workers started), stub agents of 6 s, 3 s and 9 s:
answer: Researcher (started 21:39:13, finished 21:39:19) / Coder (21:39:15–21:39:18) / Reviewer (21:39:15–21:39:24)
```
All three overlap. Full backend suite: 177 passed, 1 skipped; mypy and format clean.

**Not tested:** the live site after deploy (the coordinator re-checks it).

## Increment 23 — Lasting delegation links (M7 step 4a)

**Iteration:** M7 step 4a, asked for by the live check of #30. **Done when:** after a
run ends, the chat and the task page still link to each agent's task and say how
it ended, and an agent's task links back to the task that handed it over — each
shown by a test that fails when it breaks, and in a browser.

**Changed (frontend only; the API already carries `parent_task_id`, `agent` and the
`delegated` and `delegation_finished` events)**
- `delegatedTasks(events)`: every agent task handed work to and its end state.
- `AgentTaskLinks`, used under a finished turn's "Show activity" and in a "Handed to
  agents" panel on the task page.
- Task page: "Agent" and "Handed over by" (the parent's title, linking to it).
- Fix found by the browser run: the task page kept the earlier task's events when
  moving to another task, so following a link from an agent's task to its parent
  showed no delegations. The page is now keyed by task id.

**Tested**
```
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 14 passed (14), Tests 108 passed (108)
```
Breakage checks, frontend 10/10 caught: state never set; state set on every agent;
the activity list hidden when only agents ran; links not rendered; agents panel,
parent link, parent target, and agent row removed; end state always "reported
back"; link target wrong. The new "starts afresh" test fails (1 failed) with the
key removed and passes with it.

Browser (Chromium), real API, workers and Postgres, stub agents; after a reload
of a finished turn:
```
chat links after the run: Researcher's task | reported back | Coder's task | reported back | Reviewer's task | reported back
back link: team look over the release plan /tasks/b85bc4c9-…
parent panel: Researcher's task | reported back | Coder's task | reported back | Reviewer's task | reported back
overflow at 390: 0
errors: the 401 from the sign-in check before login
```
The first run failed at the parent panel: that was the stale-events bug above.

**Not tested:** the live site; links for agents of agents (depth above 1; the
panel lists a task's own children only).

**Open questions:** none new. 4b (Inspector) and 4c (Command Center) remain.

## Increment 24 — Delegation in the Inspector and Command Center (M7 step 4b, 4c)

**Iteration:** M7 step 4b and 4c. **Done when:** the Inspector lists a task's
hand-offs (and refusals) and links an agent's task to its parent and back; the
overview and Command Center show what each agent is doing; tasks in progress name
their agent — each shown by a test that fails when it breaks, and in a browser.

**Changed**
- `inspect()` gains `delegations` (from `delegated`, `delegation_finished`,
  `delegation_refused`; a retried task's repeated call ids go to the newest hand-off).
- Inspector: a "Delegations" panel (agent, handed over, ended, elapsed, result or
  "refused: reason"); a child's summary shows its agent and "Handed over by".
- Overview API: `agents` — per agent name, tasks working now and finished within the
  window by state, and tokens of the finished ones.
- Command Center: an "Agent activity" panel; in-progress rows name the agent.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 71 files already formatted
         mypy → Success: no issues found in 47 source files
         pytest (DB) → 178 passed, 1 skipped
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 14 passed (14), Tests 111 passed (111)
```
Breakage checks: Inspector 9/10 caught (the survivor, ignoring "already ended" when
matching a report to a hand-off, is equivalent while events arrive in order);
Command Center 5/5; overview agents query 6/6 (a first run let unfinished tasks'
tokens through; the test now gives the working task tokens).

Browser (Chromium), real API, workers and Postgres, stub agents ("team …"):
```
before any agent work: No agent work yet
agent activity while working: Coder 1 0 0 0 0 · Researcher 1 0 0 0 0 · Reviewer 1 0 0 0 0
agent activity after: Coder 0 1 0 0 6 · Researcher 0 1 0 0 6 · Reviewer 0 1 0 0 6
inspector delegations: Researcher … 6.1 s completed · Coder … 5.0 s completed · Reviewer … 11.0 s completed
child summary: … Agent Coder Handed over by the task that delegated it …
back at parent delegations rows: 4 (header + 3)
overflow at 390: 0
errors: the 401 from the sign-in check before login
```
"Elapsed" is from hand-off to report, so it includes time queued.

**Not tested:** the live site; agents of agents in the Inspector; renamed agents
(activity groups by the name an agent had when work was handed to it).

**Open questions:** the roadmap still lists workload and routing views and agent
metrics beyond tokens for M7; what to build next there is Stephen's call.

## Increment 25 — Tools & Skills page (M8 step 1)

**Iteration:** M8 step 1. **Done when:** the Tools page lists the real tools with
their permission, the approval policy in force and limits, and shows usage from
recorded tool results, with no placeholder content — each shown by a test that fails
when it breaks, and in a browser.

**Changed**
- `tools_api.py`: `GET /api/v1/tools` (catalog from the worker's tool definitions;
  usage from `tool_result` events in the window); migration
  `0015_tool_result_index` (partial index on tool results).
- Web: `Tools.tsx` (tool list with details on demand, approval policy, usage table,
  a Skills empty state); `lib/tools.ts`; the placeholder in `areas.tsx` removed.
- D-028, README, CHANGELOG, roadmap, requirements WS-9.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → clean
         mypy → Success: no issues found in 48 source files
         pytest (DB) → 182 passed, 1 skipped
frontend: typecheck ok · lint ok · format ok · vitest → Test Files 15 passed (15), Tests 115 passed (115)
```
Breakage checks: backend 9/9 caught; frontend 9/10 (the survivor is a badge colour).
The backend run first let two things through: a vacuous "no roster stub" assertion
and, equivalently, the tools' own approval flag (none sets it today); the first was
tightened.

Browser (Chromium), real API, worker and Postgres, stub model that calls
`list_files` then `read_file` on a missing file:
```
tools: list_files, read_file, write_file, run_command, remember, search_knowledge, delegate
run_command row: run_command runs code asks you first Tasks run by a worker with a sandbox (SEED_SANDBOX_URL)
usage before: No tool calls recorded
usage after: list_files 1 1 0 0 ms — · read_file 1 0 1 0 ms tool error 1
overflow at 390: 0
errors: the 401 from the sign-in check before login
```

**Not tested:** the live site; a tool added later keeping the catalog in step (only a
missing `AVAILABLE_IN` text is caught); approval policy when the API and worker run
with different settings.

**Open questions:** what a "skill" is and whether M8 owns it (D-028).

## Increment 26 — Schedules, backend (M8 step 2a)

**Iteration:** M8 step 2a. **Done when:** a schedule can be saved through the API; a
worker starts its task when it is due, exactly once however many workers poll;
missed runs and a still-running last task do not pile up tasks; the next time is
right across timezones and clock changes — each shown by a test that fails when it
breaks, and against the real stack.

**Changed**
- Migration `0016_schedules`; `schedules/recurrence.py` (next run), `store.py`
  (CRUD, `fire_due`, `run_now`), `api.py` (`/api/v1/schedules`); the worker calls
  `fire_due` on each pass; dependency `tzdata`.
- D-029, README, CHANGELOG, roadmap.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → clean
         mypy → Success: no issues found in 52 source files
         pytest (DB) → 208 passed, 1 skipped
```
26 new tests (the DB-less ones run without a database): recurrence (interval, daily in two timezones, both clock changes, bad
input); the API (create, list, replace, delete, run now, audit, 11 refused
timetables, project scoping); firing (due, not due, six concurrent workers → one
task, missed runs, a due time already used, busy skip including a task waiting for
approval, disabled, a project's context, a worker starting and running a due task).
Breakage checks 20/22 caught; the two survivors are equivalent (`SKIP LOCKED`
only avoids waiting, and the `enabled` test is covered by a table check).

Real stack (API, worker, Postgres, stub model), by API: created an hourly schedule,
made it due, and 6 s later:
```
Hourly check 2026-10-30T01:04:31Z (next run, before)
after: Hourly check started next 2026-10-30T01:04:33Z
task: Scheduled: Hourly check completed 'plain answer'
audit: admin|schedule_created · |schedule_started_task|schedule
tasks total (8 s later): 1
```
The next run moved from 01:04:31 (created + 1 h) to 01:04:33 (fired + 1 h), and no
second task started.

**Not tested:** a schedule in the live deployment; a clock change inside a running
worker; very many schedules (20 are handled per pass).

**Open questions:** none new. Step 2b is the page to manage schedules.

## Increment 27 — Tools page fixes from the live check of #35 (M8)

**Changed:** the usage table became a stacked list (the table's right-aligned
headings ran together at 390 px, and the "offered in" text was truncated); the
time and output limits show on each tool's row; the usage API returns `reasons`,
the three commonest error messages per tool, shown under "Why they failed".

**Tested**
```
backend: ruff, format, mypy clean; tests/test_tools_api.py → 5 passed
         (new: reasons are the 3 commonest messages, cut to 200 characters)
frontend: typecheck, lint, format:check clean; npm test → 115 passed
```
**Not tested:** at 390 px in a browser (the layout is stacked and wraps; checked
by reading, not by a screenshot); the live site.

**Why list_files (9 of 23) and read_file (5 of 7) fail:** not known from here. The
code's failures are the model naming a path that does not exist, a directory, an
absolute path or a file that is not UTF-8. The page now shows the actual messages,
so the live site will say which.

## Increment 28 — Schedules page (M8 step 2b)

**Changed:** `/schedules` (sidebar, `G` then `E`): list with timetable in words, next
and last run, skipped-run note, link to the last task; form to create or edit
(name, prompt, model defaulting to the provider's, project, every N minutes 5–10080
or daily at a time and time zone defaulting to the browser's); pause or resume,
run now (links to the started task), delete after a confirm.

**Tested**
```
frontend: typecheck, lint, format:check clean; npm test → 120 passed (5 new)
```
Breakage checks, each caught by a failing test: dropping the upper bound of the
interval, not flipping `enabled` on pause, sending `every_minutes` for a daily
schedule, ignoring the project choice.

**Not tested:** in a browser at 390 px or against the real API; the live site.

**Open questions:** none new.

## Increment 29 — list_files error wording

**Changed:** the live check of #37 showed the file tools' errors were the agent
guessing paths in an empty workspace. `list_files` said "Not a directory" for a path
that does not exist; it now says "No such directory: x", and "Not a directory: x is a
file." for a file.

**Tested:** `pytest tests/test_tools.py` → 5 passed (new test: missing path vs file);
ruff, format and mypy clean.

**Not tested:** the sandbox's own listing (it uses the same function).
## Increment 30 — Notifications backend (M8 step 3a)

**Changed:** migration 0017 (`notifications`), `seed_api.notifications` (store and
API), and writes in the transactions that finish a task, park it for an approval,
and skip a schedule's run (D-030). Stephen chose in-app first.

**Tested**
```
backend: ruff check → All checks passed! · ruff format --check → 82 files already formatted
         mypy → Success: no issues found in 55 source files
         pytest (DB) → 216 passed, 1 skipped
```
7 new tests: completed and failed tasks announced with a one-line, cut body;
canceled not announced; chat turns and agent task endings not announced, an agent
task's approval announced, a chat turn's not; a skipped schedule run announced and
removed with its schedule; reading per owner; the API's list, unread count, order,
mark read and 404, mark all read, limit check, and sign-in required.
Breakage checks 10/10 caught (cancel exclusion, chat/agent rule, chat approvals,
owner check, read mark, unread filter, body cut, skipped-run write, order).

**Not tested:** the real worker loop end to end (the store functions it calls are
tested); the live site. The page and bell come next.

**Open questions:** expiry of read notifications (D-030).
