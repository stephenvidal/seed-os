# ADR-0004 — Bootstrap admin auth with signed session cookie (M1)

**Status:** Accepted (2026-10-28); to be superseded in M3
**Context:** M1 requires an authentication foundation; there is no database until M3.
**Decision:** Single admin from `SEED_ADMIN_USERNAME`/`SEED_ADMIN_PASSWORD`; HMAC-SHA256 signed, expiring, HttpOnly SameSite=Lax cookie; role claim enforced server-side; in-memory failed-login limiter. No default password: unset disables sign-in.
**Consequences:** No revocation before expiry, single user, limiter is per-process. M3 replaces with Postgres-backed users, hashed passwords (argon2), revocable sessions, CSRF token, and audit log.
