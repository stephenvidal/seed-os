"""Chat over a real Postgres: conversations whose turns run as durable tasks."""

import asyncio
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

from .conftest import sign_in, start
from .fakes import ScriptedProvider, Step, calls, reply

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


@pytest.fixture
def chat(pool: Pool) -> ChatStore:
    return ChatStore(pool)


@pytest.fixture
def tasks(pool: Pool) -> TaskStore:
    return TaskStore(pool)


@pytest.fixture
def wsettings(tmp_path: Path) -> Settings:
    return Settings(workspace_root=str(tmp_path), worker_lease_seconds=3, chat_context_turns=20)


async def begin(chat: ChatStore, prompt: str = "first") -> uuid.UUID:
    conv, _, _ = await chat.start(
        owner="admin", model="fake", prompt=prompt, max_attempts=3, idempotency_key=None
    )
    return conv.id


async def send(chat: ChatStore, cid: uuid.UUID, prompt: str, *, turns: int = 20, key=None):  # type: ignore[no-untyped-def]
    task, _ = await chat.send(
        cid,
        owner="admin",
        prompt=prompt,
        model=None,
        max_attempts=3,
        idempotency_key=key,
        context_turns=turns,
    )
    return task


async def answer(tasks: TaskStore, settings: Settings, script: list[Step]) -> ScriptedProvider:
    provider = ScriptedProvider(script)
    assert await Worker(tasks, settings, lambda: provider, worker_id="w").run_once()
    return provider


@pytest.mark.anyio
async def test_a_turn_carries_the_conversation_and_its_files(
    chat: ChatStore, tasks: TaskStore, wsettings: Settings, tmp_path: Path
) -> None:
    cid = await begin(chat, "make notes.txt")
    await answer(
        tasks,
        wsettings,
        [calls(("write_file", {"path": "notes.txt", "content": "hello"})), reply("Made it.")],
    )
    second = await send(chat, cid, "what is in it?")
    assert second.turn == 2 and second.workspace == cid
    provider = await answer(
        tasks, wsettings, [calls(("read_file", {"path": "notes.txt"})), reply("It says hello.")]
    )
    sent = [(m.role, m.content) for m in provider.requests[0].messages]
    assert sent[1:] == [
        ("user", "make notes.txt"),
        ("assistant", "Made it."),
        ("user", "what is in it?"),
    ]
    # The second turn read the file the first wrote: one workspace per conversation.
    tool_msg = next(m for m in provider.requests[1].messages if m.role == "tool")
    assert '"content":"hello"' in tool_msg.content.replace(" ", "")
    assert (tmp_path / str(cid) / "notes.txt").read_text() == "hello"
    turns = await chat.turns(cid)
    assert [(t.turn, t.state, t.result_text) for t in turns] == [
        (1, "completed", "Made it."),
        (2, "completed", "It says hello."),
    ]


@pytest.mark.anyio
async def test_one_turn_at_a_time_and_failed_turns_carry_nothing(
    chat: ChatStore, tasks: TaskStore, wsettings: Settings
) -> None:
    cid = await begin(chat, "first")
    with pytest.raises(ChatError) as e:
        await send(chat, cid, "too soon")
    assert e.value.code == "turn_in_progress"
    first = (await chat.turns(cid))[0]
    await tasks.request_cancel(first.id)
    second = await send(chat, cid, "second")
    assert second.turn == 2 and second.context == []  # the canceled turn has no answer


@pytest.mark.anyio
async def test_retry_waits_for_the_other_turns(
    chat: ChatStore, tasks: TaskStore, wsettings: Settings
) -> None:
    cid = await begin(chat, "first")
    first = (await chat.turns(cid))[0]
    await tasks.request_cancel(first.id)
    await send(chat, cid, "second")
    # Turns share a workspace: the canceled turn may not run beside the queued one.
    assert await tasks.retry(first.id, extra_attempts=3) is None
    await answer(tasks, wsettings, [reply("two")])
    retried = await tasks.retry(first.id, extra_attempts=3)
    assert retried is not None and retried.state == "queued"


@pytest.mark.anyio
async def test_retry_waits_for_a_turn_that_waits_for_approval(
    chat: ChatStore, tasks: TaskStore, pool: Pool
) -> None:
    cid = await begin(chat, "first")
    first = (await chat.turns(cid))[0]
    await tasks.request_cancel(first.id)
    second = await send(chat, cid, "second")
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE tasks SET state = 'waiting', awaiting_approval = %s WHERE id = %s",
            ('{"id": "c", "name": "run_command", "arguments": {}}', second.id),
        )
    assert await tasks.retry(first.id, extra_attempts=3) is None
    with pytest.raises(ChatError) as e:
        await send(chat, cid, "third")
    assert e.value.code == "turn_in_progress"


@pytest.mark.anyio
async def test_context_keeps_the_latest_turns(
    chat: ChatStore, tasks: TaskStore, wsettings: Settings
) -> None:
    cid = await begin(chat, "q1")
    await answer(tasks, wsettings, [reply("a1")])
    for n in (2, 3):
        await send(chat, cid, f"q{n}")
        await answer(tasks, wsettings, [reply(f"a{n}")])
    fourth = await send(chat, cid, "q4", turns=2)
    assert [m.content for m in fourth.context] == ["q2", "a2", "q3", "a3"]


@pytest.mark.anyio
async def test_conversations_belong_to_their_owner(chat: ChatStore) -> None:
    cid = await begin(chat)
    assert await chat.get("someone-else", cid) is None
    assert await chat.list("someone-else", limit=10) == []
    with pytest.raises(ChatError) as e:
        await chat.send(
            cid,
            owner="someone-else",
            prompt="hi",
            model=None,
            max_attempts=3,
            idempotency_key=None,
            context_turns=20,
        )
    assert e.value.code == "not_found"
    [summary] = await chat.list("admin", limit=10)
    assert summary.id == cid and summary.turns == 1 and summary.last_state == "queued"


@pytest.mark.anyio
async def test_a_resumed_turn_does_not_repeat_its_context(
    chat: ChatStore, tasks: TaskStore, wsettings: Settings
) -> None:
    """The checkpoint already holds the context; resuming must not add it again."""
    cid = await begin(chat, "q1")
    await answer(tasks, wsettings, [reply("a1")])
    turn = await send(chat, cid, "q2")
    a = Worker(
        tasks,
        wsettings,
        lambda: ScriptedProvider([calls(("list_files", {"path": "."})), 30.0]),
        worker_id="a",
    )
    running = asyncio.create_task(a.run_once())
    for _ in range(250):
        t = await tasks.get(turn.id)
        if t is not None and t.checkpoint is not None:
            break
        await asyncio.sleep(0.02)
    a.stop.set()  # graceful shutdown hands the turn back with its checkpoint
    await asyncio.wait_for(running, timeout=5)
    provider = await answer(tasks, wsettings, [reply("a2")])
    roles = [m.role for m in provider.requests[0].messages]
    assert roles == ["system", "user", "assistant", "user", "assistant", "tool"]
    done = await tasks.get(turn.id)
    assert done is not None and done.state == "completed" and done.result_text == "a2"


# --- HTTP API -----------------------------------------------------------------


@pytest.fixture
def api_settings(db_settings: Settings) -> Settings:
    return db_settings.model_copy(update={"ollama_api_key": SecretStr("unused")})


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    with start(api_settings) as c:
        yield sign_in(c)


def test_chat_requires_auth_csrf_and_a_provider(api_settings: Settings) -> None:
    body = {"model": MODEL, "prompt": "hi"}
    with start(api_settings) as c:
        assert c.get("/api/v1/conversations").status_code == 401
        assert c.post("/api/v1/conversations", json=body).status_code == 401
        sign_in(c)
        del c.headers["X-CSRF-Token"]
        assert c.post("/api/v1/conversations", json=body).json()["error"]["code"] == "csrf_failed"
    with start(api_settings.model_copy(update={"ollama_api_key": None})) as c:
        sign_in(c)
        r = c.post("/api/v1/conversations", json=body)
        assert r.status_code == 503 and r.json()["error"]["code"] == "provider_not_configured"


def test_start_list_get_and_send(api: TestClient, db_url: str) -> None:
    r = api.post("/api/v1/conversations", json={"model": MODEL, "prompt": "Plan  my\nweek"})
    assert r.status_code == 201
    conv, [turn] = r.json()["conversation"], r.json()["turns"]
    assert conv["title"] == "Plan my week" and conv["model"] == MODEL
    assert turn["conversation_id"] == conv["id"] and turn["turn"] == 1
    assert turn["state"] == "queued" and "context" not in turn
    # The turn is an ordinary task: the Tasks API and its stream see it.
    assert api.get(f"/api/v1/tasks/{turn['id']}").json()["conversation_id"] == conv["id"]

    [summary] = api.get("/api/v1/conversations").json()
    assert summary["id"] == conv["id"] and summary["turns"] == 1
    detail = api.get(f"/api/v1/conversations/{conv['id']}").json()
    assert [t["id"] for t in detail["turns"]] == [turn["id"]]

    busy = api.post(f"/api/v1/conversations/{conv['id']}/turns", json={"prompt": "more"})
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "turn_in_progress"
    api.post(f"/api/v1/tasks/{turn['id']}/cancel")
    sent = api.post(
        f"/api/v1/conversations/{conv['id']}/turns", json={"prompt": "more", "model": "other"}
    )
    assert sent.status_code == 201 and sent.json()["turn"] == 2 and sent.json()["model"] == "other"
    assert api.get(f"/api/v1/conversations/{conv['id']}").json()["conversation"]["model"] == "other"

    with psycopg.connect(db_url) as conn:
        audit = conn.execute(
            "SELECT action, target FROM audit_log "
            "WHERE action LIKE 'task_%' OR action LIKE 'conversation_%' ORDER BY id"
        ).fetchall()
    assert audit == [
        ("conversation_created", conv["id"]),
        ("task_created", turn["id"]),
        ("task_canceled", turn["id"]),
        ("task_created", sent.json()["id"]),
    ]


def test_idempotent_start_and_send(api: TestClient) -> None:
    body = {"model": MODEL, "prompt": "hi"}
    h = {"Idempotency-Key": "chat-1"}
    first = api.post("/api/v1/conversations", json=body, headers=h)
    again = api.post("/api/v1/conversations", json=body, headers=h)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json() == first.json()
    clash = api.post("/api/v1/conversations", json={**body, "prompt": "bye"}, headers=h)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "idempotency_conflict"
    assert len(api.get("/api/v1/conversations").json()) == 1

    cid, tid = first.json()["conversation"]["id"], first.json()["turns"][0]["id"]
    # A key already spent on a turn cannot be reused as a lone task, or vice versa.
    task = api.post("/api/v1/tasks", json=body, headers=h)
    assert task.status_code == 409 and task.json()["error"]["code"] == "idempotency_conflict"
    replay = api.post(f"/api/v1/conversations/{cid}/turns", json={"prompt": "hi"}, headers=h)
    assert replay.status_code == 200 and replay.json()["id"] == tid  # not turn_in_progress

    lone = {"Idempotency-Key": "task-1"}
    assert api.post("/api/v1/tasks", json=body, headers=lone).status_code == 201
    reuse = api.post("/api/v1/conversations", json=body, headers=lone)
    assert reuse.status_code == 409 and reuse.json()["error"]["code"] == "idempotency_conflict"
    other = api.post("/api/v1/conversations", json=body).json()["conversation"]["id"]
    api.post(
        f"/api/v1/tasks/{api.get(f'/api/v1/conversations/{other}').json()['turns'][0]['id']}/cancel"
    )
    elsewhere = api.post(f"/api/v1/conversations/{other}/turns", json={"prompt": "hi"}, headers=h)
    assert elsewhere.status_code == 409  # chat-1 belongs to the first conversation


def test_unknown_conversation_and_validation(api: TestClient) -> None:
    missing = uuid.uuid4()
    assert api.get(f"/api/v1/conversations/{missing}").status_code == 404
    r = api.post(f"/api/v1/conversations/{missing}/turns", json={"prompt": "hi"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert api.post("/api/v1/conversations", json={"model": MODEL, "prompt": ""}).status_code == 422
    assert api.get("/api/v1/conversations?limit=0").status_code == 422


def test_a_turn_waiting_for_approval_blocks_the_next(api: TestClient, db_url: str) -> None:
    detail = api.post("/api/v1/conversations", json={"model": MODEL, "prompt": "build it"}).json()
    cid, tid = detail["conversation"]["id"], detail["turns"][0]["id"]
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "UPDATE tasks SET state = 'waiting', awaiting_approval = %s WHERE id = %s",
            ('{"id": "c", "name": "run_command", "arguments": {}}', tid),
        )
    r = api.post(f"/api/v1/conversations/{cid}/turns", json={"prompt": "next"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "turn_in_progress"
