"""Overview API over a real Postgres: the Command Center's numbers come from tasks."""

from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api.config import Settings

from .conftest import sign_in, start


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    settings = db_settings.model_copy(update={"ollama_api_key": SecretStr("unused")})
    with start(settings) as c:
        yield sign_in(c)


def make(api: TestClient, title: str, model: str = "m-a") -> str:
    r = api.post("/api/v1/tasks", json={"model": model, "prompt": title, "title": title})
    assert r.status_code == 201
    return str(r.json()["id"])


def set_state(
    db_url: str, task_id: str, state: str, *, hours_ago: float = 0, tokens: tuple[int, int] = (0, 0)
) -> None:
    """Finish (or park) a task as a worker would have, `hours_ago`."""
    finished = state in ("completed", "failed", "canceled")
    with psycopg.connect(db_url) as conn:
        conn.execute(
            """
            UPDATE tasks SET state = %(state)s,
                   awaiting_approval = CASE WHEN %(state)s = 'waiting'
                       THEN '{"id": "c", "name": "run_command", "arguments": {}}'::jsonb END,
                   finished_at = CASE WHEN %(finished)s
                       THEN now() - make_interval(secs => %(secs)s) END,
                   updated_at = now() - make_interval(secs => %(secs)s),
                   usage = jsonb_build_object('input_tokens', %(i)s, 'output_tokens', %(o)s),
                   error = CASE WHEN %(state)s = 'failed' THEN 'boom' END
            WHERE id = %(id)s
            """,
            {
                "state": state,
                "finished": finished,
                "secs": hours_ago * 3600,
                "i": tokens[0],
                "o": tokens[1],
                "id": task_id,
            },
        )


def test_overview_needs_auth(db_settings: Settings) -> None:
    with start(db_settings) as c:
        assert c.get("/api/v1/overview").status_code == 401


def test_an_empty_overview(api: TestClient) -> None:
    r = api.get("/api/v1/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["window_hours"] == 24
    assert body["counts"] == {
        "queued": 0,
        "running": 0,
        "waiting": 0,
        "delegating": 0,
        "completed": 0,
        "failed": 0,
        "canceled": 0,
    }
    assert body["attention"] == body["active"] == body["recent"] == body["usage"] == []
    assert body["agents"] == []
    for bad in ("0", "721", "x"):
        assert api.get(f"/api/v1/overview?hours={bad}").status_code == 422


def test_overview_counts_lists_and_usage(api: TestClient, db_url: str) -> None:
    queued_old = make(api, "queued first")
    queued_new = make(api, "queued second")
    running = make(api, "running")
    set_state(db_url, running, "running")
    waiting = make(api, "waiting")
    set_state(db_url, waiting, "waiting", hours_ago=30)  # waiting never ages out
    failed = make(api, "failed", model="m-b")
    set_state(db_url, failed, "failed", hours_ago=1, tokens=(5, 1))
    failed_old = make(api, "failed long ago")
    set_state(db_url, failed_old, "failed", hours_ago=48, tokens=(1000, 1000))
    done_a = make(api, "done earlier")
    set_state(db_url, done_a, "completed", hours_ago=2, tokens=(100, 10))
    done_b = make(api, "done later")
    set_state(db_url, done_b, "completed", hours_ago=1, tokens=(200, 20))
    done_old = make(api, "done long ago")
    set_state(db_url, done_old, "completed", hours_ago=50, tokens=(1, 1))
    canceled = make(api, "canceled", model="m-b")
    set_state(db_url, canceled, "canceled", hours_ago=3, tokens=(7, 0))
    delegating = make(api, "delegating")
    with psycopg.connect(db_url) as conn:  # waiting for an agent, not for a person
        conn.execute(
            "UPDATE tasks SET state = 'waiting', awaiting_delegation = "
            """'{"id": "d", "name": "delegate", "arguments": {}}'::jsonb WHERE id = %s""",
            (delegating,),
        )

    body = api.get("/api/v1/overview").json()
    assert body["counts"] == {
        "queued": 2,
        "running": 1,
        "waiting": 1,
        "delegating": 1,
        "completed": 2,
        "failed": 1,
        "canceled": 1,
    }
    # Waiting first (a person must act), then failures in the window, newest first.
    assert [t["id"] for t in body["attention"]] == [waiting, failed]
    assert body["attention"][0]["awaiting_approval"]["name"] == "run_command"
    # Running first, then queued and delegating in the order they were created.
    assert [t["id"] for t in body["active"]] == [running, queued_old, queued_new, delegating]
    assert [t["id"] for t in body["recent"]] == [done_b, done_a]
    assert body["usage"] == [
        {"model": "m-a", "tasks": 2, "input_tokens": 300, "output_tokens": 30},
        {"model": "m-b", "tasks": 2, "input_tokens": 12, "output_tokens": 1},
    ]

    wide = api.get("/api/v1/overview?hours=72").json()
    assert wide["window_hours"] == 72
    assert (wide["counts"]["failed"], wide["counts"]["completed"]) == (2, 3)
    assert [t["id"] for t in wide["recent"]] == [done_b, done_a, done_old]
    assert [t["id"] for t in wide["attention"]] == [waiting, failed, failed_old]
    assert wide["usage"][0] == {
        "model": "m-a",
        "tasks": 4,
        "input_tokens": 1301,
        "output_tokens": 1031,
    }


def test_overview_lists_are_capped(api: TestClient, db_url: str) -> None:
    ids = [make(api, f"t{i}") for i in range(12)]
    for i in ids[:7]:
        set_state(db_url, i, "completed")
    body = api.get("/api/v1/overview").json()
    assert body["counts"]["queued"] == 5 and body["counts"]["completed"] == 7
    assert len(body["active"]) == 5 and len(body["recent"]) == 5
    for i in ids[7:]:
        set_state(db_url, i, "failed")
    more = [make(api, f"q{i}") for i in range(11)]
    body = api.get("/api/v1/overview").json()
    assert len(body["attention"]) == 5 and len(body["active"]) == 10
    assert body["counts"]["queued"] == len(more)


def test_overview_shows_what_each_agent_is_doing(api: TestClient, db_url: str) -> None:
    def as_agent(task_id: str, name: str) -> None:
        with psycopg.connect(db_url) as conn:
            conn.execute(
                "UPDATE tasks SET agent = jsonb_build_object('id', gen_random_uuid()::text, "
                "'name', %s::text, 'description', 'd', 'instructions', '', 'model', NULL, "
                "'tools', '[]'::jsonb) "
                "WHERE id = %s",
                (name, task_id),
            )

    plain = make(api, "not an agent task")
    set_state(db_url, plain, "completed", hours_ago=1, tokens=(9000, 9000))
    working = make(api, "researcher running")
    as_agent(working, "Researcher")
    set_state(db_url, working, "running", tokens=(50, 5))  # not finished: not counted
    queued = make(api, "researcher queued")
    as_agent(queued, "Researcher")
    done = make(api, "researcher done")
    as_agent(done, "Researcher")
    set_state(db_url, done, "completed", hours_ago=2, tokens=(100, 10))
    old = make(api, "researcher done long ago")
    as_agent(old, "Researcher")
    set_state(db_url, old, "completed", hours_ago=48, tokens=(5000, 500))
    failed = make(api, "coder failed")
    as_agent(failed, "Coder")
    set_state(db_url, failed, "failed", hours_ago=1, tokens=(7, 3))
    canceled = make(api, "coder canceled")
    as_agent(canceled, "Coder")
    set_state(db_url, canceled, "canceled", hours_ago=1)
    idle = make(api, "reviewer long ago")
    as_agent(idle, "Reviewer")
    set_state(db_url, idle, "completed", hours_ago=48)

    body = api.get("/api/v1/overview").json()
    # Busiest first; the agent whose work ended before the window is left out.
    assert body["agents"] == [
        {
            "name": "Researcher",
            "working": 2,
            "completed": 1,
            "failed": 0,
            "canceled": 0,
            "input_tokens": 100,
            "output_tokens": 10,
        },
        {
            "name": "Coder",
            "working": 0,
            "completed": 0,
            "failed": 1,
            "canceled": 1,
            "input_tokens": 7,
            "output_tokens": 3,
        },
    ]
    wide = api.get("/api/v1/overview?hours=72").json()
    assert [a["name"] for a in wide["agents"]] == ["Researcher", "Coder", "Reviewer"]
    assert wide["agents"][0]["completed"] == 2 and wide["agents"][0]["input_tokens"] == 5100
