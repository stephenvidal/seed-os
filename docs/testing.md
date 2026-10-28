# Testing — SEED OS

| Layer | Tool | Command | Iteration 1 |
|---|---|---|---|
| Backend unit/API | pytest + FastAPI TestClient | `cd backend && .venv/bin/pytest -q` | 11 tests |
| Backend lint/format/types | ruff, mypy --strict | `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy` | clean |
| Frontend unit/integration | Vitest + Testing Library (real api client, stubbed fetch) | `cd frontend && npm test` | 12 tests |
| Accessibility | vitest-axe on sign-in and shell | part of `npm test` | 2 checks |
| Frontend types/lint/format | tsc strict, ESLint, Prettier | `npm run typecheck && npm run lint && npm run format:check` | clean |
| Browser | Playwright screenshots, light/dark/mobile | manual script (not committed) | reviewed |
| Container | Compose build + up + curl | see `deployment.md` | verified (see progress) |
| E2E, visual regression, migration, security | — | — | not yet (M2+) |

Rules: tests must be able to fail. Iteration 1 checked this by mutation —
disabling signature verification fails `test_tampered_and_expired_tokens_fail`;
breaking `resolveTheme` fails the theme test.

## Milestone 2 additions
- `tests/test_ollama_provider.py` — adapter against `httpx.MockTransport` (wire
  format, tool calls, streaming, every error class).
- `tests/test_agent.py` — loop against a scripted provider (`tests/fakes.py`):
  completion, real file round trip, every termination reason, bounded retries,
  cancellation, per-step tool cap.
- `tests/test_tools.py` — registry outcomes and workspace confinement (traversal,
  absolute paths, symlink escape).
- `tests/test_runs_api.py` — SSE endpoint end to end with a scripted provider.
- Frontend: `runs.test.ts` (SSE parser), `Chat.test.tsx` (streamed run, failure,
  unconfigured provider).
- Scripted providers prove the plumbing only. Agent capability is claimed only
  from runs against a real model.
