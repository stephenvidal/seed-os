"""Recall across chats (D-039): session_search finds the owner's earlier chat turns."""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from seed_api.chat.recall import RecallStore
from seed_api.chat.store import ChatStore
from seed_api.config import Settings
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import TaskStore
from seed_api.flow.worker import Worker

from .fakes import ScriptedProvider, Step, calls, reply

pytestmark = pytest.mark.anyio


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


async def chat(
    pool: Pool, tmp_path: Path, owner: str, prompt: str, *script: Step
) -> tuple[uuid.UUID, ScriptedProvider]:
    """Start a conversation and run its first turn with scripted replies."""
    conv, _, _ = await ChatStore(pool).start(
        owner=owner, model="fake", prompt=prompt, max_attempts=3, idempotency_key=None
    )
    provider = ScriptedProvider(list(script))
    worker = Worker(TaskStore(pool), Settings(workspace_root=str(tmp_path)), lambda: provider)
    assert await worker.run_once()
    return conv.id, provider


async def test_search_finds_the_owners_other_chats_only(pool: Pool, tmp_path: Path) -> None:
    garden, _ = await chat(
        pool, tmp_path, "admin", "Which tomatoes suit a shady balcony?", reply("Try Sungold.")
    )
    await chat(pool, tmp_path, "other", "Tomatoes for my roof?", reply("Cherry tomatoes."))
    here, _ = await chat(pool, tmp_path, "admin", "More tomatoes please", reply("Sure."))
    store = RecallStore(pool)

    found = await store.search("admin", "tomatoes", exclude=here)
    assert [(f.conversation_id, f.answered) for f in found] == [(garden, "Try Sungold.")]
    assert found[0].asked == "Which tomatoes suit a shady balcony?"
    # Stemming: "tomato" finds "tomatoes"; without an exclusion this chat is found too.
    assert len(await store.search("admin", "tomato")) == 2
    assert await store.search("admin", "zucchini") == []


async def test_failed_turns_are_not_recalled(pool: Pool, tmp_path: Path) -> None:
    from seed_api.core.providers.base import ProviderError

    err = ProviderError("fake", "bad_request", "no", 400)
    await chat(pool, tmp_path, "admin", "What about artichokes?", err)  # type: ignore[arg-type]
    assert await RecallStore(pool).search("admin", "artichokes") == []


async def test_a_chat_turn_can_search_earlier_chats(pool: Pool, tmp_path: Path) -> None:
    await chat(pool, tmp_path, "admin", "Remember my bike is a Brompton", reply("Noted."))
    script = [calls(("session_search", {"query": "bike"})), reply("Your Brompton.")]
    _, provider = await chat(pool, tmp_path, "admin", "Which bike do I have?", *script)
    tool_message = provider.requests[1].messages[-1]
    assert tool_message.role == "tool"
    [hit] = json.loads(tool_message.content or "")["results"]
    assert hit["asked"] == "Remember my bike is a Brompton" and hit["answered"] == "Noted."


def test_the_tool_says_to_stop_at_a_good_hit() -> None:
    """The live check (2026-10-31) saw a found answer followed by run_command for the
    same fact, which waited for approval. The description now says not to."""
    from seed_api.chat.recall import DESCRIPTION

    assert "answer from it: do not also search files or run commands" in DESCRIPTION
