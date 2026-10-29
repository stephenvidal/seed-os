"""Tasks in a project (D-023): a task started outside a chat can run in a project
and gets its instructions, memory and knowledge like a chat turn does."""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api.chat.store import project_context
from seed_api.config import Settings
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import TaskStore
from seed_api.flow.worker import Worker
from seed_api.projects.knowledge import KnowledgeStore
from seed_api.projects.memory import MemoryStore
from seed_api.projects.store import ProjectStore

from .conftest import sign_in, start
from .fakes import ScriptedProvider, calls, reply

MODEL = "deepseek-v4.1-flash"


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


@pytest.mark.anyio
async def test_a_project_task_gets_the_projects_instructions_memory_and_tools(
    pool: Pool, tmp_path: Path
) -> None:
    p = await ProjectStore(pool).create(owner="admin", name="Garden", instructions="Be brief.")
    memory = MemoryStore(pool)
    await memory.add("admin", p.id, "The garden faces south.")
    await KnowledgeStore(pool).add("admin", p.id, "guide.md", "Water tomatoes twice a week.")
    tasks = TaskStore(pool)
    async with pool.connection() as conn:
        project = await project_context(conn, "admin", p.id)
    task, _ = await tasks.create(
        created_by="admin",
        title="Plan",
        model="fake",
        prompt="Plan the week",
        max_attempts=3,
        idempotency_key=None,
        **project,
    )
    assert (task.project_id, task.instructions, task.conversation_id) == (p.id, "Be brief.", None)

    provider = ScriptedProvider(
        [
            calls(
                ("search_knowledge", {"query": "tomatoes"}),
                ("remember", {"content": "Prefers short plans."}),
            ),
            reply("Done."),
        ]
    )
    settings = Settings(workspace_root=str(tmp_path), worker_lease_seconds=3)
    assert await Worker(tasks, settings, lambda: provider, worker_id="w").run_once()
    system = provider.requests[0].messages[0].content
    assert "Be brief." in system and "The garden faces south." in system
    names = [t.name for t in provider.requests[0].tools]
    assert "search_knowledge" in names and "remember" in names
    results = [m.content for m in provider.requests[1].messages if m.role == "tool"]
    assert "twice a week" in results[0]
    [proposed] = await memory.list("admin", p.id, status="proposed")
    assert proposed.content == "Prefers short plans."
    assert (proposed.source_task_id, proposed.source_conversation_id) == (task.id, None)


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings.model_copy(update={"ollama_api_key": SecretStr("unused")})) as c:
        yield sign_in(c)


def test_start_list_and_leave_project_tasks(api: TestClient, db_url: str) -> None:
    p = api.post("/api/v1/projects", json={"name": "Garden", "instructions": "Be brief."}).json()
    body = {"model": MODEL, "prompt": "Plan the week", "project_id": p["id"]}
    r = api.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": "k1"})
    assert r.status_code == 201 and r.json()["project_id"] == p["id"]
    task = r.json()
    assert (
        api.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": "k1"}).status_code == 200
    )
    moved = {**body, "project_id": None}
    r = api.post("/api/v1/tasks", json=moved, headers={"Idempotency-Key": "k1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "idempotency_conflict"

    loose = api.post("/api/v1/tasks", json={"model": MODEL, "prompt": "loose"}).json()
    assert loose["project_id"] is None
    api.post("/api/v1/conversations", json={"model": MODEL, "prompt": "hi", "project_id": p["id"]})

    listed = api.get("/api/v1/tasks", params={"project_id": p["id"]}).json()
    assert [t["id"] for t in listed] == [task["id"]]  # no chat turns, no other tasks
    assert len(api.get("/api/v1/tasks").json()) == 3
    assert api.get(f"/api/v1/projects/{p['id']}").json()["tasks"] == 1

    r = api.post("/api/v1/tasks", json={**body, "project_id": str(uuid.uuid4())})
    assert r.status_code == 404 and r.json()["error"]["code"] == "project_not_found"
    assert api.post("/api/v1/tasks", json={**body, "project_id": "nope"}).status_code == 422

    with psycopg.connect(db_url) as conn:
        theirs = uuid.uuid4()
        conn.execute(
            "INSERT INTO projects (id, owner, name) VALUES (%s, 'other', 'Theirs')", (theirs,)
        )
        copied = conn.execute(
            "SELECT instructions FROM tasks WHERE id = %s", (task["id"],)
        ).fetchone()
    assert copied == ("Be brief.",)
    r = api.post("/api/v1/tasks", json={**body, "project_id": str(theirs)})
    assert r.status_code == 404 and r.json()["error"]["code"] == "project_not_found"

    # Deleting the project keeps the task, outside any project.
    assert api.delete(f"/api/v1/projects/{p['id']}").status_code == 204
    assert api.get(f"/api/v1/tasks/{task['id']}").json()["project_id"] is None
