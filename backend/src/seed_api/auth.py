"""Bootstrap authentication: one admin from environment, HMAC-signed session cookie.

This is the Milestone 1 foundation. Database-backed users and roles arrive with
SEED Flow persistence (Milestone 3); the `role` claim already flows through so
authorization checks are enforced server-side from day one.
"""

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .errors import ApiError

COOKIE = "seed_session"
_process_secret = secrets.token_bytes(32)


@dataclass(frozen=True)
class Principal:
    username: str
    role: str


def _key(settings: Settings) -> bytes:
    if settings.session_secret is not None:
        return settings.session_secret.get_secret_value().encode()
    return _process_secret


def _sign(settings: Settings, payload: str) -> str:
    mac = hmac.new(_key(settings), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def issue_token(settings: Settings, principal: Principal, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + settings.session_ttl_seconds)
    payload = f"{principal.username}|{principal.role}|{expires}"
    body = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{body}.{_sign(settings, payload)}"


def verify_token(settings: Settings, token: str, now: float | None = None) -> Principal | None:
    try:
        body, sig = token.split(".", 1)
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
        username, role, expires = payload.split("|")
        valid = hmac.compare_digest(sig, _sign(settings, payload))
        if not valid or int(expires) < (now if now is not None else time.time()):
            return None
    except ValueError:
        return None
    return Principal(username=username, role=role)


class _LoginLimiter:
    """In-memory sliding-window limiter on failed logins, keyed by client address."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, settings: Settings) -> None:
        window = self._failures[key]
        cutoff = time.monotonic() - settings.login_window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= settings.login_max_failures:
            raise ApiError(429, "rate_limited", "Too many failed sign-in attempts. Try again soon.")

    def record_failure(self, key: str) -> None:
        self._failures[key].append(time.monotonic())

    def reset(self) -> None:
        self._failures.clear()


limiter = _LoginLimiter()


def current_principal(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Principal:
    token = request.cookies.get(COOKIE)
    principal = verify_token(settings, token) if token else None
    if principal is None:
        raise ApiError(401, "unauthenticated", "Sign in to continue.")
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


@router.post("/login", response_model=Me)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Me:
    if settings.admin_password is None:
        raise ApiError(503, "auth_not_configured", "Set SEED_ADMIN_PASSWORD to enable sign-in.")
    client = request.client.host if request.client else "unknown"
    limiter.check(client, settings)
    user_ok = hmac.compare_digest(body.username.encode(), settings.admin_username.encode())
    pass_ok = hmac.compare_digest(
        body.password.encode(), settings.admin_password.get_secret_value().encode()
    )
    if not (user_ok and pass_ok):
        limiter.record_failure(client)
        raise ApiError(401, "invalid_credentials", "Incorrect username or password.")
    principal = Principal(username=settings.admin_username, role="admin")
    response.set_cookie(
        COOKIE,
        issue_token(settings, principal),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return Me(username=principal.username, role=principal.role)


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=Me)
def me(principal: Annotated[Principal, Depends(current_principal)]) -> Me:
    return Me(username=principal.username, role=principal.role)
