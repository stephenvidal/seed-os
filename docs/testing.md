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
