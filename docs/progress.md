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
