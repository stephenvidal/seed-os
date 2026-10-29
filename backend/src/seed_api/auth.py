"""Authentication: Postgres users, revocable server-side sessions, CSRF tokens (ADR-0009).

- Passwords are argon2id hashes. Unknown usernames still pay for one verify, so
  response time does not reveal which usernames exist.
- The session cookie is a random token; the database stores only its SHA-256,
  so a leaked database row cannot be replayed as a cookie.
- Each session carries a CSRF token. The browser reads it from the `seed_csrf`
  cookie and echoes it in `X-CSRF-Token` on every request that changes state.
- Sign-ins, sign-outs and task actions are written to `audit_log`; failed
  sign-ins there also drive the per-username rate limit.
"""

import hashlib
import hmac
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, Request, Response
from psycopg import errors as pg_errors
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .errors import ApiError
from .flow.db import Pool

COOKIE = "seed_session"
CSRF_COOKIE = "seed_csrf"
CSRF_HEADER = "X-CSRF-Token"
ROLES = ("admin",)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MIN_PASSWORD = 12

log = logging.getLogger("seed.auth")
_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class UserError(ValueError):
    """A user-management request that cannot be applied (bad input or conflict)."""


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    user_id: uuid.UUID | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class User:
    id: uuid.UUID
    username: str
    role: str
    disabled: bool
    password_hash: str


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        raise UserError(f"Passwords need at least {MIN_PASSWORD} characters.")
    return _hasher.hash(password)


def check_username(username: str) -> str:
    if not USERNAME.match(username):
        raise UserError(
            "Usernames are 1-64 characters: lowercase letters, digits, '.', '_' or '-', "
            "starting with a letter or digit."
        )
    return username


class AuthStore:
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def count_users(self) -> int:
        async with self.pool.connection() as conn:
            cur = await conn.execute("SELECT count(*) AS n FROM users")
            row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def create_user(
        self, username: str, password: str, role: str = "admin", *, enforce_length: bool = True
    ) -> User:
        if role not in ROLES:
            raise UserError(f"Unknown role {role!r}. Roles: {', '.join(ROLES)}.")
        username = check_username(username)
        pw_hash = hash_password(password) if enforce_length else _hasher.hash(password)
        try:
            async with self.pool.connection() as conn:
                cur = await conn.execute(
                    "INSERT INTO users (id, username, password_hash, role) "
                    "VALUES (%s, %s, %s, %s) RETURNING *",
                    (uuid.uuid4(), username, pw_hash, role),
                )
                row = await cur.fetchone()
        except pg_errors.UniqueViolation as e:
            raise UserError(f"User {username!r} already exists.") from e
        if row is None:
            raise UserError(f"User {username!r} was not created.")
        return _user(row)

    async def get_user(self, username: str) -> User | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute("SELECT * FROM users WHERE username = %s", (username,))
            row = await cur.fetchone()
        return _user(row) if row else None

    async def list_users(self) -> list[User]:
        async with self.pool.connection() as conn:
            cur = await conn.execute("SELECT * FROM users ORDER BY username")
            return [_user(r) for r in await cur.fetchall()]

    async def set_password(self, username: str, password: str) -> None:
        """Changes the password and signs the user out everywhere."""
        pw_hash = hash_password(password)
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "UPDATE users SET password_hash = %s, updated_at = now() "
                "WHERE username = %s RETURNING id",
                (pw_hash, username),
            )
            row = await cur.fetchone()
            if row is None:
                raise UserError(f"No user {username!r}.")
            await conn.execute(
                "UPDATE sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
                (row["id"],),
            )

    async def set_disabled(self, username: str, disabled: bool) -> None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE users SET disabled = %s, updated_at = now() WHERE username = %s",
                (disabled, username),
            )
        if cur.rowcount == 0:
            raise UserError(f"No user {username!r}.")

    async def rehash(self, user_id: uuid.UUID, pw_hash: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s", (pw_hash, user_id)
            )

    async def create_session(
        self, user: User, ttl_seconds: int, ip: str | None, user_agent: str | None
    ) -> tuple[str, str]:
        """Returns (cookie token, CSRF token). Only the token's digest is stored."""
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO sessions (id, user_id, csrf_token, expires_at, ip, user_agent) "
                "VALUES (%s, %s, %s, now() + make_interval(secs => %s), %s, %s)",
                (_digest(token), user.id, csrf, ttl_seconds, ip, (user_agent or "")[:300]),
            )
        return token, csrf

    async def load_session(self, token: str) -> tuple[Principal, str] | None:
        """The live session for a cookie, with its CSRF token. Revoked, expired and
        disabled-user sessions are not live."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE sessions s SET last_seen_at = now() FROM users u "
                "WHERE s.id = %s AND u.id = s.user_id AND s.revoked_at IS NULL "
                "AND s.expires_at > now() AND NOT u.disabled "
                "RETURNING s.id, s.csrf_token, u.id AS user_id, u.username, u.role",
                (_digest(token),),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        principal = Principal(row["username"], row["role"], row["user_id"], row["id"])
        return principal, row["csrf_token"]

    async def revoke_session(self, session_id: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE sessions SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL",
                (session_id,),
            )

    async def revoke_user_sessions(self, username: str) -> int:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE sessions s SET revoked_at = now() FROM users u "
                "WHERE u.id = s.user_id AND u.username = %s AND s.revoked_at IS NULL",
                (username,),
            )
        return cur.rowcount

    async def recent_failures(self, username: str, window_seconds: int) -> int:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM audit_log WHERE action = 'login_failed' "
                "AND target = %s AND at > now() - make_interval(secs => %s)",
                (username, window_seconds),
            )
            row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def audit(
        self,
        action: str,
        *,
        actor: str | None,
        target: str | None = None,
        ip: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO audit_log (actor, action, target, ip, detail) "
                "VALUES (%s, %s, %s, %s, %s)",
                (actor, action, target, ip, Jsonb(detail or {})),
            )


def _user(row: dict[str, Any]) -> User:
    return User(row["id"], row["username"], row["role"], row["disabled"], row["password_hash"])


async def bootstrap_admin(store: AuthStore, settings: Settings) -> bool:
    """On first start (no users yet), create the admin from SEED_ADMIN_USERNAME and
    SEED_ADMIN_PASSWORD. Afterwards those settings are not read again: change
    passwords with `python -m seed_api.users set-password`."""
    if settings.admin_password is None or await store.count_users() > 0:
        return False
    password = settings.admin_password.get_secret_value()
    if len(password) < MIN_PASSWORD:
        # Accepted so an existing deployment keeps starting; new passwords set with
        # the CLI must meet the minimum.
        log.warning("SEED_ADMIN_PASSWORD is shorter than %d characters", MIN_PASSWORD)
    try:
        await store.create_user(settings.admin_username, password, "admin", enforce_length=False)
    except UserError as e:
        if await store.count_users() > 0:  # another process bootstrapped first
            return False
        raise RuntimeError(f"Cannot create the bootstrap admin: {e}") from e
    await store.audit("user_bootstrapped", actor=None, target=settings.admin_username)
    log.info("created bootstrap admin %s", settings.admin_username)
    return True


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def get_auth_store(request: Request) -> AuthStore:
    store: AuthStore | None = getattr(request.app.state, "auth_store", None)
    if store is None:
        raise ApiError(
            503, "auth_not_configured", "Sign-in needs a database. Set SEED_DATABASE_URL."
        )
    return store


AuthStoreDep = Annotated[AuthStore, Depends(get_auth_store)]


async def current_principal(request: Request, store: AuthStoreDep) -> Principal:
    token = request.cookies.get(COOKIE)
    live = await store.load_session(token) if token else None
    if live is None:
        raise ApiError(401, "unauthenticated", "Sign in to continue.")
    principal, csrf = live
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(sent.encode(), csrf.encode()):
            raise ApiError(403, "csrf_failed", "Missing or invalid CSRF token. Reload the page.")
    return principal


def require_role(*roles: str):  # type: ignore[no-untyped-def]
    def dependency(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if principal.role not in roles:
            raise ApiError(403, "forbidden", "Your role does not permit this action.")
        return principal

    return dependency


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class Me(BaseModel):
    username: str
    role: str


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/login", response_model=Me)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    store: AuthStoreDep,
) -> Me:
    username, ip = body.username.strip().lower(), client_ip(request)
    if await store.recent_failures(username, settings.login_window_seconds) >= (
        settings.login_max_failures
    ):
        await store.audit("login_rate_limited", actor=None, target=username, ip=ip)
        raise ApiError(429, "rate_limited", "Too many failed sign-in attempts. Try again soon.")
    user = await store.get_user(username)
    try:
        _hasher.verify(user.password_hash if user else _DUMMY_HASH, body.password)
        ok = user is not None and not user.disabled
    except (VerificationError, InvalidHashError):
        ok = False
    if not ok or user is None:
        if user is None and await store.count_users() == 0:
            raise ApiError(
                503,
                "auth_not_configured",
                "No users exist yet. Set SEED_ADMIN_PASSWORD and restart, "
                "or add one with `python -m seed_api.users add`.",
            )
        await store.audit("login_failed", actor=None, target=username, ip=ip)
        raise ApiError(401, "invalid_credentials", "Incorrect username or password.")
    if _hasher.check_needs_rehash(user.password_hash):
        await store.rehash(user.id, _hasher.hash(body.password))
    token, csrf = await store.create_session(
        user, settings.session_ttl_seconds, ip, request.headers.get("user-agent")
    )
    await store.audit("login", actor=user.username, target=user.username, ip=ip)
    cookie = {
        "max_age": settings.session_ttl_seconds,
        "secure": settings.cookie_secure,
        "path": "/",
    }
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", **cookie)  # type: ignore[arg-type]
    # Readable by the page's script on purpose: it echoes this value in X-CSRF-Token.
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, samesite="strict", **cookie)  # type: ignore[arg-type]
    return Me(username=user.username, role=user.role)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_principal)],
    store: AuthStoreDep,
) -> None:
    """Revokes this session server-side, so the cookie stops working everywhere."""
    if principal.session_id:
        await store.revoke_session(principal.session_id)
    await store.audit("logout", actor=principal.username, ip=client_ip(request))
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.get("/me", response_model=Me)
def me(principal: Annotated[Principal, Depends(current_principal)]) -> Me:
    return Me(username=principal.username, role=principal.role)
