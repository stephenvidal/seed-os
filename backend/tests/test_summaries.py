"""Session summaries (D-022): completed turns that no longer fit a chat turn's
context reach the model as a rolling summary instead of being dropped."""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api.chat import summary as summary_mod
from seed_api.chat.store import ChatStore, left_out
from seed_api.chat.summary import summary_through
from seed_api.config import Settings
from seed_api.core.providers.base import ProviderError
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import Task, TaskStore
from seed_api.flow.worker import Worker

from .conftest import sign_in, start
from .fakes import ScriptedProvider, Step, reply

WINDOW = 2


def test_left_out_is_the_newest_completed_turn_before_the_window() -> None:
    rows = [
        {"id": 1, "state": "completed"},
        {"id": 2, "state": "failed"},
        {"id": 3, "state": "completed"},
        {"id": 4, "state": "completed"},
    ]
    assert left_out(rows, 3) is None  # three completed turns fit
    assert left_out(rows, 2) == 1  # failed turns neither count nor get summarized
    assert left_out(rows, 1) == 3


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


class Chat:
    """A conversation driven through the store and a worker with scripted replies."""

    def __init__(self, pool: Pool, tmp_path: Path) -> None:
        self.pool, self.store, self.tasks = pool, ChatStore(pool), TaskStore(pool)
        self.settings = Settings(workspace_root=str(tmp_path), worker_lease_seconds=3)
        self.cid: uuid.UUID | None = None
        self.provider = ScriptedProvider([])

    async def run(self, *script: Step) -> Task:
        self.provider = ScriptedProvider(list(script))
        provider = self.provider
        worker = Worker(self.tasks, self.settings, lambda: provider, worker_id="w")
        assert await worker.run_once()
        assert provider.script == []  # every scripted step was used
        turns = await self.store.turns(self.cid) if self.cid else []
        return turns[-1].task

    async def say(self, prompt: str, *script: Step) -> Task:
        if self.cid is None:
            conv, _, _ = await self.store.start(
                owner="admin", model="fake", prompt=prompt, max_attempts=3, idempotency_key=None
            )
            self.cid = conv.id
        else:
            await self.store.send(
                self.cid,
                owner="admin",
                prompt=prompt,
                model=None,
                max_attempts=3,
                idempotency_key=None,
                context_turns=WINDOW,
            )
        return await self.run(*script)

    async def events(self, task: Task) -> dict[str, dict[str, object]]:
        return {e.type: e.data for e in await self.tasks.events(task.id, after=0, limit=1000)}


def system_of(provider: ScriptedProvider, i: int = -1) -> str:
    return provider.requests[i].messages[0].content


@pytest.mark.anyio
async def test_turns_past_the_window_reach_the_model_as_a_rolling_summary(
    pool: Pool, tmp_path: Path
) -> None:
    chat = Chat(pool, tmp_path)
    one = await chat.say("My cat is called Miso.", reply("Nice name."))
    two = await chat.say("I live in Lyon.", reply("Noted."))
    three = await chat.say("I like tea.", reply("Good."))
    assert three.summary_of is None  # two earlier turns fit the window of two
    assert "summary" not in system_of(chat.provider)

    four = await chat.say("What is my cat called?", reply("S1: cat Miso."), reply("Miso."))
    assert four.summary_of == one.id
    made = chat.provider.requests[0]  # the summary call, before the run
    assert made.tools == [] and "Miso" in made.messages[1].content
    assert "There is no summary yet." in made.messages[1].content
    run = chat.provider.requests[1]
    assert "A summary of them:\nS1: cat Miso." in system_of(chat.provider)
    assert [m.content for m in run.messages[1:-1]] == [
        "I live in Lyon.",
        "Noted.",
        "I like tea.",
        "Good.",
    ]
    events = await chat.events(four)
    assert events["context_summarized"]["turns"] == 1
    assert events["context_summarized"]["through"] == str(one.id)
    assert four.usage.input_tokens == 20  # the summary's tokens count toward the turn
    [first] = [t.task for t in await chat.store.turns(chat.cid) if t.task.id == one.id]
    assert first.summary == "S1: cat Miso."

    # The next turn rolls the summary forward with only the turn that just left.
    await chat.say("And where do I live?", reply("S2: cat Miso, Lyon."), reply("Lyon."))
    roll = chat.provider.requests[0].messages[1].content
    assert roll.startswith("Summary so far:\nS1: cat Miso.") and "I live in Lyon." in roll
    assert "My cat is called Miso." not in roll
    assert "S2: cat Miso, Lyon." in system_of(chat.provider)

    # A new version of that message has the same earlier turns: the stored summary
    # is reused without a model call.
    [*_, fifth] = await chat.store.turns(chat.cid)
    await chat.store.add_version(
        chat.cid,
        fifth.task.id,
        owner="admin",
        prompt=None,
        model=None,
        max_attempts=3,
        idempotency_key=None,
        context_turns=WINDOW,
    )
    again = await chat.run(reply("Lyon, still."))
    assert again.summary_of == two.id and len(chat.provider.requests) == 1
    assert "S2: cat Miso, Lyon." in system_of(chat.provider)
    assert (await chat.events(again))["context_summarized"]["turns"] == 0


@pytest.mark.anyio
async def test_a_failed_summary_is_recorded_and_the_turn_still_runs(
    pool: Pool, tmp_path: Path
) -> None:
    chat = Chat(pool, tmp_path)
    for p in ("a", "b", "c"):
        await chat.say(p, reply("ok"))
    down = ProviderError("fake", "unavailable", "provider down")
    turn = await chat.say("d", down, reply("answered anyway"))
    assert turn.state == "completed" and turn.result_text == "answered anyway"
    assert "summary" not in system_of(chat.provider)
    failed = (await chat.events(turn))["summary_failed"]
    assert failed["error"] == "fake: unavailable: provider down"

    turn = await chat.say("e", reply("   "), reply("ok"))  # an empty summary fails too
    assert "empty summary" in str((await chat.events(turn))["summary_failed"]["error"])


@pytest.mark.anyio
async def test_a_backlog_is_summarized_in_batches(
    pool: Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat = Chat(pool, tmp_path)
    turns = [await chat.say(p, reply(f"answer {p}")) for p in ("a", "b", "c")]
    monkeypatch.setattr(summary_mod, "BATCH_TURNS", 2)
    provider = ScriptedProvider([reply("S-ab"), reply("S-abc " + "x" * 5000)])
    made = await summary_through(pool, provider, "fake", turns[2].id)
    assert made is not None and made.turns == 3 and made.usage.output_tokens == 20
    assert len(made.text) <= summary_mod.SUMMARY_CHARS and made.text.endswith(" …")
    first, second = (r.messages[1].content for r in provider.requests)
    assert "Person: a" in first and "Person: b" in first and "Person: c" not in first
    assert second.startswith("Summary so far:\nS-ab") and "Person: c" in second
    stored = {t.task.id: t.task.summary for t in await chat.store.turns(chat.cid)}
    assert stored == {turns[0].id: None, turns[1].id: "S-ab", turns[2].id: made.text}

    assert await summary_through(pool, provider, "fake", uuid.uuid4()) is None
    queued, _ = await chat.store.send(
        chat.cid,
        owner="admin",
        prompt="d",
        model=None,
        max_attempts=3,
        idempotency_key=None,
        context_turns=WINDOW,
    )
    assert await summary_through(pool, provider, "fake", queued.id) is None  # no answer yet


def test_turns_show_their_summary(db_settings: Settings, db_url: str) -> None:
    settings = db_settings.model_copy(
        update={"ollama_api_key": SecretStr("unused"), "chat_context_turns": 1}
    )
    with start(settings) as c:
        api: TestClient = sign_in(c)
        conv = api.post("/api/v1/conversations", json={"prompt": "hi", "model": "fake"}).json()
        first = conv["turns"][0]
        assert (first["summary_of"], first["summary"]) == (None, None)
        with psycopg.connect(db_url) as db:
            db.execute(
                "UPDATE tasks SET summary = 'S', summary_of = id WHERE id = %s", (first["id"],)
            )
        cid = conv["conversation"]["id"]
        [shown] = api.get(f"/api/v1/conversations/{cid}").json()["turns"]
        assert (shown["summary_of"], shown["summary"]) == (first["id"], "S")
