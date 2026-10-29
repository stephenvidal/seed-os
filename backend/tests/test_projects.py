"""Projects (D-017): conversations grouped under a name and instructions the model
sees on every turn sent in the project."""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api.chat.store import ChatError, ChatStore
from seed_api.config import Settings
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import TaskStore
from seed_api.flow.worker import Worker
from seed_api.models import SYSTEM_PROMPT
from seed_api.projects.store import ProjectStore

from .conftest import sign_in, start
from .fakes import ScriptedProvider, reply

MODEL = "deepseek-v4.1-flash"


# --- Store and worker ---------------------------------------------------------


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def pool(db_url: str) -> AsyncIterator[Pool]:
    pool = make_pool(db_url, max_size=4)
    await pool.open(wait=True)
    await migrate(pool)
    yield pool
    await pool.close()


async def system_sent(pool: Pool, tmp_path: Path) -> str:
    """Runs the next queued task and returns the system prompt the model got."""
    provider = ScriptedProvider([reply("ok")])
    settings = Settings(workspace_root=str(tmp_path), worker_lease_seconds=3)
    assert await Worker(TaskStore(pool), settings, lambda: provider, worker_id="w").run_once()
    first = provider.requests[0].messages[0]
    assert first.role == "system"
    return first.content


@pytest.mark.anyio
async def test_turns_carry_the_instructions_they_were_sent_with(pool: Pool, tmp_path: Path) -> None:
    projects, chat = ProjectStore(pool), ChatStore(pool)
    p = await projects.create(owner="admin", name="Site", instructions="Answer in French.")
    conv, first, _ = await chat.start(
        owner="admin",
        model="fake",
        prompt="hi",
        max_attempts=3,
        idempotency_key=None,
        project_id=p.id,
    )
    assert conv.project_id == p.id and first.instructions == "Answer in French."
    sent = await system_sent(pool, tmp_path)
    assert sent.startswith(SYSTEM_PROMPT) and sent.endswith("\nAnswer in French.")

    # Changing the instructions reaches the next turn, not the one already sent.
    await projects.update(p.id, owner="admin", name=None, instructions="Be brief.")
    assert (await TaskStore(pool).get(first.id)).instructions == "Answer in French."  # type: ignore[union-attr]
    second, _ = await chat.send(
        conv.id,
        owner="admin",
        prompt="again",
        model=None,
        max_attempts=3,
        idempotency_key=None,
        context_turns=20,
    )
    assert second.instructions == "Be brief."
    assert (await system_sent(pool, tmp_path)).endswith("\nBe brief.")

    # Out of the project, turns get the plain system prompt.
    await chat.move(conv.id, owner="admin", project_id=None)
    await chat.send(
        conv.id,
        owner="admin",
        prompt="third",
        model=None,
        max_attempts=3,
        idempotency_key=None,
        context_turns=20,
    )
    assert await system_sent(pool, tmp_path) == SYSTEM_PROMPT


@pytest.mark.anyio
async def test_projects_belong_to_their_owner(pool: Pool) -> None:
    projects, chat = ProjectStore(pool), ChatStore(pool)
    theirs = await projects.create(owner="other", name="Theirs", instructions="")
    assert await projects.get("admin", theirs.id) is None
    assert await projects.list("admin") == []
    assert await projects.update(theirs.id, owner="admin", name="x", instructions=None) is None
    assert await projects.delete(theirs.id, owner="admin") is None
    with pytest.raises(ChatError) as e:
        await chat.start(
            owner="admin",
            model="fake",
            prompt="hi",
            max_attempts=3,
            idempotency_key=None,
            project_id=theirs.id,
        )
    assert e.value.code == "project_not_found"
    assert await chat.list("admin", limit=10) == []  # nothing half-made
    conv, _, _ = await chat.start(
        owner="admin", model="fake", prompt="hi", max_attempts=3, idempotency_key=None
    )
    with pytest.raises(ChatError) as e:
        await chat.move(conv.id, owner="admin", project_id=theirs.id)
    assert e.value.code == "project_not_found"
    with pytest.raises(ChatError) as e:
        await chat.move(conv.id, owner="other", project_id=theirs.id)
    assert e.value.code == "not_found"


# --- HTTP API -----------------------------------------------------------------


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings.model_copy(update={"ollama_api_key": SecretStr("unused")})) as c:
        yield sign_in(c)


def test_projects_need_a_signed_in_admin_and_csrf(db_settings: Settings) -> None:
    with start(db_settings) as c:
        assert c.get("/api/v1/projects").status_code == 401
        sign_in(c)
        del c.headers["X-CSRF-Token"]
        r = c.post("/api/v1/projects", json={"name": "x"})
        assert r.json()["error"]["code"] == "csrf_failed"


def test_create_list_update_and_delete(api: TestClient, db_url: str) -> None:
    r = api.post(
        "/api/v1/projects", json={"name": "  Launch\n site ", "instructions": " Be kind. "}
    )
    assert r.status_code == 201
    p = r.json()
    assert (p["name"], p["instructions"], p["conversations"]) == ("Launch site", "Be kind.", 0)
    other = api.post("/api/v1/projects", json={"name": "Other"}).json()
    assert other["instructions"] == ""

    for bad in ({"name": "   "}, {"name": "x" * 81}, {"name": "x", "instructions": "y" * 20_001}):
        assert api.post("/api/v1/projects", json=bad).status_code == 422
    assert api.patch(f"/api/v1/projects/{p['id']}", json={"name": " "}).status_code == 422

    conv = api.post(
        "/api/v1/conversations", json={"model": MODEL, "prompt": "hi", "project_id": p["id"]}
    ).json()["conversation"]
    assert conv["project_id"] == p["id"]
    loose = api.post("/api/v1/conversations", json={"model": MODEL, "prompt": "loose"}).json()
    assert loose["conversation"]["project_id"] is None
    r = api.post(
        "/api/v1/conversations",
        json={"model": MODEL, "prompt": "x", "project_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "project_not_found"

    listed = api.get("/api/v1/projects").json()
    assert [(x["name"], x["conversations"]) for x in listed] == [("Other", 0), ("Launch site", 1)]
    only = api.get("/api/v1/conversations", params={"project_id": p["id"]}).json()
    assert [c["id"] for c in only] == [conv["id"]]

    r = api.patch(f"/api/v1/projects/{p['id']}", json={"instructions": "Be brief."})
    assert r.json()["name"] == "Launch site" and r.json()["instructions"] == "Be brief."
    r = api.patch(f"/api/v1/projects/{p['id']}", json={"name": "Renamed"})
    assert r.json()["name"] == "Renamed" and r.json()["instructions"] == "Be brief."
    assert [x["name"] for x in api.get("/api/v1/projects").json()] == ["Renamed", "Other"]
    assert api.get(f"/api/v1/projects/{p['id']}").json()["conversations"] == 1
    missing = f"/api/v1/projects/{uuid.uuid4()}"
    assert api.get(missing).status_code == 404
    assert api.patch(missing, json={"name": "x"}).status_code == 404
    assert api.delete(missing).status_code == 404

    # Moving a conversation in and out.
    moved = api.put(
        f"/api/v1/conversations/{loose['conversation']['id']}/project",
        json={"project_id": other["id"]},
    )
    assert moved.status_code == 200 and moved.json()["project_id"] == other["id"]
    out = api.put(
        f"/api/v1/conversations/{loose['conversation']['id']}/project", json={"project_id": None}
    )
    assert out.json()["project_id"] is None
    r = api.put(f"/api/v1/conversations/{uuid.uuid4()}/project", json={"project_id": other["id"]})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"

    # Deleting the project keeps its conversations.
    assert api.delete(f"/api/v1/projects/{p['id']}").status_code == 204
    assert (
        api.get(f"/api/v1/conversations/{conv['id']}").json()["conversation"]["project_id"] is None
    )
    assert api.get(f"/api/v1/projects/{p['id']}").status_code == 404

    with psycopg.connect(db_url) as conn:
        audit = conn.execute(
            "SELECT action, target, detail FROM audit_log "
            "WHERE action LIKE 'project_%' OR action = 'conversation_moved' ORDER BY id"
        ).fetchall()
    assert [(a, t) for a, t, _ in audit] == [
        ("project_created", p["id"]),
        ("project_created", other["id"]),
        ("project_updated", p["id"]),
        ("project_updated", p["id"]),
        ("conversation_moved", loose["conversation"]["id"]),
        ("conversation_moved", loose["conversation"]["id"]),
        ("project_deleted", p["id"]),
    ]
    assert audit[2][2] == {"fields": ["instructions"]}
    assert audit[-1][2] == {"conversations": 1}


def test_studio_lists_a_projects_files(api: TestClient, db_url: str) -> None:
    p = api.post("/api/v1/projects", json={"name": "Site"}).json()
    inside = api.post(
        "/api/v1/conversations", json={"model": MODEL, "prompt": "a", "project_id": p["id"]}
    ).json()["conversation"]["id"]
    outside = api.post("/api/v1/conversations", json={"model": MODEL, "prompt": "b"}).json()
    with psycopg.connect(db_url) as conn:
        for conv, path in ((inside, "in.txt"), (outside["conversation"]["id"], "out.txt")):
            conn.execute(
                "INSERT INTO artifacts (id, workspace_id, conversation_id, path) "
                "VALUES (%s, %s, %s, %s)",
                (uuid.uuid4(), conv, conv, path),
            )
        conn.execute(
            "INSERT INTO artifact_versions (artifact_id, version, sha256, size) "
            "SELECT id, 1, NULL, NULL FROM artifacts"
        )
    rows = api.get("/api/v1/artifacts", params={"project_id": p["id"]}).json()
    assert [r["path"] for r in rows] == ["in.txt"]
    assert len(api.get("/api/v1/artifacts").json()) == 2


def test_system_prompt_asks_for_responsive_self_contained_html() -> None:
    assert "viewport" in SYSTEM_PROMPT
    assert "media queries" in SYSTEM_PROMPT
    assert "no network" in SYSTEM_PROMPT
