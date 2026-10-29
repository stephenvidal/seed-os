"""Project memory (D-018): the agent proposes notes, the owner approves them, and
approved notes reach the model in the project's later turns."""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api.chat.store import ChatStore
from seed_api.config import Settings
from seed_api.core.tools import ToolFailure
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import TaskStore
from seed_api.flow.worker import Worker
from seed_api.projects.memory import (
    MAX_PROPOSALS_PER_TASK,
    MEMORY_BUDGET_CHARS,
    MemoryStore,
    notes_for_prompt,
)
from seed_api.projects.store import ProjectStore

from .conftest import sign_in, start
from .fakes import ScriptedProvider, Step, calls, reply

MODEL = "deepseek-v4.1-flash"
NOTES = "Notes from this project's memory, approved by the owner:\n"


# --- Store, tool and worker ---------------------------------------------------


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


async def run(pool: Pool, tmp_path: Path, script: list[Step]) -> ScriptedProvider:
    provider = ScriptedProvider(script)
    settings = Settings(workspace_root=str(tmp_path), worker_lease_seconds=3)
    assert await Worker(TaskStore(pool), settings, lambda: provider, worker_id="w").run_once()
    return provider


async def send(chat: ChatStore, cid: uuid.UUID, prompt: str) -> None:
    await chat.send(
        cid,
        owner="admin",
        prompt=prompt,
        model=None,
        max_attempts=3,
        idempotency_key=None,
        context_turns=20,
    )


def tool_names(provider: ScriptedProvider) -> list[str]:
    return [t.name for t in provider.requests[0].tools]


@pytest.mark.anyio
async def test_the_agent_proposes_and_only_approved_notes_reach_the_model(
    pool: Pool, tmp_path: Path
) -> None:
    projects, chat, memory = ProjectStore(pool), ChatStore(pool), MemoryStore(pool)
    p = await projects.create(owner="admin", name="Site", instructions="")
    conv, first, _ = await chat.start(
        owner="admin",
        model="fake",
        prompt="We use plain CSS",
        max_attempts=3,
        idempotency_key=None,
        project_id=p.id,
    )
    assert first.project_id == p.id and first.memory is None
    provider = await run(
        pool,
        tmp_path,
        [calls(("remember", {"content": "The site uses  plain CSS."})), reply("Proposed.")],
    )
    assert "remember" in tool_names(provider)
    result = next(m for m in provider.requests[1].messages if m.role == "tool")
    assert '"status": "proposed"' in result.content

    [note] = await memory.list("admin", p.id)
    assert (note.content, note.status, note.created_by) == (
        "The site uses plain CSS.",
        "proposed",
        "agent",
    )
    assert note.source_task_id == first.id and note.source_conversation_id == conv.id
    assert (await projects.get("admin", p.id)).proposed_memories == 1  # type: ignore[union-attr]

    # A proposal is not memory yet.
    await send(chat, conv.id, "next")
    provider = await run(pool, tmp_path, [reply("ok")])
    assert NOTES not in provider.requests[0].messages[0].content

    approved = await memory.update("admin", p.id, note.id, content=None, approve=True)
    assert approved is not None and approved.status == "approved"
    assert approved.approved_by == "admin" and approved.approved_at is not None
    await send(chat, conv.id, "and now")
    provider = await run(pool, tmp_path, [reply("ok")])
    assert provider.requests[0].messages[0].content.endswith(NOTES + "- The site uses plain CSS.")

    # Proposing what is already remembered adds nothing.
    again = await memory.propose(
        p.id, "The site uses plain CSS.", task_id=uuid.uuid4(), conversation_id=None
    )
    assert again.id == note.id and again.status == "approved"


@pytest.mark.anyio
async def test_no_memory_tool_outside_a_project(pool: Pool, tmp_path: Path) -> None:
    await ChatStore(pool).start(
        owner="admin", model="fake", prompt="hi", max_attempts=3, idempotency_key=None
    )
    provider = await run(pool, tmp_path, [reply("ok")])
    assert "remember" not in tool_names(provider)


@pytest.mark.anyio
async def test_a_retry_proposes_once_and_proposals_are_limited(pool: Pool) -> None:
    p = await ProjectStore(pool).create(owner="admin", name="Site", instructions="")
    memory = MemoryStore(pool)
    task = (
        await TaskStore(pool).create(
            created_by="admin",
            title="t",
            model="m",
            prompt="p",
            max_attempts=3,
            idempotency_key=None,
        )
    )[0].id
    one = await memory.propose(p.id, "note 0", task_id=task, conversation_id=None)
    assert (await memory.propose(p.id, "note 0", task_id=task, conversation_id=None)).id == one.id
    for i in range(1, MAX_PROPOSALS_PER_TASK):
        await memory.propose(p.id, f"note {i}", task_id=task, conversation_id=None)
    assert len(await memory.list("admin", p.id)) == MAX_PROPOSALS_PER_TASK
    with pytest.raises(ToolFailure):
        await memory.propose(p.id, "one too many", task_id=task, conversation_id=None)
    await ProjectStore(pool).delete(p.id, owner="admin")
    with pytest.raises(ToolFailure):
        await memory.propose(p.id, "gone", task_id=uuid.uuid4(), conversation_id=None)


def test_memory_in_the_prompt_is_bounded_by_whole_notes() -> None:
    assert notes_for_prompt([]) is None
    assert notes_for_prompt(["newest", "older"]) == "- newest\n- older"
    big = "x" * 450
    text = notes_for_prompt([big] * 20)
    assert text is not None and len(text) <= MEMORY_BUDGET_CHARS
    assert all(line == f"- {big}" for line in text.split("\n"))  # no note is cut


# --- HTTP API -----------------------------------------------------------------


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings.model_copy(update={"ollama_api_key": SecretStr("unused")})) as c:
        yield sign_in(c)


def test_owner_adds_edits_approves_and_deletes_notes(api: TestClient, db_url: str) -> None:
    p = api.post("/api/v1/projects", json={"name": "Site"}).json()
    base = f"/api/v1/projects/{p['id']}/memories"
    assert api.get(base).json() == []

    r = api.post(base, json={"content": "  Stephen   prefers short answers. "})
    assert r.status_code == 201
    mine = r.json()
    assert (mine["content"], mine["status"], mine["created_by"]) == (
        "Stephen prefers short answers.",
        "approved",
        "admin",
    )
    for bad in ({"content": "  "}, {"content": "x" * 501}):
        assert api.post(base, json=bad).status_code == 422

    with psycopg.connect(db_url) as conn:  # an agent proposal, as the tool writes it
        proposed = uuid.uuid4()
        conn.execute(
            "INSERT INTO project_memories (id, project_id, content, status, created_by) "
            "VALUES (%s, %s, 'Deploys go out on Fridays.', 'proposed', 'agent')",
            (proposed, p["id"]),
        )
    assert api.get(f"/api/v1/projects/{p['id']}").json()["proposed_memories"] == 1
    listed = api.get(base).json()
    assert [(m["status"], m["content"]) for m in listed] == [
        ("proposed", "Deploys go out on Fridays."),
        ("approved", "Stephen prefers short answers."),
    ]
    assert [m["id"] for m in api.get(base, params={"status": "approved"}).json()] == [mine["id"]]

    r = api.patch(
        f"{base}/{proposed}", json={"content": "Deploys go out on Thursdays.", "approve": True}
    )
    assert (
        r.json()["status"] == "approved" and r.json()["content"] == "Deploys go out on Thursdays."
    )
    assert r.json()["approved_by"] == "admin"
    assert api.get(f"/api/v1/projects/{p['id']}").json()["proposed_memories"] == 0
    r = api.patch(f"{base}/{mine['id']}", json={"content": "Short answers, please."})
    assert r.json()["content"] == "Short answers, please." and r.json()["status"] == "approved"

    assert api.delete(f"{base}/{proposed}").status_code == 204
    assert [m["id"] for m in api.get(base).json()] == [mine["id"]]
    missing = f"{base}/{uuid.uuid4()}"
    assert api.patch(missing, json={"approve": True}).status_code == 404
    assert api.delete(missing).status_code == 404
    other = f"/api/v1/projects/{uuid.uuid4()}/memories"
    assert api.get(other).status_code == 404
    assert api.post(other, json={"content": "x"}).status_code == 404
    # A note is reached only through its own project.
    q = api.post("/api/v1/projects", json={"name": "Other"}).json()
    assert api.delete(f"/api/v1/projects/{q['id']}/memories/{mine['id']}").status_code == 404

    with psycopg.connect(db_url) as conn:
        audit = conn.execute(
            "SELECT action, target FROM audit_log WHERE action LIKE 'memory_%' ORDER BY id"
        ).fetchall()
    assert audit == [
        ("memory_added", mine["id"]),
        ("memory_approved", str(proposed)),
        ("memory_updated", mine["id"]),
        ("memory_deleted", str(proposed)),
    ]


def test_notes_belong_to_their_owner(api: TestClient, db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        theirs, note = uuid.uuid4(), uuid.uuid4()
        conn.execute(
            "INSERT INTO projects (id, owner, name) VALUES (%s, 'other', 'Theirs')", (theirs,)
        )
        conn.execute(
            "INSERT INTO project_memories (id, project_id, content, status, created_by) "
            "VALUES (%s, %s, 'secret', 'approved', 'other')",
            (note, theirs),
        )
    base = f"/api/v1/projects/{theirs}/memories"
    assert api.get(base).status_code == 404
    assert api.post(base, json={"content": "x"}).status_code == 404
    assert api.patch(f"{base}/{note}", json={"content": "mine now"}).status_code == 404
    assert api.delete(f"{base}/{note}").status_code == 404
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT content FROM project_memories").fetchall() == [("secret",)]
