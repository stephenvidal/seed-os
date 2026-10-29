"""Sign-in, sessions, CSRF and the audit log against a real Postgres."""

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api import auth, users
from seed_api.config import Settings

from .conftest import LOGIN, sign_in, start

LOGIN_URL = "/api/v1/auth/login"


def audit_actions(db_url: str) -> list[tuple[str, str | None]]:
    with psycopg.connect(db_url) as conn:
        rows = conn.execute("SELECT action, target FROM audit_log ORDER BY id").fetchall()
    return [(a, t) for a, t in rows]


def sql(db_url: str, query: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(query.encode())


def test_healthz_is_public(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_protected_routes_reject_anonymous(client: TestClient) -> None:
    for path in ("/api/v1/auth/me", "/api/v1/system"):
        r = client.get(path)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthenticated"


def test_first_start_creates_admin_with_hashed_password(client: TestClient, db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        row = conn.execute("SELECT username, role, password_hash FROM users").fetchall()
    assert [(u, r) for u, r, _ in row] == [("admin", "admin")]
    assert row[0][2].startswith("$argon2id$") and LOGIN["password"] not in row[0][2]
    assert audit_actions(db_url) == [("user_bootstrapped", "admin")]


def test_login_sets_session_and_csrf_cookies(client: TestClient, db_url: str) -> None:
    r = client.post(LOGIN_URL, json=LOGIN)
    assert r.status_code == 200 and r.json() == {"username": "admin", "role": "admin"}
    cookies = {c.split("=", 1)[0]: c.lower() for c in r.headers.get_list("set-cookie")}
    assert "httponly" in cookies[auth.COOKIE] and "samesite=lax" in cookies[auth.COOKIE]
    assert "httponly" not in cookies[auth.CSRF_COOKIE]
    assert client.get("/api/v1/auth/me").json()["username"] == "admin"
    assert client.get("/api/v1/system").status_code == 200
    # Only the token's digest is stored, so a database row cannot be replayed as a cookie.
    with psycopg.connect(db_url) as conn:
        (stored,) = conn.execute("SELECT id FROM sessions").fetchone()  # type: ignore[misc]
    assert stored != client.cookies[auth.COOKIE] and len(stored) == 64


def test_login_is_case_insensitive_on_username(client: TestClient) -> None:
    assert client.post(LOGIN_URL, json={**LOGIN, "username": " Admin "}).status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(client: TestClient, db_url: str) -> None:
    for creds in ({**LOGIN, "password": "nope"}, {"username": "ghost", "password": "nope"}):
        r = client.post(LOGIN_URL, json=creds)
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    assert client.get("/api/v1/auth/me").status_code == 401
    assert audit_actions(db_url)[1:] == [("login_failed", "admin"), ("login_failed", "ghost")]


def test_state_changes_need_the_csrf_token(client: TestClient) -> None:
    client.post(LOGIN_URL, json=LOGIN)
    for headers in ({}, {auth.CSRF_HEADER: "forged"}):
        r = client.post("/api/v1/auth/logout", headers=headers)
        assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    assert client.get("/api/v1/auth/me").status_code == 200  # reads need no token
    r = client.post("/api/v1/auth/logout", headers={auth.CSRF_HEADER: client.cookies["seed_csrf"]})
    assert r.status_code == 204


def test_csrf_token_belongs_to_its_session(db_settings: Settings) -> None:
    with start(db_settings) as a, start(db_settings) as b:
        sign_in(a)
        b.post(LOGIN_URL, json=LOGIN)
        r = b.post("/api/v1/auth/logout", headers={auth.CSRF_HEADER: a.cookies[auth.CSRF_COOKIE]})
        assert r.status_code == 403


def test_logout_revokes_the_session_server_side(authed: TestClient) -> None:
    stolen = authed.cookies[auth.COOKIE]
    assert authed.post("/api/v1/auth/logout").status_code == 204
    authed.cookies.set(auth.COOKIE, stolen)  # a copy of the cookie taken before logout
    assert authed.get("/api/v1/auth/me").status_code == 401


def test_expired_session_is_rejected(authed: TestClient, db_url: str) -> None:
    sql(db_url, "UPDATE sessions SET expires_at = now() - interval '1 second'")
    assert authed.get("/api/v1/auth/me").status_code == 401


def test_disabling_a_user_ends_their_sessions(authed: TestClient, db_url: str) -> None:
    sql(db_url, "UPDATE users SET disabled = true")
    assert authed.get("/api/v1/auth/me").status_code == 401
    assert authed.post(LOGIN_URL, json=LOGIN).status_code == 401


def test_rate_limit_is_per_username(client: TestClient, db_url: str) -> None:
    for _ in range(5):
        assert client.post(LOGIN_URL, json={**LOGIN, "password": "x"}).status_code == 401
    r = client.post(LOGIN_URL, json=LOGIN)  # even correct credentials are blocked in-window
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    # Everyone shares one address behind the tunnel, so other accounts stay usable.
    assert client.post(LOGIN_URL, json={"username": "bob", "password": "x"}).status_code == 401
    sql(db_url, "UPDATE audit_log SET at = at - interval '61 seconds'")  # window passes
    assert client.post(LOGIN_URL, json=LOGIN).status_code == 200


def test_validation_error_is_typed(client: TestClient) -> None:
    r = client.post(LOGIN_URL, json={"username": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_no_database_means_no_sign_in(settings: Settings) -> None:
    with start(settings) as c:
        r = c.post(LOGIN_URL, json=LOGIN)
        assert r.status_code == 503 and r.json()["error"]["code"] == "auth_not_configured"
        assert c.get("/api/v1/tasks").json()["error"]["code"] == "auth_not_configured"


def test_no_users_and_no_bootstrap_password_is_a_typed_503(db_settings: Settings) -> None:
    with start(db_settings.model_copy(update={"admin_password": None})) as c:
        r = c.post(LOGIN_URL, json=LOGIN)
        assert r.status_code == 503 and r.json()["error"]["code"] == "auth_not_configured"


def test_bootstrap_password_is_only_read_once(db_settings: Settings) -> None:
    with start(db_settings):
        pass
    changed = db_settings.model_copy(update={"admin_password": SecretStr("a-new-password")})
    with start(changed) as c:
        assert c.post(LOGIN_URL, json={**LOGIN, "password": "a-new-password"}).status_code == 401
        assert c.post(LOGIN_URL, json=LOGIN).status_code == 200


def test_role_gate_is_enforced_server_side() -> None:
    from seed_api.errors import ApiError

    gate = auth.require_role("admin")
    with pytest.raises(ApiError) as e:
        gate(auth.Principal("bob", "viewer"))
    assert e.value.status == 403


def run_cli(monkeypatch: pytest.MonkeyPatch, db_url: str, *argv: str, stdin: str = "") -> int:
    import io

    from seed_api.config import get_settings

    monkeypatch.setenv("SEED_DATABASE_URL", db_url)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    get_settings.cache_clear()
    try:
        return users.main(list(argv))
    finally:
        get_settings.cache_clear()


def test_cli_manages_users_and_sessions(
    client: TestClient,
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pw = "long-enough-password\n"
    assert run_cli(monkeypatch, db_url, "add", "Bad Name", stdin=pw) == 1
    assert run_cli(monkeypatch, db_url, "add", "bob", stdin="short\n") == 1
    assert run_cli(monkeypatch, db_url, "add", "bob", stdin=pw) == 0
    assert run_cli(monkeypatch, db_url, "add", "bob", stdin=pw) == 1  # already exists
    assert "already exists" in capsys.readouterr().err

    bob = sign_in(client, {"username": "bob", "password": pw.strip()})
    assert run_cli(monkeypatch, db_url, "revoke-sessions", "bob") == 0
    assert bob.get("/api/v1/auth/me").status_code == 401

    sign_in(bob, {"username": "bob", "password": pw.strip()})
    assert run_cli(monkeypatch, db_url, "set-password", "bob", stdin="another-long-one\n") == 0
    assert bob.get("/api/v1/auth/me").status_code == 401  # signed out everywhere
    assert bob.post(LOGIN_URL, json={"username": "bob", "password": pw.strip()}).status_code == 401
    sign_in(bob, {"username": "bob", "password": "another-long-one"})

    assert run_cli(monkeypatch, db_url, "disable", "bob") == 0
    assert bob.get("/api/v1/auth/me").status_code == 401
    assert run_cli(monkeypatch, db_url, "set-password", "nobody", stdin=pw) == 1
    capsys.readouterr()
    assert run_cli(monkeypatch, db_url, "list") == 0
    assert capsys.readouterr().out.split("\n")[:2] == [
        "admin\tadmin\tactive",
        "bob\tadmin\tdisabled",
    ]
    actions = [a for a, _ in audit_actions(db_url)]
    assert {"user_added", "sessions_revoked", "password_changed", "user_disabled"} <= set(actions)
