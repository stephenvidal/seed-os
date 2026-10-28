# CLAUDE.md — execution rules for SEED OS

You are the implementer for SEED OS. Read `DIRECTIVE.md` first; it outranks this
file when they disagree. Directive v1.0 defines the frame (method, gate, change
control); v1.1 defines the product — see `docs/product-vision.md`,
`docs/requirements.md`, `docs/roadmap.md`.

## Session protocol

1. Read `DIRECTIVE.md`, this file, `docs/decisions.md`, `docs/progress.md`
   (latest entry first), and `docs/roadmap.md`.
2. State the iteration you are working on in one sentence, plus its definition of
   done, **before** editing anything.
3. Work in one increment. If the increment grows past a reviewable diff, stop and
   split it.
4. Verify by running it. Paste the observed output into `docs/progress.md`.
5. Append to `docs/progress.md`: changed / tested / not tested / open questions.

## Hard rules

- **No invented requirements.** If the directive does not require it, do not build
  it. Log the gap in `docs/decisions.md` under "Open questions."
- **No unverified claims.** "Done" means a cited command output or test line. If
  you could not test something, write that down.
- **`main` stays green.** Never commit a state that does not run.
- **Small diffs.** One concern per commit. Conventional Commits
  (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- **Secrets never enter the repo.** Configuration comes from the environment;
  commit `.env.example`, never `.env`.
- **Do not edit `DIRECTIVE.md`.** Amendments are ratified by the owner.
- **No placeholder architecture.** No TODO-shaped modules, no empty interfaces
  "for later." Prototypes go in `spikes/` and are deleted when spent.

## Production bar

- Explicit error paths at every boundary; failures are typed, not swallowed.
- Inputs validated where they enter the system.
- Tests must be able to fail. A test that passes against a broken implementation
  is a bug in the test.
- Every public surface documented in README as it behaves today.

## Repository conventions

| Path | Rule |
|---|---|
| `docs/decisions.md` | Append-only. One entry per decision: context, options, choice, reason, consequences. |
| `docs/progress.md` | Append-only per session. Never rewrite history to look better. |
| `spikes/` | Disposable. Nothing here is production code. |

## Verification checklist before you report

- [ ] The iteration's definition of done is met and each criterion is cited.
- [ ] Tests were run; output quoted, not summarised.
- [ ] `docs/progress.md` appended with the untested section filled in honestly.
- [ ] Diff contains no drive-by edits.
- [ ] `main` still runs from a clean checkout.

## Environment and commands

- Stack ratified by Directive v1.1 / ADRs in `docs/decisions/`: React + Vite +
  TypeScript + Tailwind (`frontend/`), Python + FastAPI (`backend/`), Docker
  Compose. Postgres, workers, sandbox arrive in M3.
- Backend: `cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`;
  check with `.venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest -q`.
- Frontend: `cd frontend && npm ci`; check with
  `npm run typecheck && npm run lint && npm run format:check && npm test`.
- Dev: run the API (`SEED_ADMIN_PASSWORD=… .venv/bin/uvicorn seed_api.main:app`)
  and `npm run dev`; Vite proxies `/api` to `:8000`.
- Hosted GitHub Actions is unavailable. CI/deploy workflows target a self-hosted
  runner (`[self-hosted, golden-eye]`, see `docs/deployment.md`); keep `runs-on`,
  the fork guard, and job timeouts. Until that runner exists, run the checks
  above locally and paste output into `docs/progress.md`.
- Never touch `stephenvidal/agent-native-os` or the Hermes Agent installation.
- No fake data in screens: unbuilt areas show an honest empty state naming the
  milestone.
