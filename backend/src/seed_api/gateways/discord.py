"""Discord gateway (D-044): SEED in your Discord direct messages, as on Telegram.

It runs as its own process (`python -m seed_api.gateways.discord`). It keeps one
connection to Discord's Gateway (a websocket it opens, so it needs no inbound port)
and reads direct messages to the bot. A message from the linked Discord account
(SEED_DISCORD_USER_ID) is a chat turn, as if typed in the app; anyone else is told
their id, which the owner sets to link it. Answers, approvals (with Approve and Deny
buttons) and notifications are sent to that account's direct-message channel over
Discord's REST API. Discord shows Markdown itself, so answers are sent as written.

A notification is marked sent only after Discord took it, and only those from the
last hour are sent, so a gateway that was off does not send a backlog. A turn carries
the key `discord:<message id>`, so a message delivered twice (Discord replays events
when a connection resumes) is answered once.
"""

import asyncio
import json
import logging
import random
import signal
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from typing import Any, Protocol

import httpx
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from ..auth import AuthStore
from ..chat.store import ChatStore
from ..config import Settings, get_settings
from ..flow.db import Pool, make_pool, migrate
from ..flow.store import TERMINAL, TaskStore
from ..notifications.store import Notification
from .telegram import decision_key, message_for
from .turns import queue_turn

log = logging.getLogger("seed.discord")

FRESH = timedelta(hours=1)
BATCH = 20
SEND_EVERY_SECONDS = 3.0
BACKOFF_SECONDS = 10.0
# Discord takes up to 2000 characters a message; longer answers go in parts.
PART_CHARS = 1900
ARGS_CHARS = 1200
# Gateway intents: direct messages only. Their text reaches a bot without the
# privileged message content intent.
INTENTS = 1 << 12
# Close codes after which reconnecting cannot help (bad token, intents refused).
FATAL_CLOSE = {4004, 4010, 4011, 4012, 4013, 4014}
EPHEMERAL = 64

HELP = (
    "Send a message and SEED answers it, as in Chat. Messages continue one "
    "conversation; /new starts another. Start a message with /name to use your "
    "skill called name. Notifications arrive here too."
)


class DiscordError(Exception):
    def __init__(self, status: int, description: str) -> None:
        super().__init__(f"Discord answered {status}: {description}")
        self.status = status
        # 429 (too many requests) and 5xx pass; anything else will not.
        self.lasting = status != 429 and status < 500


class DiscordFatal(Exception):
    """Discord closed the connection for a reason reconnecting cannot fix."""


class DiscordApi:
    """The REST calls the gateway makes."""

    def __init__(
        self, base_url: str, token: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={
                "Authorization": f"Bot {token}",
                "User-Agent": "DiscordBot (https://github.com/stephenvidal/seed-os, 1)",
            },
            timeout=20,
            transport=transport,
        )

    async def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        try:
            r = await self._http.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise DiscordError(503, f"unreachable ({type(e).__name__})") from None
        if r.status_code == 204:
            return None
        try:
            data = r.json()
        except ValueError:
            raise DiscordError(r.status_code, "not JSON") from None
        if r.status_code >= 400:
            detail = data.get("message", "") if isinstance(data, dict) else ""
            raise DiscordError(r.status_code, str(detail))
        return data

    async def gateway_url(self) -> str:
        data = await self._call("GET", "gateway/bot")
        return str(data["url"])

    async def open_dm(self, user_id: str) -> str:
        """The direct-message channel with a user, opened if need be."""
        data = await self._call("POST", "users/@me/channels", {"recipient_id": user_id})
        return str(data["id"])

    async def send(
        self, channel_id: str, content: str, *, buttons: list[tuple[str, str, int]] | None = None
    ) -> None:
        """Send `content`, mentioning nobody. Buttons are (label, custom id, style)."""
        body: dict[str, Any] = {"content": content, "allowed_mentions": {"parse": []}}
        if buttons:
            body["components"] = [
                {
                    "type": 1,
                    "components": [
                        {"type": 2, "style": style, "label": label, "custom_id": cid}
                        for label, cid, style in buttons
                    ],
                }
            ]
        await self._call("POST", f"channels/{channel_id}/messages", body)

    async def respond(self, interaction: dict[str, Any], kind: int, data: dict[str, Any]) -> None:
        """Answer a button press: 4 sends a message, 7 replaces the pressed one."""
        await self._call(
            "POST",
            f"interactions/{interaction['id']}/{interaction['token']}/callback",
            {"type": kind, "data": data},
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def parts(text: str) -> list[str]:
    """`text` in pieces Discord accepts, split at line breaks where possible."""
    out: list[str] = []
    while len(text) > PART_CHARS:
        cut = text.rfind("\n", 0, PART_CHARS)
        cut = cut if cut > PART_CHARS // 2 else PART_CHARS
        out.append(text[:cut].rstrip("\n"))
        text = text[cut:].lstrip("\n")
    return [*out, text] if text else out


class Socket(Protocol):
    """What the gateway needs of a websocket."""

    async def recv(self) -> str | bytes: ...

    async def send(self, message: str) -> None: ...

    async def close(self, code: int = 1000) -> None: ...

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...


Connector = Callable[[str], AbstractAsyncContextManager[Socket]]


def _connect(url: str) -> AbstractAsyncContextManager[Socket]:
    return ws_connect(url, max_size=2**22, open_timeout=20)


class DiscordGateway:
    def __init__(
        self,
        pool: Pool,
        api: DiscordApi,
        settings: Settings,
        *,
        connector: Connector = _connect,
    ) -> None:
        self.pool = pool
        self.api = api
        self.settings = settings
        self.token = (
            settings.discord_bot_token.get_secret_value() if settings.discord_bot_token else ""
        )
        self.owner = settings.discord_user or settings.admin_username
        self.user_id = settings.discord_user_id
        self.chats = ChatStore(pool)
        self.connector = connector
        self.stop = asyncio.Event()
        # Kept across connections so a dropped one resumes and Discord replays events.
        self.session_id: str | None = None
        self.resume_url: str | None = None
        self.seq: int | None = None

    def link(self, path: str) -> str:
        url = self.settings.public_url
        return f"\n{url.rstrip('/')}{path}" if url else ""

    # --- The direct-message channel -------------------------------------------------

    async def _row(self) -> dict[str, Any] | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM discord_chats WHERE user_id = %s", (self.user_id,)
            )
            return await cur.fetchone()

    async def channel(self) -> str:
        """The linked user's direct-message channel, opened once and kept."""
        if self.user_id is None:
            raise RuntimeError("no Discord account is linked")
        row = await self._row()
        if row is not None:
            return str(row["channel_id"])
        channel = await self.api.open_dm(self.user_id)
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO discord_chats (user_id, channel_id) VALUES (%s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET channel_id = excluded.channel_id",
                (self.user_id, channel),
            )
        return channel

    # --- Notifications --------------------------------------------------------------

    async def send_pending(self) -> int:
        """Send the owner's recent unsent notifications, oldest first; returns how many
        were sent. A lasting refusal marks the row as handled so it does not block the
        rest; a passing one leaves it for the next pass."""
        if self.user_id is None:
            return 0
        channel = await self.channel()
        sent = 0
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT * FROM notifications WHERE owner = %s AND discord_sent_at IS NULL "
                "AND created_at > now() - %s ORDER BY created_at, id LIMIT %s "
                "FOR UPDATE SKIP LOCKED",
                (self.owner, FRESH, BATCH),
            )
            for row in await cur.fetchall():
                n = Notification(**row)
                try:
                    await self.api.send(channel, message_for(n, self.settings.public_url))
                    sent += 1
                except DiscordError as e:
                    if not e.lasting:
                        log.warning("discord send deferred: %s", e)
                        break
                    log.error("discord refused notification %s: %s", n.id, e)
                await conn.execute(
                    "UPDATE notifications SET discord_sent_at = now() WHERE id = %s", (n.id,)
                )
        return sent

    # --- Messages and button presses ------------------------------------------------

    async def on_message(self, d: dict[str, Any]) -> None:
        author = d.get("author") or {}
        if author.get("bot") or d.get("guild_id") is not None:
            return  # its own messages, other bots, and anything outside a DM
        channel = str(d.get("channel_id") or "")
        sender = str(author.get("id") or "")
        if not channel or not sender:
            return
        if sender != self.user_id:
            await self.api.send(
                channel,
                f"This Discord account is not linked to SEED. Its id is {sender}: set "
                f"SEED_DISCORD_USER_ID={sender} on the server to link it.",
            )
            return
        text = d.get("content")
        if not isinstance(text, str) or not text.strip():
            await self.api.send(channel, "SEED reads text messages only.")
            return
        command = text.strip().split()[0].lower()
        if command in ("/start", "/help"):
            await self.api.send(channel, HELP)
        elif command == "/new":
            async with self.pool.connection() as conn:  # an answer still owed is kept
                await conn.execute(
                    "UPDATE discord_chats SET conversation_id = NULL, updated_at = now() "
                    "WHERE user_id = %s",
                    (sender,),
                )
            await self.api.send(channel, "Your next message starts a new conversation.")
        else:
            await self.api.send(channel, await self._turn(channel, text.strip(), str(d["id"])))

    async def _turn(self, channel: str, prompt: str, message_id: str) -> str:
        row = await self._row()
        queued = await queue_turn(
            self.chats,
            self.settings,
            owner=self.owner,
            conversation=row["conversation_id"] if row else None,
            prompt=prompt,
            key=f"discord:{message_id}",
        )
        if isinstance(queued, str):
            return queued
        conversation, task = queued
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO discord_chats (user_id, channel_id, conversation_id, awaiting_task)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET channel_id = excluded.channel_id,
                    conversation_id = excluded.conversation_id,
                    awaiting_task = excluded.awaiting_task, told_call = NULL, updated_at = now()
                """,
                (self.user_id, channel, conversation, task),
            )
        return "Working on it…"

    async def on_interaction(self, d: dict[str, Any]) -> None:
        """A press of Approve or Deny. Only the linked account may decide, and only the
        call that message asked about."""
        if d.get("type") != 3:  # a message component; nothing else is registered
            return
        user = d.get("user") or (d.get("member") or {}).get("user") or {}
        custom = (d.get("data") or {}).get("custom_id")

        async def refuse(text: str) -> None:
            await self.api.respond(d, 4, {"content": text, "flags": EPHEMERAL})

        if str(user.get("id") or "") != self.user_id or not isinstance(custom, str):
            await refuse("This account cannot decide that.")
            return
        verb, _, key = custom.partition(":")
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT t.id, t.awaiting_approval FROM discord_chats c "
                "JOIN tasks t ON t.id = c.awaiting_task "
                "WHERE c.user_id = %s AND t.state = 'waiting'",
                (self.user_id,),
            )
            row = await cur.fetchone()
        call = row["awaiting_approval"] if row else None
        if (
            row is None
            or call is None
            or verb not in ("ok", "no")
            or key != decision_key(row["id"], call["id"])
        ):
            await refuse("That request is no longer waiting.")
            return
        approved = verb == "ok"
        task = await TaskStore(self.pool).decide(
            row["id"], call_id=call["id"], approved=approved, by=self.owner
        )
        if task is None:
            await refuse("That request is no longer waiting.")
            return
        await AuthStore(self.pool).audit(
            "tool_approved" if approved else "tool_denied",
            actor=self.owner,
            target=f"{row['id']}/{call['id']}",
            detail={"tool": call["name"], "arguments": call["arguments"], "via": "discord"},
        )
        old = str((d.get("message") or {}).get("content") or "")
        verdict = "✅ Approved" if approved else "❌ Denied"
        await self.api.respond(d, 7, {"content": f"{old}\n\n{verdict}", "components": []})

    # --- Answers --------------------------------------------------------------------

    async def deliver_answers(self) -> int:
        """Send the answer of the user's turn once it has ended, and tell them once per
        call when the turn waits for an approval; returns answers sent."""
        if self.user_id is None:
            return 0
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT c.channel_id, c.told_call, t.id, t.state, t.result_text, t.error,
                       t.conversation_id, t.awaiting_approval
                FROM discord_chats c JOIN tasks t ON t.id = c.awaiting_task
                WHERE c.user_id = %s
                """,
                (self.user_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return 0
        channel = str(row["channel_id"])
        here = self.link(f"/chat/{row['conversation_id']}")
        call = row["awaiting_approval"]
        if row["state"] == "waiting" and call and call.get("id") != row["told_call"]:
            shown = json.dumps(call.get("arguments") or {}, ensure_ascii=False, indent=1)
            if len(shown) > ARGS_CHARS:
                shown = shown[:ARGS_CHARS] + "…"
            key = decision_key(row["id"], call.get("id"))
            await self.api.send(
                channel,
                f"✋ Waiting for your approval to call `{call.get('name')}`:\n"
                f"```json\n{shown}\n```{here}",
                buttons=[("Approve", f"ok:{key}", 3), ("Deny", f"no:{key}", 4)],
            )
            async with self.pool.connection() as conn:
                await conn.execute(
                    "UPDATE discord_chats SET told_call = %s WHERE user_id = %s",
                    (call.get("id"), self.user_id),
                )
            return 0
        if row["state"] not in TERMINAL:
            return 0
        if row["state"] == "completed":
            answer = (row["result_text"] or "").strip()
            pieces = parts(answer) or [f"Done. The answer has no text to show here.{here}"]
        elif row["state"] == "failed":
            pieces = [f"❌ That failed: {row['error'] or 'no reason given'}{here}"]
        else:
            pieces = ["That message was canceled."]
        for piece in pieces:
            await self.api.send(channel, piece)
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE discord_chats SET awaiting_task = NULL, told_call = NULL, "
                "updated_at = now() WHERE user_id = %s AND awaiting_task = %s",
                (self.user_id, row["id"]),
            )
        return 1

    async def send_all(self) -> None:
        await self.deliver_answers()
        await self.send_pending()

    # --- The Gateway connection -----------------------------------------------------

    async def dispatch(self, event: str | None, d: Any) -> None:
        if event == "READY":
            self.session_id = d.get("session_id")
            self.resume_url = d.get("resume_gateway_url")
            log.info("discord: connected as %s", (d.get("user") or {}).get("username"))
            return
        handler: Callable[[dict[str, Any]], Awaitable[None]] | None = {
            "MESSAGE_CREATE": self.on_message,
            "INTERACTION_CREATE": self.on_interaction,
        }.get(event or "")
        if handler is None or not isinstance(d, dict):
            return
        try:
            await handler(d)
        except DiscordError as e:
            log.warning("discord reply failed: %s", e)
        except Exception:  # a database outage, say: keep the connection up
            log.exception("discord: handling %s failed", event)

    async def connect_once(self) -> None:
        """One Gateway connection, from hello to close. Returns when Discord asks for a
        reconnect or the connection drops; raises DiscordFatal when retrying is useless."""
        base = self.resume_url or await self.api.gateway_url()
        async with self.connector(f"{base.rstrip('/')}/?v=10&encoding=json") as ws:
            hello = json.loads(await ws.recv())
            if hello.get("op") != 10:
                raise ConnectionError("Discord did not say hello")
            interval = float(hello["d"]["heartbeat_interval"]) / 1000
            if self.session_id and self.seq is not None:
                await ws.send(
                    json.dumps(
                        {
                            "op": 6,
                            "d": {
                                "token": self.token,
                                "session_id": self.session_id,
                                "seq": self.seq,
                            },
                        }
                    )
                )
            else:
                await ws.send(
                    json.dumps(
                        {
                            "op": 2,
                            "d": {
                                "token": self.token,
                                "intents": INTENTS,
                                "properties": {"os": "linux", "browser": "seed", "device": "seed"},
                            },
                        }
                    )
                )
            acked = asyncio.Event()
            acked.set()

            async def beat() -> None:
                await asyncio.sleep(interval * random.random())  # noqa: S311 - jitter, not crypto
                while True:
                    if not acked.is_set():  # the last beat went unanswered: a zombie link
                        await ws.close(4000)
                        return
                    acked.clear()
                    await ws.send(json.dumps({"op": 1, "d": self.seq}))
                    await asyncio.sleep(interval)

            heart = asyncio.create_task(beat())
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    op = msg.get("op")
                    if op == 0:
                        if isinstance(msg.get("s"), int):
                            self.seq = msg["s"]
                        await self.dispatch(msg.get("t"), msg.get("d"))
                    elif op == 1:
                        await ws.send(json.dumps({"op": 1, "d": self.seq}))
                    elif op == 11:
                        acked.set()
                    elif op == 7:  # reconnect and resume
                        await ws.close(4000)
                        return
                    elif op == 9:  # invalid session; resumable only when d is true
                        if not msg.get("d"):
                            self.session_id = self.resume_url = None
                            self.seq = None
                        await ws.close(4000)
                        await asyncio.sleep(1 + 4 * random.random())  # noqa: S311
                        return
            except ConnectionClosed as e:
                code = e.rcvd.code if e.rcvd is not None else None
                if code in FATAL_CLOSE:
                    raise DiscordFatal(f"Discord closed the connection with code {code}") from None
                log.warning("discord: connection closed (%s); reconnecting", code)
            finally:
                heart.cancel()

    async def _receive_forever(self) -> None:
        while not self.stop.is_set():
            try:
                await self.connect_once()
                wait = 1.0
            except DiscordFatal as e:
                log.error("discord: %s. Check SEED_DISCORD_BOT_TOKEN; the gateway stops.", e)
                self.stop.set()
                return
            except DiscordError as e:
                log.warning("discord: %s", e)
                wait = BACKOFF_SECONDS
            except Exception as e:  # a dropped network, say: retry
                log.warning("discord: connection failed (%s); retrying", type(e).__name__)
                wait = BACKOFF_SECONDS
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=wait)
            except TimeoutError:
                pass

    async def _send_forever(self) -> None:
        while not self.stop.is_set():
            try:
                await self.send_all()
                wait = SEND_EVERY_SECONDS
            except DiscordError as e:
                log.warning("discord: %s", e)
                wait = BACKOFF_SECONDS
            except Exception:
                log.exception("discord gateway step failed")
                wait = BACKOFF_SECONDS
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=wait)
            except TimeoutError:
                pass

    async def run_forever(self) -> None:
        loops = [
            asyncio.create_task(self._receive_forever()),
            asyncio.create_task(self._send_forever()),
        ]
        await self.stop.wait()
        for t in loops:
            t.cancel()
        await asyncio.gather(*loops, return_exceptions=True)


async def main(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.discord_bot_token is None:
        log.info("SEED_DISCORD_BOT_TOKEN unset: the Discord gateway is off")
        return
    if settings.database_url is None:
        raise SystemExit("SEED_DATABASE_URL is required for the Discord gateway")
    if settings.discord_user_id is None:
        log.warning("SEED_DISCORD_USER_ID unset: message the bot to learn your id")
    api = DiscordApi(settings.discord_api_url, settings.discord_bot_token.get_secret_value())
    pool = make_pool(settings.database_url.get_secret_value(), max_size=2)
    await pool.open(wait=True)
    try:
        await migrate(pool)
        gateway = DiscordGateway(pool, api, settings)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, gateway.stop.set)
        await gateway.run_forever()
    finally:
        await pool.close()
        await api.aclose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    asyncio.run(main())
