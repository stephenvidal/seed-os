"""Memory about the owner (D-040): SEED proposes, the owner approves, every run of
SEED's own is given the approved notes."""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api.config import Settings
from seed_api.core.tools import ToolFailure
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import TaskStore
from seed_api.flow.worker import Worker
from seed_api.owner_memory import OwnerMemoryStore

from .conftest import sign_in, start
from .fakes import ScriptedProvider, Step, calls, reply


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


async def run(pool: Pool, tmp_path: Path, *script: Step, owner: str = "admin"):  # type: ignore[no-untyped-def]
    store = TaskStore(pool)
    task, _ = await store.create(
        created_by=owner, title="t", model="fake", prompt="hi", max_attempts=3, idempotency_key=None
    )
    provider = ScriptedProvider(list(script))
    w = Worker(store, Settings(workspace_root=str(tmp_path)), lambda: provider)
    assert await w.run_once()
    return task, provider


@pytest.mark.anyio
async def test_a_proposal_reaches_the_model_only_after_approval(pool: Pool, tmp_path: Path) -> None:
    notes = OwnerMemoryStore(pool)
    script = [calls(("remember_owner", {"content": "Prefers  short answers"})), reply("Noted")]
    task, _ = await run(pool, tmp_path, *script)
    [proposed] = await notes.list("admin")
    assert proposed.status == "proposed" and proposed.content == "Prefers short answers"
    assert proposed.source_task_id == task.id and proposed.created_by == "agent"

    _, provider = await run(pool, tmp_path, reply("ok"))
    assert "short answers" not in provider.requests[0].messages[0].content

    assert await notes.update("admin", proposed.id, content=None, approve=True)
    _, provider = await run(pool, tmp_path, reply("ok"))
    system = provider.requests[0].messages[0].content
    assert "What you know about the owner, approved by them:\n- Prefers short answers" in system

    _, provider = await run(pool, tmp_path, reply("ok"), owner="other")
    assert "short answers" not in provider.requests[0].messages[0].content  # theirs only


@pytest.mark.anyio
async def test_proposals_are_not_duplicated_and_are_limited_per_task(pool: Pool) -> None:
    notes = OwnerMemoryStore(pool)
    mine = await notes.add("admin", "Lives in Lisbon")
    task = uuid.uuid4()
    async with pool.connection() as conn:  # a task row for the foreign key
        await conn.execute(
            "INSERT INTO tasks (id, created_by, title, model, prompt, state, max_attempts) "
            "VALUES (%s, 'admin', 't', 'fake', 'p', 'completed', 1)",
            (task,),
        )
    again = await notes.propose("admin", "Lives in Lisbon", task_id=task, conversation_id=None)
    assert again.id == mine.id and again.status == "approved"
    for i in range(5):
        await notes.propose("admin", f"fact {i}", task_id=task, conversation_id=None)
    with pytest.raises(ToolFailure):
        await notes.propose("admin", "one too many", task_id=task, conversation_id=None)


@pytest.mark.anyio
async def test_an_owner_cannot_change_anothers_notes(pool: Pool) -> None:
    notes = OwnerMemoryStore(pool)
    theirs = await notes.add("other", "Has a cat")
    assert await notes.update("admin", theirs.id, content="x", approve=True) is None
    assert await notes.delete("admin", theirs.id) is False
    assert await notes.list("admin") == []


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings.model_copy(update={"ollama_api_key": SecretStr("unused")})) as c:
        yield sign_in(c)


def test_the_api_adds_edits_approves_and_deletes(api: TestClient, db_url: str) -> None:
    import psycopg

    assert api.get("/api/v1/memory").json() == []
    made = api.post("/api/v1/memory", json={"content": "  Works   nights "})
    assert made.status_code == 201 and made.json()["content"] == "Works nights"
    assert made.json()["status"] == "approved"
    assert api.post("/api/v1/memory", json={"content": "   "}).status_code == 422
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO owner_memories (id, owner, content, status, created_by) "
            "VALUES (%s, 'admin', 'Likes tea', 'proposed', 'agent')",
            (uuid.uuid4(),),
        )
    listed = api.get("/api/v1/memory").json()
    assert [n["status"] for n in listed] == ["proposed", "approved"]
    pid = listed[0]["id"]
    assert api.get("/api/v1/memory?status=proposed").json()[0]["id"] == pid
    ok = api.patch(f"/api/v1/memory/{pid}", json={"content": "Likes green tea", "approve": True})
    assert ok.json()["status"] == "approved" and ok.json()["content"] == "Likes green tea"
    assert api.delete(f"/api/v1/memory/{pid}").status_code == 204
    assert api.delete(f"/api/v1/memory/{pid}").status_code == 404
    assert api.patch(f"/api/v1/memory/{uuid.uuid4()}", json={"approve": True}).status_code == 404


HERMES_USER_MD = (
    "\ufeffName: Stephen.\r\n§\r\nPrefers   short answers.\n§\n\n§\n"
    "Works nights\n§\nPrefers short answers."
)


def test_hermes_entries_split_on_the_section_line_only() -> None:
    from seed_api.owner_memory import hermes_entries

    assert hermes_entries(HERMES_USER_MD) == [
        "Name: Stephen.",
        "Prefers short answers.",
        "Works nights",
        "Prefers short answers.",
    ]
    assert hermes_entries("Costs 5 § per item") == ["Costs 5 § per item"]  # a bare § stays


def test_the_api_imports_a_hermes_memory_file(api: TestClient) -> None:
    api.post("/api/v1/memory", json={"content": "Works nights"})
    long = "x" * 501
    body = {"text": HERMES_USER_MD + "\n§\n" + long}
    preview = api.post("/api/v1/memory/import?preview=true", json=body)
    assert preview.status_code == 200
    assert preview.json()["added"] == ["Name: Stephen.", "Prefers short answers."]
    assert [s["reason"] for s in preview.json()["skipped"]] == [
        "duplicate",
        "duplicate",
        "too_long",
    ]
    assert len(api.get("/api/v1/memory").json()) == 1  # preview saves nothing
    done = api.post("/api/v1/memory/import", json=body)
    assert done.json()["added"] == ["Name: Stephen.", "Prefers short answers."]
    notes = api.get("/api/v1/memory").json()
    assert sorted(n["content"] for n in notes) == [
        "Name: Stephen.",
        "Prefers short answers.",
        "Works nights",
    ]
    assert all(n["status"] == "approved" for n in notes)
    again = api.post("/api/v1/memory/import", json=body).json()
    assert again["added"] == [] and len(again["skipped"]) == 5
    too_big = api.post("/api/v1/memory/import", json={"text": "a" * 50_001})
    assert too_big.status_code == 422
