from fastapi.testclient import TestClient

from seed_api import auth
from seed_api.config import Settings

LOGIN = "/api/v1/auth/login"
GOOD = {"username": "admin", "password": "correct-horse"}


def test_healthz_is_public(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_protected_routes_reject_anonymous(client: TestClient) -> None:
    for path in ("/api/v1/auth/me", "/api/v1/system"):
        r = client.get(path)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthenticated"


def test_login_sets_httponly_cookie_and_grants_access(client: TestClient) -> None:
    r = client.post(LOGIN, json=GOOD)
    assert r.status_code == 200 and r.json() == {"username": "admin", "role": "admin"}
    assert "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/v1/auth/me").json()["username"] == "admin"
    assert client.get("/api/v1/system").status_code == 200


def test_wrong_password_is_rejected(client: TestClient) -> None:
    r = client.post(LOGIN, json={**GOOD, "password": "nope"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_clears_session(client: TestClient) -> None:
    client.post(LOGIN, json=GOOD)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_rate_limit_after_repeated_failures(client: TestClient) -> None:
    for _ in range(5):
        assert client.post(LOGIN, json={**GOOD, "password": "x"}).status_code == 401
    r = client.post(LOGIN, json=GOOD)  # even correct credentials are blocked in-window
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


def test_validation_error_is_typed(client: TestClient) -> None:
    r = client.post(LOGIN, json={"username": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_login_disabled_without_password(client: TestClient) -> None:
    from seed_api.config import get_settings

    client.app.dependency_overrides[get_settings] = lambda: Settings(admin_password=None)  # type: ignore[attr-defined]
    r = client.post(LOGIN, json=GOOD)
    assert r.status_code == 503 and r.json()["error"]["code"] == "auth_not_configured"


def test_tampered_and_expired_tokens_fail(settings: Settings) -> None:
    p = auth.Principal("admin", "admin")
    token = auth.issue_token(settings, p, now=1000.0)
    assert auth.verify_token(settings, token, now=1001.0) == p
    assert auth.verify_token(settings, token, now=1000.0 + settings.session_ttl_seconds + 1) is None
    body, sig = token.split(".")
    assert auth.verify_token(settings, body + "." + sig[:-2] + "AA", now=1001.0) is None
    assert auth.verify_token(settings, "garbage", now=1001.0) is None


def test_role_gate_is_enforced_server_side(settings: Settings) -> None:
    import pytest

    from seed_api.errors import ApiError

    gate = auth.require_role("admin")
    with pytest.raises(ApiError) as e:
        gate(auth.Principal("bob", "viewer"))
    assert e.value.status == 403
