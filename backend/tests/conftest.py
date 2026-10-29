import os
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api import auth
from seed_api.config import Settings, get_settings
from seed_api.main import create_app

LOGIN = {"username": "admin", "password": "correct-horse"}


@pytest.fixture
def settings() -> Settings:
    return Settings(admin_username="admin", admin_password=SecretStr(LOGIN["password"]))


@pytest.fixture
def db_url() -> str:
    """A Postgres database the tests may wipe. CI sets SEED_REQUIRE_DB_TESTS so a
    missing database fails the run instead of silently skipping these tests."""
    url = os.environ.get("SEED_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("SEED_REQUIRE_DB_TESTS"):
            pytest.fail("SEED_TEST_DATABASE_URL is required (SEED_REQUIRE_DB_TESTS is set)")
        pytest.skip("SEED_TEST_DATABASE_URL not set")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "DROP TABLE IF EXISTS artifact_previews, artifact_versions, artifacts, task_events, "
            "tasks, conversations, audit_log, sessions, users, schema_migrations CASCADE"
        )
    return url


@pytest.fixture
def db_settings(settings: Settings, db_url: str) -> Settings:
    return settings.model_copy(update={"database_url": SecretStr(db_url)})


def start(settings: Settings) -> TestClient:
    """A client for an app on `settings`. Use it as a context manager so the
    lifespan runs (pool, migrations, bootstrap admin)."""
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def sign_in(client: TestClient, creds: dict[str, str] = LOGIN) -> TestClient:
    """Signs in and sends the session's CSRF token on every later request, as the
    web app does."""
    r = client.post("/api/v1/auth/login", json=creds)
    assert r.status_code == 200, r.text
    client.headers[auth.CSRF_HEADER] = client.cookies[auth.CSRF_COOKIE]
    return client


@pytest.fixture
def client(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings) as c:
        yield c


@pytest.fixture
def authed(client: TestClient) -> TestClient:
    return sign_in(client)
