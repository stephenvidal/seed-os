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
