"""Tasks API over a real Postgres, including persistence across an API restart."""

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api import auth
from seed_api.config import Settings, get_settings
from seed_api.main import create_app

LOGIN = {"username": "admin", "password": "correct-horse"}
BODY = {"model": "deepseek-v4.1-flash", "prompt": "Summarise  the\\nrepo"}


@pytest.fixture
def db_settings(settings: Settings, db_url: str) -> Settings:
    return settings.model_copy(
        update={"database_url": SecretStr(db_url), "ollama_api_key": SecretStr("unused")}
    )


def start(settings: Settings) -> TestClient:
    auth.limiter.reset()
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings) as c:  # runs the lifespan: pool + migrations
        c.post("/api/v1/auth/login", json=LOGIN)
        yield c


def test_tasks_need_a_database(client: TestClient) -> None:
    client.post("/api/v1/auth/login", json=LOGIN)
    r = client.get("/api/v1/tasks")
    assert r.status_code == 503 and r.json()["error"]["code"] == "database_not_configured"


def test_tasks_require_auth(db_settings: Settings) -> None:
    with start(db_settings) as c:
        assert c.get("/api/v1/tasks").status_code == 401
        assert c.post("/api/v1/tasks", json=BODY).status_code == 401


def test_create_needs_a_provider(db_settings: Settings) -> None:
    with start(db_settings.model_copy(update={"ollama_api_key": None})) as c:
        c.post("/api/v1/auth/login", json=LOGIN)
        r = c.post("/api/v1/tasks", json=BODY)
        assert r.status_code == 503 and r.json()["error"]["code"] == "provider_not_configured"


def test_create_get_list_and_events(api: TestClient) -> None:
    r = api.post("/api/v1/tasks", json=BODY)
    assert r.status_code == 201
    task = r.json()
    assert task["state"] == "queued" and task["attempt"] == 0 and task["max_attempts"] == 3
    assert task["title"] == "Summarise the\\nrepo"  # whitespace collapsed
    assert "checkpoint" not in task and task["resumable_from_step"] is None

    assert api.get(f"/api/v1/tasks/{task['id']}").json()["id"] == task["id"]
    assert [t["id"] for t in api.get("/api/v1/tasks").json()] == [task["id"]]
    assert api.get("/api/v1/tasks?state=running").json() == []

    page = api.get(f"/api/v1/tasks/{task['id']}/events").json()
    assert [e["type"] for e in page["events"]] == ["task_created"]
    assert page["last_seq"] == 1 and page["state"] == "queued"
    assert api.get(f"/api/v1/tasks/{task['id']}/events?after=1").json()["events"] == []


def test_idempotency_key(api: TestClient) -> None:
    h = {"Idempotency-Key": "chat-msg-42"}
    first = api.post("/api/v1/tasks", json=BODY, headers=h)
    again = api.post("/api/v1/tasks", json=BODY, headers=h)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    clash = api.post("/api/v1/tasks", json={**BODY, "prompt": "different"}, headers=h)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "idempotency_conflict"
    bad = api.post("/api/v1/tasks", json=BODY, headers={"Idempotency-Key": "has space"})
    assert bad.status_code == 422
    assert len(api.get("/api/v1/tasks").json()) == 1


def test_cancel_and_retry_transitions(api: TestClient) -> None:
    tid = api.post("/api/v1/tasks", json=BODY).json()["id"]
    assert api.post(f"/api/v1/tasks/{tid}/retry").json()["error"]["code"] == "not_retryable"
    canceled = api.post(f"/api/v1/tasks/{tid}/cancel")
    assert canceled.status_code == 200 and canceled.json()["state"] == "canceled"
    again = api.post(f"/api/v1/tasks/{tid}/cancel")
    assert again.status_code == 409 and again.json()["error"]["code"] == "not_cancelable"
    retried = api.post(f"/api/v1/tasks/{tid}/retry")
    assert retried.status_code == 200 and retried.json()["state"] == "queued"
    types = [e["type"] for e in api.get(f"/api/v1/tasks/{tid}/events").json()["events"]]
    assert types == ["task_created", "cancel_requested", "task_requeued"]


def test_unknown_and_malformed_ids(api: TestClient) -> None:
    missing = uuid.uuid4()
    assert api.get(f"/api/v1/tasks/{missing}").status_code == 404
    assert api.post(f"/api/v1/tasks/{missing}/cancel").status_code == 404
    assert api.get(f"/api/v1/tasks/{missing}/events").status_code == 404
    assert api.get("/api/v1/tasks/not-a-uuid").status_code == 422
    assert api.post("/api/v1/tasks", json={"model": "m", "prompt": ""}).status_code == 422


def test_tasks_survive_an_api_restart(db_settings: Settings, db_url: str) -> None:
    with start(db_settings) as first:
        first.post("/api/v1/auth/login", json=LOGIN)
        tid = first.post("/api/v1/tasks", json=BODY).json()["id"]
    # The first app and its pool are gone; a new process sees the same task.
    with start(db_settings) as second:
        second.post("/api/v1/auth/login", json=LOGIN)
        assert second.get(f"/api/v1/tasks/{tid}").json()["state"] == "queued"
    with psycopg.connect(db_url) as conn:
        row = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()
        assert row == (1,)  # migrations ran once, not per start
