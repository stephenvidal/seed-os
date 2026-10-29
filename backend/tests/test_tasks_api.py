"""Tasks API over a real Postgres, including persistence across an API restart."""

import json
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api.config import Settings

from .conftest import sign_in, start

BODY = {"model": "deepseek-v4.1-flash", "prompt": "Summarise  the\\nrepo"}


@pytest.fixture
def db_settings(db_settings: Settings) -> Settings:
    return db_settings.model_copy(update={"ollama_api_key": SecretStr("unused")})


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings) as c:  # runs the lifespan: pool + migrations
        yield sign_in(c)


def test_tasks_require_auth_and_csrf(db_settings: Settings) -> None:
    with start(db_settings) as c:
        assert c.get("/api/v1/tasks").status_code == 401
        assert c.post("/api/v1/tasks", json=BODY).status_code == 401
        sign_in(c)
        del c.headers["X-CSRF-Token"]
        assert c.post("/api/v1/tasks", json=BODY).json()["error"]["code"] == "csrf_failed"
        assert c.get("/api/v1/tasks").json() == []


def test_create_needs_a_provider(db_settings: Settings) -> None:
    with start(db_settings.model_copy(update={"ollama_api_key": None})) as c:
        sign_in(c)
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


def test_cancel_and_retry_transitions_are_audited(api: TestClient, db_url: str) -> None:
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
    with psycopg.connect(db_url) as conn:
        audit = conn.execute(
            "SELECT actor, action, target FROM audit_log WHERE action LIKE 'task_%' ORDER BY id"
        ).fetchall()
    assert audit == [
        ("admin", "task_created", tid),
        ("admin", "task_canceled", tid),
        ("admin", "task_retried", tid),
    ]


def test_unknown_and_malformed_ids(api: TestClient) -> None:
    missing = uuid.uuid4()
    assert api.get(f"/api/v1/tasks/{missing}").status_code == 404
    assert api.post(f"/api/v1/tasks/{missing}/cancel").status_code == 404
    assert api.get(f"/api/v1/tasks/{missing}/events").status_code == 404
    assert api.get("/api/v1/tasks/not-a-uuid").status_code == 422
    assert api.post("/api/v1/tasks", json={"model": "m", "prompt": ""}).status_code == 422


def test_tasks_survive_an_api_restart(db_settings: Settings, db_url: str) -> None:
    with start(db_settings) as first:
        sign_in(first)
        tid = first.post("/api/v1/tasks", json=BODY).json()["id"]
    # The first app and its pool are gone; a new process sees the same task.
    with start(db_settings) as second:
        sign_in(second)
        assert second.get(f"/api/v1/tasks/{tid}").json()["state"] == "queued"
    with psycopg.connect(db_url) as conn:
        row = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()
        assert row == (9,)  # migrations ran once, not per start


def sse(text: str) -> list[tuple[str | None, str | None, dict]]:  # type: ignore[type-arg]
    out = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "data" in fields:
            out.append((fields.get("id"), fields.get("event"), json.loads(fields["data"])))
    return out


def test_stream_replays_and_ends_for_a_finished_task(api: TestClient) -> None:
    tid = api.post("/api/v1/tasks", json=BODY).json()["id"]
    api.post(f"/api/v1/tasks/{tid}/cancel")
    with api.stream("GET", f"/api/v1/tasks/{tid}/stream") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = r.read().decode()
    assert body.startswith("retry: 2000")
    events = sse(body)
    assert [(i, e, d.get("type")) for i, e, d in events] == [
        ("1", None, "task_created"),
        ("2", None, "cancel_requested"),
        (None, "end", None),
    ]
    assert events[-1][2] == {"state": "canceled"}


def test_stream_resumes_after_last_event_id(api: TestClient) -> None:
    tid = api.post("/api/v1/tasks", json=BODY).json()["id"]
    api.post(f"/api/v1/tasks/{tid}/cancel")
    with api.stream("GET", f"/api/v1/tasks/{tid}/stream", headers={"Last-Event-ID": "1"}) as r:
        events = sse(r.read().decode())
    assert [i for i, _, _ in events] == ["2", None]
    with api.stream("GET", f"/api/v1/tasks/{tid}/stream?after=2") as r:
        assert [e for _, e, _ in sse(r.read().decode())] == ["end"]
    assert api.get(f"/api/v1/tasks/{uuid.uuid4()}/stream").status_code == 404


def park(db_url: str, tid: str, call_id: str = "call_0") -> None:
    """Stand-in for a worker pausing the task on a gated tool call."""
    call = {"id": call_id, "name": "run_command", "arguments": {"command": "make"}}
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "UPDATE tasks SET state = 'waiting', awaiting_approval = %s WHERE id = %s",
            (json.dumps(call), tid),
        )


def test_approve_or_deny_a_waiting_task(api: TestClient, db_url: str) -> None:
    tid = api.post("/api/v1/tasks", json=BODY).json()["id"]
    not_yet = api.post(f"/api/v1/tasks/{tid}/decision", json={"call_id": "call_0", "approve": True})
    assert not_yet.status_code == 409 and not_yet.json()["error"]["code"] == "not_waiting"

    park(db_url, tid)
    shown = api.get(f"/api/v1/tasks/{tid}").json()
    assert shown["state"] == "waiting" and shown["awaiting_approval"]["name"] == "run_command"
    wrong = api.post(f"/api/v1/tasks/{tid}/decision", json={"call_id": "call_9", "approve": True})
    assert wrong.status_code == 409
    ok = api.post(f"/api/v1/tasks/{tid}/decision", json={"call_id": "call_0", "approve": False})
    assert ok.status_code == 200
    assert ok.json()["state"] == "queued" and ok.json()["awaiting_approval"] is None
    again = api.post(f"/api/v1/tasks/{tid}/decision", json={"call_id": "call_0", "approve": True})
    assert again.status_code == 409  # decided once; the decision stands

    events = api.get(f"/api/v1/tasks/{tid}/events").json()["events"]
    assert events[-1]["type"] == "approval_decided"
    assert events[-1]["data"] == {"id": "call_0", "approved": False, "by": "admin"}
    with psycopg.connect(db_url) as conn:
        row = conn.execute(
            "SELECT action, target, detail FROM audit_log WHERE action LIKE 'tool_%'"
        ).fetchone()
        stored = conn.execute("SELECT approvals FROM tasks WHERE id = %s", (tid,)).fetchone()
    assert row == (
        "tool_denied",
        f"{tid}/call_0",
        {"tool": "run_command", "arguments": {"command": "make"}},
    )
    assert stored is not None and stored[0]["call_0"]["approved"] is False


def test_a_waiting_task_cancels_at_once(api: TestClient, db_url: str) -> None:
    tid = api.post("/api/v1/tasks", json=BODY).json()["id"]
    park(db_url, tid)
    r = api.post(f"/api/v1/tasks/{tid}/cancel")
    assert r.status_code == 200
    assert r.json()["state"] == "canceled" and r.json()["awaiting_approval"] is None
