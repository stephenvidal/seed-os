import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from seed_api import auth
from seed_api.config import Settings, get_settings
from seed_api.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(admin_username="admin", admin_password="correct-horse", session_secret="s" * 32)  # type: ignore[arg-type]


@pytest.fixture
def client(settings: Settings) -> TestClient:
    auth.limiter.reset()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


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
        conn.execute("DROP TABLE IF EXISTS task_events, tasks, schema_migrations CASCADE")
    return url
