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
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.gateways.telegram import TelegramApi, TelegramError, TelegramGateway, message_for
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


async def test_other_chats_learn_their_id_and_the_linked_chat_is_acknowledged() -> None:
    bot = FakeBot()
    gw = TelegramGateway(None, api(bot), Settings(telegram_chat_id=CHAT))  # type: ignore[arg-type]
    bot.updates = [
        {"update_id": 10, "message": {"chat": {"id": 99}, "text": "/start"}},
        {"update_id": 11, "message": {"chat": {"id": CHAT}, "text": "hello"}},
        {"update_id": 12, "edited_message": {"chat": {"id": CHAT}}},  # ignored
    ]
    assert await gw.receive_once() == 3
    assert bot.sent == [
        (
            99,
            "This chat is not linked to SEED. Its id is 99: set SEED_TELEGRAM_CHAT_ID=99 "
            "on the server to link it.",
        ),
        (CHAT, "This chat is linked to SEED. Notifications for admin arrive here."),
    ]
    await gw.receive_once()
    assert bot.offsets == [None, 13]  # confirmed: the same updates do not come again


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
