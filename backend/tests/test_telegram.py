"""Telegram gateway (D-031) against a fake Bot API: notifications are sent once, only
recent ones, to the linked chat; other chats are told their id."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from seed_api.config import Settings
from seed_api.core.messages import ToolCall, Usage
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import TaskStore
from seed_api.gateways.telegram import (
    PART_CHARS,
    TelegramApi,
    TelegramError,
    TelegramGateway,
    message_for,
    parts,
    telegram_html,
)
from seed_api.notifications.store import Notification

pytestmark = pytest.mark.anyio
CHAT = 4242


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeBot:
    """Answers the Bot API like Telegram; `refuse` makes sendMessage fail with a status."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.modes: list[str | None] = []
        self.reject_html = False
        self.updates: list[dict[str, Any]] = []
        self.offsets: list[int | None] = []
        self.refuse: int | None = None
        self.paths: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path.endswith("/sendMessage"):
            if self.refuse:
                return httpx.Response(
                    self.refuse, json={"ok": False, "description": "Forbidden: bot was blocked"}
                )
            if self.reject_html and body.get("parse_mode"):
                return httpx.Response(
                    400, json={"ok": False, "description": "Bad Request: can't parse entities"}
                )
            self.modes.append(body.get("parse_mode"))
            self.sent.append((body["chat_id"], body["text"]))
            return httpx.Response(200, json={"ok": True, "result": {}})
        self.offsets.append(body.get("offset"))
        out, self.updates = self.updates, []
        return httpx.Response(200, json={"ok": True, "result": out})


def api(bot: FakeBot) -> TelegramApi:
    return TelegramApi("https://tg.test", "123:secret", transport=httpx.MockTransport(bot))


def note(**over: Any) -> Notification:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "kind": "task_failed",
        "title": "Backup",
        "body": "Disk is full.",
        "task_id": uuid.UUID(int=7),
        "schedule_id": None,
        "created_at": datetime.now(UTC),
        "read_at": None,
    }
    return Notification(**{**base, **over})


def test_the_message_names_what_happened_and_links_to_it() -> None:
    n = note()
    assert message_for(n, "https://seed.example/") == (
        f"❌ Failed: Backup\nDisk is full.\nhttps://seed.example/tasks/{n.task_id}"
    )
    assert message_for(note(kind="task_completed", body=""), None) == "✅ Finished: Backup"
    skipped = note(kind="schedule_skipped", title="Hourly", schedule_id=uuid.uuid4())
    assert message_for(skipped, "https://s").endswith("\nhttps://s/schedules")


async def test_the_bot_api_is_called_with_the_token_and_its_errors_are_typed() -> None:
    bot = FakeBot()
    client = api(bot)
    await client.send_message(CHAT, "hi")
    assert bot.paths == ["/bot123:secret/sendMessage"] and bot.sent == [(CHAT, "hi")]
    bot.refuse = 403
    with pytest.raises(TelegramError) as lasting:
        await client.send_message(CHAT, "hi")
    assert lasting.value.lasting and "blocked" in str(lasting.value)
    bot.refuse = 429
    with pytest.raises(TelegramError) as passing:
        await client.send_message(CHAT, "hi")
    assert not passing.value.lasting

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    offline = TelegramApi("https://tg.test", "123:secret", transport=httpx.MockTransport(down))
    with pytest.raises(TelegramError) as unreachable:
        await offline.get_updates(None)
    assert not unreachable.value.lasting and "secret" not in str(unreachable.value)
    await client.aclose()
    await offline.aclose()


# --- Sending notifications (database) ---------------------------------------------


@pytest.fixture
async def pool(db_url: str) -> AsyncIterator[Pool]:
    pool = make_pool(db_url, max_size=4)
    await pool.open(wait=True)
    await migrate(pool)
    yield pool
    await pool.close()


async def add(pool: Pool, title: str, *, owner: str = "admin", minutes_ago: int = 0) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO notifications (owner, kind, title, body, created_at) "
            "VALUES (%s, 'task_completed', %s, 'ok', now() - make_interval(mins => %s))",
            (owner, title, minutes_ago),
        )


async def test_recent_notifications_are_sent_once_in_order(pool: Pool) -> None:
    bot = FakeBot()
    gw = TelegramGateway(pool, api(bot), Settings(telegram_chat_id=CHAT, public_url=None))
    await add(pool, "old", minutes_ago=61)  # from before the gateway ran: not sent
    await add(pool, "first", minutes_ago=2)
    await add(pool, "second", minutes_ago=1)
    await add(pool, "theirs", owner="other")
    assert await gw.send_pending() == 2
    assert [text for _, text in bot.sent] == ["✅ Finished: first\nok", "✅ Finished: second\nok"]
    assert {chat for chat, _ in bot.sent} == {CHAT}
    assert await gw.send_pending() == 0 and len(bot.sent) == 2
    # Another SEED user's notifications go to that user's chat when it is set.
    other = TelegramGateway(pool, api(bot), Settings(telegram_chat_id=7, telegram_user="other"))
    assert await other.send_pending() == 1 and bot.sent[-1][0] == 7


async def test_nothing_is_sent_without_a_linked_chat(pool: Pool) -> None:
    bot = FakeBot()
    await add(pool, "first")
    assert await TelegramGateway(pool, api(bot), Settings()).send_pending() == 0
    assert bot.sent == []


async def test_a_passing_refusal_keeps_the_notification_and_a_lasting_one_does_not(
    pool: Pool,
) -> None:
    bot = FakeBot()
    gw = TelegramGateway(pool, api(bot), Settings(telegram_chat_id=CHAT))
    await add(pool, "first")
    bot.refuse = 429
    assert await gw.send_pending() == 0
    bot.refuse = None
    assert await gw.send_pending() == 1  # sent on the next pass
    await add(pool, "second")
    bot.refuse = 403
    assert await gw.send_pending() == 0
    bot.refuse = None
    assert await gw.send_pending() == 0  # given up on, not retried for ever
    assert [t for _, t in bot.sent] == ["✅ Finished: first\nok"]


async def test_the_gateway_stops_at_once_on_a_signal(pool: Pool) -> None:
    async def slow_poll(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)
        return httpx.Response(200, json={"ok": True, "result": []})

    client = TelegramApi("https://tg.test", "t", transport=httpx.MockTransport(slow_poll))
    gw = TelegramGateway(pool, client, Settings(telegram_chat_id=CHAT))
    run = asyncio.create_task(gw.run_forever())
    await asyncio.sleep(0.1)
    gw.stop.set()
    await asyncio.wait_for(run, timeout=2)
    await client.aclose()


# --- Chatting from Telegram (D-032) ------------------------------------------------

CHATTING = {
    "telegram_chat_id": CHAT,
    "ollama_api_key": "k",
    "default_model": "m-default",
    "public_url": "https://seed.example",
}


def text(update_id: int, body: str, chat: int = CHAT) -> dict[str, Any]:
    return {"update_id": update_id, "message": {"chat": {"id": chat}, "text": body}}


async def turns(pool: Pool) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, conversation_id, turn, prompt, model, created_by, idempotency_key, state "
            "FROM tasks ORDER BY created_at"
        )
        return list(await cur.fetchall())


async def end(pool: Pool, state: str, *, answer: str = "", error: str = "") -> None:
    store = TaskStore(pool)
    claimed = await store.claim("w", 30)
    assert claimed is not None
    await store.finish(
        claimed[1],
        state=state,  # type: ignore[arg-type]
        termination="done",
        error=error or None,
        result_text=answer,
        usage=Usage(),
    )


def test_long_answers_are_split_at_line_breaks() -> None:
    assert parts("") == [] and parts("short") == ["short"]
    para = "x" * (PART_CHARS - 100)
    assert parts(f"{para}\n\n{para}") == [para, para]
    unbroken = "y" * (PART_CHARS * 2 + 5)
    assert [len(p) for p in parts(unbroken)] == [PART_CHARS, PART_CHARS, 5]


async def test_other_chats_learn_their_id_and_nothing_else(pool: Pool) -> None:
    bot = FakeBot()
    gw = TelegramGateway(pool, api(bot), Settings(**CHATTING))  # type: ignore[arg-type]
    bot.updates = [text(10, "do something", chat=99), {"update_id": 11, "edited_message": {}}]
    assert await gw.receive_once() == 2
    assert bot.sent == [
        (
            99,
            "This chat is not linked to SEED. Its id is 99: set SEED_TELEGRAM_CHAT_ID=99 "
            "on the server to link it.",
        )
    ]
    assert await turns(pool) == []


async def test_a_message_is_a_chat_turn_and_its_answer_comes_back(pool: Pool) -> None:
    bot = FakeBot()
    gw = TelegramGateway(pool, api(bot), Settings(**CHATTING))  # type: ignore[arg-type]
    bot.updates = [text(20, "What is 2+2?")]
    await gw.receive_once()
    [first] = await turns(pool)
    assert (first["prompt"], first["model"], first["created_by"], first["turn"]) == (
        "What is 2+2?",
        "m-default",
        "admin",
        1,
    )
    assert first["idempotency_key"] == "telegram:20"
    assert bot.sent[-1] == (CHAT, "Working on it…")

    bot.updates = [text(21, "And 3+3?")]  # the first is still being answered
    await gw.receive_once()
    assert bot.sent[-1][1].startswith("SEED is still answering")
    assert len(await turns(pool)) == 1

    assert await gw.deliver_answers() == 0  # not ended yet
    await end(pool, "completed", answer="4")
    assert await gw.deliver_answers() == 1
    assert bot.sent[-1] == (CHAT, "4") and bot.modes[-1] == "HTML"
    assert await gw.deliver_answers() == 0  # sent once

    bot.updates = [text(22, "And 3+3?")]
    await gw.receive_once()
    second = (await turns(pool))[-1]
    assert (second["conversation_id"], second["turn"]) == (first["conversation_id"], 2)


async def test_a_message_read_twice_is_answered_once(pool: Pool) -> None:
    bot = FakeBot()
    gw = TelegramGateway(pool, api(bot), Settings(**CHATTING))  # type: ignore[arg-type]
    bot.updates = [text(30, "Hello")]
    await gw.receive_once()
    await end(pool, "completed", answer="Hi")
    await gw.deliver_answers()
    again = TelegramGateway(pool, api(bot), Settings(**CHATTING))  # type: ignore[arg-type]
    await again.receive_once()
    assert bot.offsets[-1] == 31  # the next gateway reads on from where this one stopped
    bot.updates = [text(30, "Hello")]  # Telegram sends it again all the same
    await again.receive_once()
    assert len(await turns(pool)) == 1


async def test_new_starts_another_conversation_and_help_explains(pool: Pool) -> None:
    bot = FakeBot()
    gw = TelegramGateway(pool, api(bot), Settings(**CHATTING))  # type: ignore[arg-type]
    bot.updates = [text(40, "/start")]
    await gw.receive_once()
    assert "/new starts another" in bot.sent[-1][1]
    bot.updates = [text(41, "First")]
    await gw.receive_once()
    await end(pool, "completed", answer="ok")
    bot.updates = [text(42, "/new@SeedBot"), text(43, "Second")]
    await gw.receive_once()
    assert bot.sent[-2][1] == "Your next message starts a new conversation."
    first, second = await turns(pool)
    assert first["conversation_id"] != second["conversation_id"] and second["turn"] == 1
    # The answer to the first was still owed when /new came: it is not lost.
    assert await gw.deliver_answers() == 0  # the second is now the one owed


async def test_a_conversation_deleted_in_the_app_is_started_afresh(pool: Pool) -> None:
    bot = FakeBot()
    gw = TelegramGateway(pool, api(bot), Settings(**CHATTING))  # type: ignore[arg-type]
    bot.updates = [text(50, "First")]
    await gw.receive_once()
    await end(pool, "completed", answer="ok")
    [first] = await turns(pool)
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM tasks WHERE id = %s", (first["id"],))
        await conn.execute("DELETE FROM conversations WHERE id = %s", (first["conversation_id"],))
    bot.updates = [text(51, "Again")]
    await gw.receive_once()
    [again] = await turns(pool)
    assert again["turn"] == 1 and bot.sent[-1][1] == "Working on it…"


async def test_waiting_for_an_approval_is_told_once_and_a_failure_is_reported(
    pool: Pool,
) -> None:
    bot = FakeBot()
    gw = TelegramGateway(pool, api(bot), Settings(**CHATTING))  # type: ignore[arg-type]
    bot.updates = [text(60, "Run ls")]
    await gw.receive_once()
    [turn] = await turns(pool)
    store = TaskStore(pool)
    claimed = await store.claim("w", 30)
    assert claimed is not None
    await store.pause(claimed[1], ToolCall(id="c1", name="run_command", arguments={}))
    assert await gw.deliver_answers() == 0
    link = f"https://seed.example/chat/{turn['conversation_id']}"
    assert bot.sent[-1] == (
        CHAT,
        f"✋ Waiting for your approval to call run_command. Approve or deny it in SEED.\n{link}",
    )
    await gw.deliver_answers()
    assert sum("Waiting for your approval" in t for _, t in bot.sent) == 1
    await store.decide(turn["id"], call_id="c1", approved=True, by="admin")
    await end(pool, "failed", error="The model gave up.")
    assert await gw.deliver_answers() == 1
    assert bot.sent[-1] == (CHAT, f"❌ That failed: The model gave up.\n{link}")


async def test_it_says_why_it_cannot_answer(pool: Pool) -> None:
    bot = FakeBot()
    gw = TelegramGateway(pool, api(bot), Settings(telegram_chat_id=CHAT, default_model="m"))
    bot.updates = [text(70, "Hi"), {"update_id": 71, "message": {"chat": {"id": CHAT}}}]
    await gw.receive_once()
    assert [t for _, t in bot.sent] == [
        "SEED has no model provider configured, so it cannot answer.",
        "SEED reads text messages only.",
    ]
    no_model = TelegramGateway(pool, api(bot), Settings(telegram_chat_id=CHAT, ollama_api_key="k"))
    bot.updates = [text(72, "Hi")]
    await no_model.receive_once()
    assert bot.sent[-1][1] == "No model is chosen: set SEED_DEFAULT_MODEL on the server."
    assert await turns(pool) == []


async def test_a_long_answer_arrives_in_parts_and_an_empty_one_links_to_it(pool: Pool) -> None:
    bot = FakeBot()
    gw = TelegramGateway(pool, api(bot), Settings(**CHATTING))  # type: ignore[arg-type]
    bot.updates = [text(80, "Write a lot")]
    await gw.receive_once()
    await end(pool, "completed", answer="z" * (PART_CHARS + 10))
    await gw.deliver_answers()
    assert [len(t) for _, t in bot.sent[1:]] == [PART_CHARS, 10]
    bot.updates = [text(81, "Make a page")]
    await gw.receive_once()
    await end(pool, "completed", answer="  ")
    await gw.deliver_answers()
    [turn, _] = await turns(pool)
    assert bot.sent[-1][1] == (
        "Done. The answer has no text to show here.\n"
        f"https://seed.example/chat/{turn['conversation_id']}"
    )


def test_markdown_becomes_telegram_html() -> None:
    md = (
        "# Plan\n- **Write** files & *notes*\n  - run `a<b` now\n"
        "See [docs](https://x.test/a?b=1&c=2) and snake_case_name.\n"
        "```py\nif a < b:\n    **not bold**\n```\nend"
    )
    assert telegram_html(md) == (
        "<b>Plan</b>\n"
        "\u2022 <b>Write</b> files &amp; <i>notes</i>\n"
        "  \u2022 run <code>a&lt;b</code> now\n"
        'See <a href="https://x.test/a?b=1&amp;c=2">docs</a> and snake_case_name.\n'
        "<pre>if a &lt; b:\n    **not bold**</pre>\n"
        "end"
    )
    assert telegram_html("2 * 3 * 4 and <script>") == "2 * 3 * 4 and &lt;script&gt;"
    assert telegram_html("```\nunclosed <b>") == "<pre>unclosed &lt;b&gt;</pre>"


async def test_answer_falls_back_to_plain_text_when_telegram_refuses_html() -> None:
    bot = FakeBot()
    bot.reject_html = True
    client = api(bot)
    await client.send_message(CHAT, "**hi** <there>", markdown=True)
    assert bot.sent == [(CHAT, "**hi** <there>")] and bot.modes == [None]
    bot.refuse = 403  # other refusals are not retried as plain text
    with pytest.raises(TelegramError):
        await client.send_message(CHAT, "**hi**", markdown=True)
    assert len(bot.sent) == 1
    await client.aclose()
