# ADR-0009 — Postgres users, revocable sessions, CSRF token, audit log

**Status:** Accepted (2026-10-28). Supersedes ADR-0004.

**Context:** ADR-0004's bootstrap auth had one user from the environment, an
HMAC-signed cookie that could not be revoked before expiry, an in-memory
per-process rate limiter and no CSRF token. M3 put Postgres in production, and
the requirements ask for secure auth, sessions, backend-enforced RBAC and audit
logs (requirements, "Security"). Open question 4 asked for a CSRF strategy.

**Options**
- Sessions: signed stateless tokens (JWT/HMAC) vs. server-side session rows.
- CSRF: double-submit cookie vs. synchronizer token stored with the session vs.
  an `Origin` header check alone.
- Rate limit: in-memory vs. Redis vs. counting failures already in Postgres.

**Decision**
- **Users** in Postgres (`users`, migration `0002_auth`): lowercase username,
  argon2id hash (argon2-cffi defaults, rehashed on sign-in when the defaults
  change), role, disabled flag. Roles: `admin` only, enforced by
  `require_role`. Sign-in for an unknown username still runs one argon2 verify,
  so timing does not reveal which usernames exist.
- **Sessions** are server-side rows. The cookie (`seed_session`, HttpOnly,
  SameSite=Lax, `Secure` via `SEED_COOKIE_SECURE`) carries a random 256-bit
  token; the row is keyed by its SHA-256, so a leaked database cannot be replayed
  as cookies. A session is live while not revoked, not past `expires_at`
  (`SEED_SESSION_TTL_SECONDS`) and its user is not disabled. Sign-out revokes the
  row; a password change revokes all of that user's rows. `SEED_SESSION_SECRET`
  is no longer used.
- **CSRF:** synchronizer token. Each session row holds a random token, sent to
  the browser in the readable `seed_csrf` cookie (SameSite=Strict). Every
  authenticated request other than GET/HEAD/OPTIONS must echo it in
  `X-CSRF-Token`; mismatch → 403 `csrf_failed`. Because the token is bound to
  the session server-side, a cookie planted by a sibling subdomain cannot satisfy
  it (the weakness of plain double-submit). Sign-in itself has no session yet;
  it accepts JSON only, which a cross-site form cannot send.
- **Audit log** (`audit_log`): sign-in, failed sign-in, rate-limited sign-in,
  sign-out, bootstrap, user management, and task create/cancel/retry, with actor,
  target, client address and time.
- **Rate limit:** failed sign-ins for a username within
  `SEED_LOGIN_WINDOW_SECONDS` are counted from `audit_log`; at
  `SEED_LOGIN_MAX_FAILURES` sign-in for that username answers 429. It holds
  across processes and restarts. It is keyed by username, not address: behind
  the Cloudflare tunnel and nginx every client reaches the API from the same
  address, so an address key would let one person lock everyone out.
- **First user:** when `users` is empty, the API creates
  `SEED_ADMIN_USERNAME` with `SEED_ADMIN_PASSWORD` at start. After that the
  environment password is not read; users are managed with
  `python -m seed_api.users` (add, set-password, disable, enable,
  revoke-sessions, list). New passwords need 12+ characters; the bootstrap
  password is accepted shorter (with a warning) so an existing deployment keeps
  starting.

**Consequences**
- Sign-in needs the database: without `SEED_DATABASE_URL` it answers 503
  `auth_not_configured`, as it does when no users exist.
- One database write per authenticated request (`last_seen_at`). Fine at this
  scale; revisit if it shows up in profiles.
- Per-username lockout can be triggered by anyone who knows a username, for one
  window at a time. Per-client limits need a trusted client address
  (`CF-Connecting-IP` passed through nginx); left as an open question.
- No user-management screen yet; the CLI is the interface.
