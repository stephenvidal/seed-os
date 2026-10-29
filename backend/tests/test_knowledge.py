"""Project knowledge (D-021): text documents the owner adds to a project, searched
by the agent in that project's chats."""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api.chat.store import ChatStore
from seed_api.config import Settings
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import TaskStore
from seed_api.flow.worker import Worker
from seed_api.projects.knowledge import CHUNK_CHARS, MAX_DOCUMENT_CHARS, KnowledgeStore, chunk
from seed_api.projects.store import ProjectStore

from .conftest import sign_in, start
from .fakes import ScriptedProvider, calls, reply

MODEL = "deepseek-v4.1-flash"
GUIDE = """# Garden guide

Tomatoes need full sun and deep watering twice a week.

Basil grows well next to tomatoes and keeps pests away.

Lettuce prefers shade in summer."""


def test_chunks_keep_paragraphs_and_their_size() -> None:
    assert chunk("one\n\ntwo") == ["one\n\ntwo"]
    assert chunk("a" * 10 + "\n\n" + "b" * 10, size=15) == ["a" * 10, "b" * 10]
    words = " ".join(["garden"] * 1000)
    parts = chunk(words)
    assert all(len(p) <= CHUNK_CHARS for p in parts)
    assert " ".join(parts) == words  # cut on spaces, nothing lost
    assert chunk("x" * 3500) == ["x" * 1500, "x" * 1500, "x" * 500]  # no spaces: hard cuts
    assert chunk("\n\n  \n\n") == []


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


@pytest.mark.anyio
async def test_search_finds_passages_in_its_own_project_only(pool: Pool) -> None:
    projects, knowledge = ProjectStore(pool), KnowledgeStore(pool)
    garden = await projects.create(owner="admin", name="Garden", instructions="")
    other = await projects.create(owner="admin", name="Other", instructions="")
    doc = await knowledge.add("admin", garden.id, "guide.md", GUIDE)
    assert doc is not None and (doc.chunks, doc.chars) == (1, len(GUIDE))
    await knowledge.add("admin", other.id, "notes.txt", "Tomatoes are a fruit.")

    [hit] = await knowledge.search(garden.id, "watering tomato")  # stemmed: tomato ~ tomatoes
    assert (hit.document, hit.part) == ("guide.md", 1) and "deep watering" in hit.text
    assert await knowledge.search(garden.id, "cucumber") == []
    assert [h.document for h in await knowledge.search(other.id, "tomatoes")] == ["notes.txt"]
    assert await knowledge.search(garden.id, '"tomatoes are a fruit"') == []

    # Best match first, and each chunk is a hit of its own.
    long = "\n\n".join(
        [f"Paragraph {i} about roses." + " filler" * 210 for i in range(3)]
        + ["Roses, roses, roses: pruning roses in spring."]
    )
    many = await knowledge.add("admin", garden.id, "roses.md", long)
    assert many is not None and many.chunks == 4
    hits = await knowledge.search(garden.id, "roses")
    assert [h.part for h in hits][0] == 4 and len(hits) == 4  # the densest match first

    assert await knowledge.delete("admin", garden.id, many.id)
    assert await knowledge.search(garden.id, "roses") == []
    assert not await knowledge.delete("admin", garden.id, many.id)


@pytest.mark.anyio
async def test_the_agent_searches_in_project_chats_only(pool: Pool, tmp_path: Path) -> None:
    projects, chat = ProjectStore(pool), ChatStore(pool)
    p = await projects.create(owner="admin", name="Garden", instructions="")
    await KnowledgeStore(pool).add("admin", p.id, "guide.md", GUIDE)
    await chat.start(
        owner="admin",
        model="fake",
        prompt="when do I water tomatoes?",
        max_attempts=3,
        idempotency_key=None,
        project_id=p.id,
    )
    settings = Settings(workspace_root=str(tmp_path), worker_lease_seconds=3)
    provider = ScriptedProvider(
        [calls(("search_knowledge", {"query": "water tomatoes"})), reply("Twice a week.")]
    )
    assert await Worker(TaskStore(pool), settings, lambda: provider, worker_id="w").run_once()
    assert "search_knowledge" in [t.name for t in provider.requests[0].tools]
    result = next(m for m in provider.requests[1].messages if m.role == "tool")
    assert '"document": "guide.md"' in result.content and "twice a week" in result.content

    await chat.start(owner="admin", model="fake", prompt="hi", max_attempts=3, idempotency_key=None)
    provider = ScriptedProvider([reply("ok")])
    assert await Worker(TaskStore(pool), settings, lambda: provider, worker_id="w").run_once()
    assert "search_knowledge" not in [t.name for t in provider.requests[0].tools]


# --- HTTP API -----------------------------------------------------------------


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings.model_copy(update={"ollama_api_key": SecretStr("unused")})) as c:
        yield sign_in(c)


def test_add_list_and_delete_documents(api: TestClient, db_url: str) -> None:
    p = api.post("/api/v1/projects", json={"name": "Garden"}).json()
    base = f"/api/v1/projects/{p['id']}/documents"
    assert api.get(base).json() == []

    r = api.post(base, json={"name": " guide.md ", "content": GUIDE})
    assert r.status_code == 201
    doc = r.json()
    assert (doc["name"], doc["chars"], doc["chunks"], doc["created_by"]) == (
        "guide.md",
        len(GUIDE),
        1,
        "admin",
    )
    api.post(base, json={"name": "a.CSV", "content": "x,y\n1,2"})
    assert [d["name"] for d in api.get(base).json()] == ["a.CSV", "guide.md"]
    assert api.get(f"/api/v1/projects/{p['id']}").json()["documents"] == 2

    taken = api.post(base, json={"name": "guide.md", "content": "again"})
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "name_taken"
    for bad in (
        {"name": "photo.png", "content": "x"},
        {"name": "../guide.md", "content": "x"},
        {"name": "", "content": "x"},
        {"name": "empty.md", "content": " \n "},
        {"name": "bin.txt", "content": "a\x00b"},
        {"name": "big.txt", "content": "x" * (MAX_DOCUMENT_CHARS + 1)},
    ):
        assert api.post(base, json=bad).status_code == 422, bad

    missing = f"/api/v1/projects/{uuid.uuid4()}/documents"
    assert api.get(missing).status_code == 404
    assert api.post(missing, json={"name": "a.md", "content": "x"}).status_code == 404
    assert api.delete(f"{base}/{doc['id']}").status_code == 204
    assert api.delete(f"{base}/{doc['id']}").status_code == 404
    assert [d["name"] for d in api.get(base).json()] == ["a.CSV"]

    with psycopg.connect(db_url) as conn:
        audit = conn.execute(
            "SELECT action, target FROM audit_log WHERE action LIKE 'document_%' ORDER BY id"
        ).fetchall()
        chunks = conn.execute("SELECT count(*) FROM knowledge_chunks").fetchone()
    assert [a for a, _ in audit] == ["document_added", "document_added", "document_deleted"]
    assert audit[2][1] == doc["id"]
    assert chunks == (1,)  # the deleted document's chunks went with it


def test_documents_belong_to_their_owner(api: TestClient, db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        theirs, doc = uuid.uuid4(), uuid.uuid4()
        conn.execute(
            "INSERT INTO projects (id, owner, name) VALUES (%s, 'other', 'Theirs')", (theirs,)
        )
        conn.execute(
            "INSERT INTO knowledge_documents (id, project_id, name, chars, chunks, created_by) "
            "VALUES (%s, %s, 'secret.md', 1, 0, 'other')",
            (doc, theirs),
        )
    base = f"/api/v1/projects/{theirs}/documents"
    assert api.get(base).status_code == 404
    assert api.post(base, json={"name": "a.md", "content": "x"}).status_code == 404
    assert api.delete(f"{base}/{doc}").status_code == 404
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT name FROM knowledge_documents").fetchall() == [("secret.md",)]
