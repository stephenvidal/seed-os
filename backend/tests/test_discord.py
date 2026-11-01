"""Discord gateway (D-044) against a fake Discord: the Gateway connection, direct
messages as chat turns, answers, notifications and approval buttons."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from seed_api.config import Settings
from seed_api.core.messages import ToolCall, Usage
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import TaskStore
from seed_api.gateways.discord import (
    INTENTS,
    PART_CHARS,
    DiscordApi,
    DiscordError,
    DiscordFatal,
    DiscordGateway,
    parts,
)

pytestmark = pytest.mark.anyio
ME = "111111111111"
DM = "900"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeDiscord:
    """Answers Discord's REST API; `refuse` makes sending fail with that status."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.components: list[Any] = []
        self.responses: list[tuple[int, dict[str, Any]]] = []
        self.opened: list[str] = []
        self.headers: list[httpx.Headers] = []
        self.refuse: int | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.headers.append(request.headers)
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path.endswith("/gateway/bot"):
            return httpx.Response(200, json={"url": "wss://gw.test"})
        if path.endswith("/users/@me/channels"):
            self.opened.append(body["recipient_id"])
            return httpx.Response(200, json={"id": DM})
        if "/interactions/" in path:
            self.responses.append((body["type"], body["data"]))
            return httpx.Response(204)
        if self.refuse:
            return httpx.Response(
                self.refuse, json={"message": "Cannot send messages to this user"}
            )
        channel = path.split("/channels/")[1].split("/")[0]
        self.sent.append((channel, body["content"]))
        self.components.append(body.get("components"))
        assert body["allowed_mentions"] == {"parse": []}  # never pings anyone
        return httpx.Response(200, json={"id": "m1"})


def api(fake: FakeDiscord) -> DiscordApi:
    return DiscordApi("https://discord.test/api/v10", "tok", transport=httpx.MockTransport(fake))


def test_long_answers_are_split_under_discords_limit() -> None:
    assert parts("") == [] and parts("short") == ["short"]
    para = "x" * (PART_CHARS - 100)
    assert parts(f"{para}\n\n{para}") == [para, para]
    assert [len(p) for p in parts("y" * (PART_CHARS * 2 + 5))] == [PART_CHARS, PART_CHARS, 5]


async def test_rest_calls_carry_the_bot_token_and_errors_are_typed() -> None:
    fake = FakeDiscord()
    client = api(fake)
    await client.send(DM, "hi")
    assert fake.sent == [(DM, "hi")] and fake.headers[0]["authorization"] == "Bot tok"
    fake.refuse = 403
    with pytest.raises(DiscordError) as lasting:
        await client.send(DM, "hi")
    assert lasting.value.lasting and "Cannot send" in str(lasting.value)
    fake.refuse = 429
    with pytest.raises(DiscordError) as passing:
        await client.send(DM, "hi")
    assert not passing.value.lasting

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    offline = DiscordApi("https://d.test", "tok", transport=httpx.MockTransport(down))
    with pytest.raises(DiscordError) as unreachable:
        await offline.gateway_url()
    assert not unreachable.value.lasting and "tok" not in str(unreachable.value)
    await client.aclose()
    await offline.aclose()


# --- The Gateway connection (no database) -----------------------------------------


class FakeSocket:
    """Plays a script of Gateway messages; then ends cleanly, or closes with `close`."""

    def __init__(self, script: list[dict[str, Any]], close: int | None = None) -> None:
        self.script = [json.dumps(m) for m in script]
        self.close_code = close
        self.sent: list[dict[str, Any]] = []
        self.closed: int | None = None

    async def recv(self) -> str:
        return self.script.pop(0)

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def close(self, code: int = 1000) -> None:
        self.closed = code

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[str]:
        while self.script:
            yield self.script.pop(0)
            await asyncio.sleep(0)
        if self.close_code is not None:
            raise ConnectionClosedError(Close(self.close_code, "bye"), None)


HELLO = {"op": 10, "d": {"heartbeat_interval": 45_000}}


def gateway(sockets: list[FakeSocket], urls: list[str], **over: Any) -> DiscordGateway:
    @asynccontextmanager
    async def connector(url: str) -> AsyncIterator[FakeSocket]:
        urls.append(url)
        yield sockets.pop(0)

    settings = Settings(discord_bot_token="tok", discord_user_id=ME, **over)  # type: ignore[arg-type]
    return DiscordGateway(None, api(FakeDiscord()), settings, connector=connector)  # type: ignore[arg-type]


async def test_it_identifies_for_direct_messages_and_resumes_after_a_reconnect() -> None:
    seen: list[tuple[str | None, Any]] = []
    first = FakeSocket(
        [
            HELLO,
            {
                "op": 0,
                "s": 1,
                "t": "READY",
                "d": {"session_id": "s1", "resume_gateway_url": "wss://r.test"},
            },
            {"op": 0, "s": 2, "t": "MESSAGE_CREATE", "d": {"id": "5"}},
            {"op": 7, "d": None},
        ]
    )
    second = FakeSocket([HELLO, {"op": 0, "s": 3, "t": "RESUMED", "d": {}}])
    urls: list[str] = []
    gw = gateway([first, second], urls)

    async def record(event: str | None, d: Any) -> None:
        seen.append((event, d))

    real = gw.dispatch

    async def dispatch(event: str | None, d: Any) -> None:
        await real(event, d)
        await record(event, d)

    gw.dispatch = dispatch  # type: ignore[method-assign]
    await gw.connect_once()
    assert urls == ["wss://gw.test/?v=10&encoding=json"]
    identify = first.sent[0]
    assert identify["op"] == 2 and identify["d"]["token"] == "tok"
    assert identify["d"]["intents"] == INTENTS == 4096
    assert [e for e, _ in seen] == ["READY", "MESSAGE_CREATE"] and first.closed == 4000

    await gw.connect_once()  # Discord asked for a reconnect: resume where it stopped
    assert urls[-1] == "wss://r.test/?v=10&encoding=json"
    assert second.sent[0] == {"op": 6, "d": {"token": "tok", "session_id": "s1", "seq": 2}}
    assert gw.seq == 3


async def test_a_bad_token_stops_it_and_a_dead_session_starts_afresh() -> None:
    urls: list[str] = []
    gw = gateway([FakeSocket([HELLO], close=4004)], urls)
    with pytest.raises(DiscordFatal, match="4004"):
        await gw.connect_once()

    gw = gateway([FakeSocket([HELLO], close=1006)], urls)
    await gw.connect_once()  # a dropped connection is not fatal; the loop retries

    gw = gateway([FakeSocket([HELLO, {"op": 9, "d": False}])], urls)
    gw.session_id, gw.resume_url, gw.seq = "s1", "wss://r.test", 4
    await gw.connect_once()
    assert (gw.session_id, gw.resume_url, gw.seq) == (None, None, None)


async def test_the_receive_loop_gives_up_on_a_fatal_close() -> None:
    gw = gateway([FakeSocket([HELLO], close=4014)], [])
    await asyncio.wait_for(gw._receive_forever(), timeout=2)
    assert gw.stop.is_set()


# --- Messages, answers, notifications, approvals (database) ------------------------


@pytest.fixture
async def pool(db_url: str) -> AsyncIterator[Pool]:
    pool = make_pool(db_url, max_size=4)
    await pool.open(wait=True)
    await migrate(pool)
    yield pool
    await pool.close()


CHATTING = {
    "discord_user_id": ME,
    "ollama_api_key": "k",
    "default_model": "m-default",
    "public_url": "https://seed.example",
}


def dm(message_id: str, content: str, author: str = ME, **over: Any) -> dict[str, Any]:
    return {
        "id": message_id,
        "channel_id": DM,
        "author": {"id": author},
        "content": content,
        **over,
    }


async def turns(pool: Pool) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, conversation_id, turn, prompt, created_by, idempotency_key, state, "
            "approvals FROM tasks ORDER BY created_at"
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


async def test_strangers_learn_their_id_and_bots_and_servers_are_ignored(pool: Pool) -> None:
    fake = FakeDiscord()
    gw = DiscordGateway(pool, api(fake), Settings(**CHATTING))  # type: ignore[arg-type]
    await gw.on_message(dm("1", "hello", author="222222"))
    await gw.on_message(
        dm("2", "hello", author="333333", bot=True) | {"author": {"id": "3", "bot": True}}
    )
    await gw.on_message(dm("3", "hello", guild_id="77"))
    assert fake.sent == [
        (
            DM,
            "This Discord account is not linked to SEED. Its id is 222222: set "
            "SEED_DISCORD_USER_ID=222222 on the server to link it.",
        )
    ]
    assert await turns(pool) == []


async def test_a_direct_message_is_a_chat_turn_and_its_answer_comes_back(pool: Pool) -> None:
    fake = FakeDiscord()
    gw = DiscordGateway(pool, api(fake), Settings(**CHATTING))  # type: ignore[arg-type]
    await gw.on_message(dm("10", "What is 2+2?"))
    [first] = await turns(pool)
    assert (first["prompt"], first["created_by"], first["idempotency_key"]) == (
        "What is 2+2?",
        "admin",
        "discord:10",
    )
    assert fake.sent[-1] == (DM, "Working on it…")
    await gw.on_message(dm("10", "What is 2+2?"))  # replayed on a resume: one turn
    assert len(await turns(pool)) == 1

    assert await gw.deliver_answers() == 0
    await end(pool, "completed", answer="**4**")
    assert await gw.deliver_answers() == 1
    assert fake.sent[-1] == (DM, "**4**")  # Discord shows the Markdown itself
    assert await gw.deliver_answers() == 0

    await gw.on_message(dm("11", "And 3+3?"))
    second = (await turns(pool))[-1]
    assert (second["conversation_id"], second["turn"]) == (first["conversation_id"], 2)
    await end(pool, "completed", answer="6")
    await gw.on_message(dm("12", "/new"))
    assert fake.sent[-1][1] == "Your next message starts a new conversation."
    await gw.on_message(dm("13", "Third"))
    third = (await turns(pool))[-1]
    assert third["conversation_id"] != first["conversation_id"] and third["turn"] == 1
    await gw.on_message(dm("14", "/help"))
    assert "/new starts another" in fake.sent[-1][1]


async def test_recent_notifications_are_sent_once_to_the_direct_messages(pool: Pool) -> None:
    fake = FakeDiscord()
    gw = DiscordGateway(pool, api(fake), Settings(discord_user_id=ME))
    async with pool.connection() as conn:
        for title, mins in (("old", 61), ("first", 2), ("second", 1)):
            await conn.execute(
                "INSERT INTO notifications (owner, kind, title, body, created_at) "
                "VALUES ('admin', 'task_completed', %s, 'ok', now() - make_interval(mins => %s))",
                (title, mins),
            )
    assert await gw.send_pending() == 2
    assert fake.sent == [(DM, "✅ Finished: first\nok"), (DM, "✅ Finished: second\nok")]
    assert await gw.send_pending() == 0 and fake.opened == [ME]  # the DM is opened once
    assert await DiscordGateway(pool, api(fake), Settings()).send_pending() == 0  # unlinked


async def waiting(pool: Pool, gw: DiscordGateway, fake: FakeDiscord) -> dict[str, str]:
    await gw.on_message(dm("20", "Run ls"))
    store = TaskStore(pool)
    claimed = await store.claim("w", 30)
    assert claimed is not None
    await store.pause(
        claimed[1], ToolCall(id="c1", name="run_command", arguments={"command": "ls"})
    )
    assert await gw.deliver_answers() == 0
    await gw.deliver_answers()  # told once
    assert sum("Waiting for your approval" in t for _, t in fake.sent) == 1
    row = fake.components[-1][0]["components"]
    return {b["label"]: b["custom_id"] for b in row}


def press(custom_id: str, user: str = ME) -> dict[str, Any]:
    return {
        "id": "i1",
        "token": "itok",
        "type": 3,
        "user": {"id": user},
        "data": {"custom_id": custom_id},
        "message": {"content": "✋ Waiting"},
    }


async def test_approve_decides_the_call_and_strangers_cannot(pool: Pool) -> None:
    fake = FakeDiscord()
    gw = DiscordGateway(pool, api(fake), Settings(**CHATTING))  # type: ignore[arg-type]
    keys = await waiting(pool, gw, fake)
    assert '"command": "ls"' in fake.sent[-1][1]  # the person sees what they approve
    await gw.on_interaction(press(keys["Approve"], user="222222"))
    assert fake.responses[-1] == (4, {"content": "This account cannot decide that.", "flags": 64})
    await gw.on_interaction(press("ok:" + "0" * 24))
    assert fake.responses[-1][1]["content"] == "That request is no longer waiting."
    await gw.on_interaction(press(keys["Approve"]))
    [turn] = await turns(pool)
    assert turn["state"] == "queued" and turn["approvals"]["c1"]["approved"] is True
    assert fake.responses[-1] == (7, {"content": "✋ Waiting\n\n✅ Approved", "components": []})
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT action, detail FROM audit_log")
        [audit] = await cur.fetchall()
    assert (audit["action"], audit["detail"]["via"]) == ("tool_approved", "discord")


async def test_deny_denies_and_a_failure_is_reported(pool: Pool) -> None:
    fake = FakeDiscord()
    gw = DiscordGateway(pool, api(fake), Settings(**CHATTING))  # type: ignore[arg-type]
    keys = await waiting(pool, gw, fake)
    await gw.on_interaction(press(keys["Deny"]))
    [turn] = await turns(pool)
    assert turn["approvals"]["c1"]["approved"] is False
    assert fake.responses[-1][1]["content"].endswith("❌ Denied")
    await end(pool, "failed", error="The model gave up.")
    assert await gw.deliver_answers() == 1
    link = f"https://seed.example/chat/{turn['conversation_id']}"
    assert fake.sent[-1] == (DM, f"❌ That failed: The model gave up.\n{link}")


async def test_a_real_websocket_connection_and_a_fatal_close() -> None:
    """The real websocket client against a local server that says hello, takes the
    identify, sends a message event, then closes as Discord does for a bad token."""
    from websockets.asyncio.server import ServerConnection, serve

    got: list[dict[str, Any]] = []

    async def discord(ws: ServerConnection) -> None:
        await ws.send(json.dumps(HELLO))
        got.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"op": 0, "s": 1, "t": "MESSAGE_CREATE", "d": {"id": "9"}}))
        await ws.close(4004, "Authentication failed.")

    async with serve(discord, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        def rest(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"url": f"ws://127.0.0.1:{port}"})

        client = DiscordApi("https://d.test", "tok", transport=httpx.MockTransport(rest))
        gw = DiscordGateway(None, client, Settings(discord_bot_token="tok"))  # type: ignore[arg-type]
        with pytest.raises(DiscordFatal, match="4004"):
            await asyncio.wait_for(gw.connect_once(), timeout=5)
        assert got[0]["op"] == 2 and gw.seq == 1
        await client.aclose()
