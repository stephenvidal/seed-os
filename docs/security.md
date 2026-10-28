# Security — SEED OS

## Built (Iteration 1)
- **Authentication:** bootstrap admin from `SEED_ADMIN_PASSWORD`; sign-in is
  disabled (503 `auth_not_configured`) if unset — no default password.
  Constant-time credential comparison.
- **Sessions:** HMAC-SHA256-signed token with expiry in an HttpOnly,
  SameSite=Lax cookie; `Secure` via `SEED_COOKIE_SECURE`. Without
  `SEED_SESSION_SECRET` a random per-process key is used (sessions end on restart).
- **Authorization:** enforced in backend dependencies (`current_principal`,
  `require_role`); the frontend only reflects it.
- **Rate limiting:** 5 failed sign-ins per client per 60s → 429 (in-memory,
  single-process; moves to Postgres with M3).
- **Input validation:** Pydantic models at every endpoint; typed 422 errors.
- **Transport/headers (nginx):** CSP `default-src 'self'`, `frame-ancestors
  'none'`, `X-Frame-Options DENY`, `nosniff`, `Referrer-Policy`. TLS is expected
  from a terminating proxy in front of `web`.
- **Containers:** API runs as non-root uid 10001 on a read-only root FS with
  memory limits.
- **Secrets:** environment only; `.env` ignored; `.env.example` committed.

## Known gaps (tracked)
- No CSRF token yet. Mitigated by SameSite=Lax + JSON-only POST bodies; add a
  double-submit token before any cross-site-reachable deployment (M3).
- `script-src 'unsafe-inline'` is required by the pre-paint theme script; replace
  with a hash.
- Session revocation, multi-user RBAC, audit log: M3.
- Sandbox, tool approval policies, network egress controls, prompt-injection
  handling: M2/M3 (see requirements).
- Artifact previews must be served from a separate origin (M6).
- Dependency audit not yet automated (`npm audit`, `pip-audit`).
