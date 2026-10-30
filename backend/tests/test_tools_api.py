"""Tools API (D-028): the catalog is read from the tools the worker registers; usage
comes from the tool results recorded in task events."""

import json
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api.config import Settings

from .conftest import sign_in, start

NAMES = [
    "list_files",
    "read_file",
    "write_file",
    "run_command",
    "remember",
    "search_knowledge",
    "delegate",
    "skill_list",
    "skill_view",
]


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    settings = db_settings.model_copy(update={"ollama_api_key": SecretStr("unused")})
    with start(settings) as c:
        yield sign_in(c)


def by_name(body: dict[str, object], key: str = "tools") -> dict[str, dict[str, object]]:
    rows = body[key]
    assert isinstance(rows, list)
    return {r["name" if key == "tools" else "tool"]: r for r in rows}


def test_tools_need_a_session(db_settings: Settings) -> None:
    with start(db_settings) as c:
        assert c.get("/api/v1/tools").status_code == 401


def test_the_catalog_lists_every_tool_with_its_limits_and_policy(api: TestClient) -> None:
    body = api.get("/api/v1/tools").json()
    assert [t["name"] for t in body["tools"]] == NAMES
    tools = by_name(body)
    assert {n: t["permission"] for n, t in tools.items()} == {
        "list_files": "read",
        "read_file": "read",
        "write_file": "write",
        "run_command": "exec",
        "remember": "write",
        "search_knowledge": "read",
        "delegate": "exec",
        "skill_list": "read",
        "skill_view": "read",
    }
    run = tools["run_command"]
    assert run["requires_approval"] is True  # SEED_APPROVAL_REQUIRED_TOOLS defaults to it
    assert tools["write_file"]["requires_approval"] is False
    assert tools["delegate"]["deferred"] is True and tools["read_file"]["deferred"] is False
    assert "sandbox" in str(run["available_in"])
    assert "Agents:" not in str(tools["delegate"]["description"])  # no roster stub
    assert run["timeout_s"] > 60  # the command's own limit plus the wait for the sandbox
    args = {a["name"]: a for a in run["arguments"]}  # type: ignore[attr-defined]
    assert args["command"]["required"] is True and args["command"]["type"] == "string"
    assert args["timeout_s"]["required"] is False and args["timeout_s"]["type"] == "integer"
    assert body["window_hours"] == 24 and body["usage"] == []
    for bad in ("0", "721", "x"):
        assert api.get(f"/api/v1/tools?hours={bad}").status_code == 422


def test_the_approval_policy_follows_the_setting(db_settings: Settings) -> None:
    settings = db_settings.model_copy(
        update={
            "ollama_api_key": SecretStr("unused"),
            "approval_required_tools": ["write_file", "delegate"],
        }
    )
    with start(settings) as c:
        tools = by_name(sign_in(c).get("/api/v1/tools").json())
    assert {n for n, t in tools.items() if t["requires_approval"]} == {"write_file", "delegate"}


def add_events(db_url: str, task_id: str, *results: tuple[dict[str, object], float]) -> None:
    """Record tool_result events for a task, each `hours_ago`."""
    with psycopg.connect(db_url) as conn:
        for i, (data, hours_ago) in enumerate(results, start=100):
            conn.execute(
                "INSERT INTO task_events (task_id, seq, attempt, type, data, created_at) "
                "VALUES (%s, %s, 1, 'tool_result', %s, now() - make_interval(secs => %s))",
                (task_id, i, json.dumps(data), hours_ago * 3600),
            )


def test_usage_counts_recorded_tool_results_in_the_window(api: TestClient, db_url: str) -> None:
    task = api.post("/api/v1/tasks", json={"model": "m", "prompt": "p"}).json()["id"]
    ok = {"tool": "read_file", "ok": True, "duration_ms": 10}
    add_events(
        db_url,
        task,
        (ok, 1),
        ({**ok, "duration_ms": 30}, 2),
        (
            {
                "tool": "read_file",
                "ok": False,
                "error_kind": "tool_error",
                "error": "No such file: a.txt",
                "duration_ms": 5,
            },
            2,
        ),
        ({"tool": "run_command", "ok": False, "error_kind": "denied", "duration_ms": 0}, 1),
        ({"tool": "run_command", "ok": False, "error_kind": "denied", "duration_ms": 0}, 1),
        ({"tool": "run_command", "ok": False, "error_kind": "denied", "duration_ms": 0}, 1),
        ({"tool": "run_command", "ok": False, "error_kind": "timeout"}, 1),
        ({"tool": "delegate", "ok": True}, 1),
        ({"id": "c", "ok": False, "error_kind": "limit"}, 1),  # no tool named: not counted
        ({**ok, "duration_ms": 999}, 48),  # outside the window
    )
    body = api.get("/api/v1/tools").json()
    # Most used first.
    assert [u["tool"] for u in body["usage"]] == ["run_command", "read_file", "delegate"]
    use = by_name(body, "usage")
    assert use["read_file"] == {
        "tool": "read_file",
        "calls": 3,
        "ok": 2,
        "failed": 1,
        "avg_ms": 15,
        "failures": {"tool_error": 1},
        "reasons": [{"message": "No such file: a.txt", "count": 1}],
    }
    assert use["run_command"]["failed"] == 4 and use["run_command"]["ok"] == 0
    assert use["run_command"]["failures"] == {"denied": 3, "timeout": 1}
    # Failures with no message are not listed; the commonest messages come first, at most three.
    assert use["run_command"]["reasons"] == []
    assert use["run_command"]["avg_ms"] == 0  # the one event without a duration is skipped
    assert use["delegate"]["avg_ms"] is None
    wide = api.get("/api/v1/tools?hours=72").json()
    assert by_name(wide, "usage")["read_file"]["calls"] == 4


def test_failure_reasons_are_the_three_commonest_messages(api: TestClient, db_url: str) -> None:
    task = api.post("/api/v1/tasks", json={"model": "m", "prompt": "p"}).json()["id"]

    def bad(message: str) -> tuple[dict[str, object], float]:
        return ({"tool": "list_files", "ok": False, "error": message}, 1)

    add_events(
        db_url,
        task,
        *[bad("No such directory: x")] * 4,
        *[bad("Path escapes the workspace.")] * 3,
        *[bad("No such directory: x" + "y" * 300)] * 2,  # cut to 200 characters
        bad("zeta"),
        bad("alpha"),
    )
    reasons = by_name(api.get("/api/v1/tools").json(), "usage")["list_files"]["reasons"]
    assert reasons == [
        {"message": "No such directory: x", "count": 4},
        {"message": "Path escapes the workspace.", "count": 3},
        {"message": "No such directory: x" + "y" * 180, "count": 2},
    ]
