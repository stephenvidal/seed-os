# Security — SEED OS

## Built
- **Authentication (ADR-0009):** users in Postgres with argon2id password hashes.
  The first admin is created from `SEED_ADMIN_PASSWORD` only while no users
  exist; there is no default password (no users → 503 `auth_not_configured`).
  Unknown usernames cost the same argon2 verify as known ones. Users are managed
  with `python -m seed_api.users`; passwords are prompted, never arguments.
- **Sessions:** server-side rows keyed by the SHA-256 of a random 256-bit cookie
  token (HttpOnly, SameSite=Lax, `Secure` via `SEED_COOKIE_SECURE`). Revoked on
  sign-out; all of a user's sessions are revoked on password change; disabling a
  user ends their sessions at once.
- **CSRF:** synchronizer token bound to the session, delivered in the readable
  `seed_csrf` cookie and required in `X-CSRF-Token` on every authenticated
  request except GET/HEAD/OPTIONS (403 `csrf_failed`).
- **Authorization:** enforced in backend dependencies (`current_principal`,
  `require_role`); the frontend only reflects it. One role today: `admin`.
- **Audit log:** `audit_log` records sign-ins (and failures), sign-outs, user
  management and task create/cancel/retry with actor, target, address and time.
- **Rate limiting:** 5 failed sign-ins per username per 60 s → 429, counted from
  `audit_log`, so it holds across processes and restarts.
- **Input validation:** Pydantic models at every endpoint; typed 422 errors.
- **Transport/headers (nginx):** CSP `default-src 'self'`, `frame-ancestors
  'none'`, `X-Frame-Options DENY`, `nosniff`, `Referrer-Policy`. TLS is expected
  from a terminating proxy in front of `web`.
- **Containers:** API runs as non-root uid 10001 on a read-only root FS with
  memory limits.
- **Secrets:** environment only; `.env` ignored; `.env.example` committed.

## Known gaps (tracked)
- `script-src 'unsafe-inline'` is required by the pre-paint theme script; replace
  with a hash.
- Roles beyond `admin` are not defined yet; no user-management screen (CLI only).
- Sign-in limits are per username, not per client: behind the tunnel all clients
  share one address. A per-client limit needs `CF-Connecting-IP` passed through.
- Audit log rows are kept indefinitely; no retention policy yet.
- Sandbox, tool approval policies, network egress controls, prompt-injection
  handling: M2/M3 (see requirements).
- Artifact previews must be served from a separate origin (M6).
- Dependency audit not yet automated (`npm audit`, `pip-audit`).
