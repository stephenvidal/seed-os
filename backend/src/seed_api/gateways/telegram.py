"""Telegram gateway (D-031, D-032): sends a person's notifications to one Telegram
chat, and lets them chat with SEED from it.

It runs as its own process (`python -m seed_api.gateways.telegram`), as Telegram
lets one client at a time read a bot's updates. It long-polls for messages, so it
needs no inbound port: a message from the linked chat gets a short reply, one from
any other chat is told its id, which the owner sets as SEED_TELEGRAM_CHAT_ID to link
it. Notifications are sent once each: a row is marked sent only after Telegram took
it, and only those from the last hour are sent, so a gateway that was off does not
send a backlog when it starts.

A text message from the linked chat is a chat turn, as if typed in the app: it
continues the chat's conversation (or starts one), and the answer is sent back when
the turn ends. The turn carries the key `telegram:<update id>`, so a message read
twice is answered once. /new starts a new conversation.
"""

import asyncio
import html
import logging
import re
import signal
from datetime import timedelta
from typing import Any

import httpx

from ..chat.store import ChatError, ChatStore
from ..config import Settings, get_settings
from ..flow.db import Pool, make_pool, migrate
from ..flow.store import TERMINAL
from ..notifications.store import Notification

log = logging.getLogger("seed.telegram")

FRESH = timedelta(hours=1)
BATCH = 20
POLL_SECONDS = 25
SEND_EVERY_SECONDS = 3.0
BACKOFF_SECONDS = 10.0
# Telegram takes up to 4096 characters a message; longer answers go in parts.
PART_CHARS = 4000

HELP = (
    "Send a message and SEED answers it, as in Chat. Messages continue one "
    "conversation; /new starts another. Start a message with /name to use your "
    "skill called name. Notifications arrive here too."
)

HEADING: dict[str, str] = {
    "task_completed": "✅ Finished",
    "task_failed": "❌ Failed",
    "approval_needed": "✋ Needs your approval",
    "schedule_skipped": "⏭ Schedule skipped a run",
}


class TelegramError(Exception):
    def __init__(self, status: int, description: str) -> None:
        super().__init__(f"Telegram answered {status}: {description}")
        self.status = status
        # 429 (too many requests) and 5xx pass; anything else will not.
        self.lasting = status != 429 and status < 500


class TelegramApi:
    """The two Bot API methods the gateway uses."""

    def __init__(
        self, base_url: str, token: str, transport: httpx.AsyncBaseTransport | None = None
    ):
        self._http = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/bot{token}/",
            timeout=POLL_SECONDS + 10,
            transport=transport,
        )

    async def _call(self, method: str, body: dict[str, Any]) -> Any:
        try:
            r = await self._http.post(method, json=body)
        except httpx.HTTPError as e:
            raise TelegramError(503, f"unreachable ({type(e).__name__})") from None
        try:
            data = r.json()
        except ValueError:
            raise TelegramError(r.status_code, "not JSON") from None
        if not data.get("ok"):
            raise TelegramError(r.status_code, str(data.get("description", "")))
        return data["result"]

    async def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"timeout": POLL_SECONDS, "allowed_updates": ["message"]}
        if offset is not None:
            body["offset"] = offset
        result: list[dict[str, Any]] = await self._call("getUpdates", body)
        return result

    async def send_message(self, chat_id: int, text: str, *, markdown: bool = False) -> None:
        """Send `text`; with `markdown`, as Telegram HTML made from it. Telegram refusing
        that (a tag it cannot parse, a message grown too long) sends the plain text."""
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "link_preview_options": {"is_disabled": True},
        }
        if markdown:
            try:
                await self._call(
                    "sendMessage", {**body, "text": telegram_html(text), "parse_mode": "HTML"}
                )
                return
            except TelegramError as e:
                if e.status != 400:
                    raise
        await self._call("sendMessage", body)

    async def aclose(self) -> None:
        await self._http.aclose()


_FENCE = re.compile(r"```[^\n]*\n(.*?)(?:```|\Z)", re.S)
_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
_ITALIC = re.compile(r"(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+")


def _inline(line: str) -> str:
    """One line of Markdown as Telegram HTML: code, links, bold and italic."""
    held: list[str] = []

    def hold(markup: str) -> str:
        held.append(markup)
        return f"\x00{len(held) - 1}\x00"

    line = _CODE.sub(lambda m: hold(f"<code>{html.escape(m[1], quote=False)}</code>"), line)
    line = _LINK.sub(
        lambda m: hold(
            f'<a href="{html.escape(m[2], quote=True)}">{html.escape(m[1], quote=False)}</a>'
        ),
        line,
    )
    line = html.escape(line, quote=False)
    line = _BOLD.sub(lambda m: f"<b>{m[1] or m[2]}</b>", line)
    line = _ITALIC.sub(lambda m: f"<i>{m[1]}</i>", line)
    return re.sub(r"\x00(\d+)\x00", lambda m: held[int(m[1])], line)


def telegram_html(text: str) -> str:
    """Markdown as the HTML Telegram shows: **bold**, *italic*, `code`, fenced code,
    [links](https://…), headings as bold lines and "- " items as bullets. Anything else
    (tables, quotes) stays as text, with its characters escaped."""
    out: list[str] = []
    last = 0
    for fence in [*_FENCE.finditer(text), None]:
        prose = text[last : fence.start() if fence else len(text)]
        if fence:
            prose = prose.removesuffix("\n")  # the line break before the fence
        for line in prose.split("\n") if prose else []:
            heading = _HEADING.match(line)
            if heading:
                out.append(f"<b>{_inline(heading[1])}</b>")
            else:
                out.append(_inline(_BULLET.sub(r"\1• ", line)))
        if fence:
            out.append(f"<pre>{html.escape(fence[1].rstrip(chr(10)), quote=False)}</pre>")
            last = fence.end() + (text[fence.end() : fence.end() + 1] == "\n")
    return "\n".join(out)


def parts(text: str) -> list[str]:
    """`text` in pieces Telegram accepts, split at line breaks where possible."""
    out: list[str] = []
    while len(text) > PART_CHARS:
        cut = text.rfind("\n", 0, PART_CHARS)
        cut = cut if cut > PART_CHARS // 2 else PART_CHARS
        out.append(text[:cut].rstrip("\n"))
        text = text[cut:].lstrip("\n")
    return [*out, text] if text else out


def message_for(n: Notification, public_url: str | None) -> str:
    """Plain text, so nothing in a title or body needs escaping."""
    lines = [f"{HEADING[n.kind]}: {n.title}"]
    if n.body:
        lines.append(n.body)
    if public_url:
        base = public_url.rstrip("/")
        path = (
            "/schedules"
            if n.kind == "schedule_skipped" or n.task_id is None
            else f"/tasks/{n.task_id}"
        )
        lines.append(base + path)
    return "\n".join(lines)


class TelegramGateway:
    def __init__(self, pool: Pool, api: TelegramApi, settings: Settings) -> None:
        self.pool = pool
        self.api = api
        self.settings = settings
        self.owner = settings.telegram_user or settings.admin_username
        self.chat_id = settings.telegram_chat_id
        self.offset: int | None = None
        self.chats = ChatStore(pool)
        self.stop = asyncio.Event()

    def link(self, path: str) -> str:
        url = self.settings.public_url
        return f"\n{url.rstrip('/')}{path}" if url else ""

    async def send_pending(self) -> int:
        """Send the owner's recent unsent notifications, oldest first; returns how many
        were sent. A lasting refusal marks the row as handled so it does not block the
        rest; a passing one leaves it for the next pass."""
        if self.chat_id is None:
            return 0
        sent = 0
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT * FROM notifications WHERE owner = %s AND telegram_sent_at IS NULL "
                "AND created_at > now() - %s ORDER BY created_at, id LIMIT %s "
                "FOR UPDATE SKIP LOCKED",
                (self.owner, FRESH, BATCH),
            )
            for row in await cur.fetchall():
                n = Notification(**row)
                try:
                    await self.api.send_message(
                        self.chat_id, message_for(n, self.settings.public_url)
                    )
                    sent += 1
                except TelegramError as e:
                    if not e.lasting:
                        log.warning("telegram send deferred: %s", e)
                        break
                    log.error("telegram refused notification %s: %s", n.id, e)
                await conn.execute(
                    "UPDATE notifications SET telegram_sent_at = now() WHERE id = %s", (n.id,)
                )
        return sent

    async def handle(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        chat = (message.get("chat") or {}).get("id")
        if not isinstance(chat, int):
            return
        if chat != self.chat_id:
            await self.api.send_message(
                chat,
                f"This chat is not linked to SEED. Its id is {chat}: set "
                f"SEED_TELEGRAM_CHAT_ID={chat} on the server to link it.",
            )
            return
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            await self.api.send_message(chat, "SEED reads text messages only.")
            return
        command = text.strip().split()[0].split("@")[0].lower()
        if command in ("/start", "/help"):
            await self.api.send_message(chat, HELP)
        elif command == "/new":
            async with self.pool.connection() as conn:  # an answer still owed is kept
                await conn.execute(
                    "UPDATE telegram_chats SET conversation_id = NULL, updated_at = now() "
                    "WHERE chat_id = %s",
                    (chat,),
                )
            await self.api.send_message(chat, "Your next message starts a new conversation.")
        else:
            await self.api.send_message(chat, await self._turn(chat, text.strip(), update))

    async def _turn(self, chat: int, prompt: str, update: dict[str, Any]) -> str:
        """Queue the message as a chat turn; returns what to tell the chat now."""
        if self.settings.ollama_api_key is None:
            return "SEED has no model provider configured, so it cannot answer."
        if len(prompt) > 20_000:
            return "That message is too long: send at most 20,000 characters."
        key = f"telegram:{update['update_id']}"
        conversation = await self._conversation(chat)
        try:
            if conversation is None:
                raise ChatError("not_found", "no conversation yet")
            task, _ = await self.chats.send(
                conversation,
                owner=self.owner,
                prompt=prompt,
                model=None,
                max_attempts=self.settings.task_max_attempts,
                idempotency_key=key,
                context_turns=self.settings.chat_context_turns,
            )
        except ChatError as e:
            if e.code == "turn_in_progress":
                return "SEED is still answering your last message. Send this again after."
            if e.code != "not_found":
                return e.message
            if self.settings.default_model is None:
                return "No model is chosen: set SEED_DEFAULT_MODEL on the server."
            conv, task, _ = await self.chats.start(
                owner=self.owner,
                model=self.settings.default_model,
                prompt=prompt,
                max_attempts=self.settings.task_max_attempts,
                idempotency_key=key,
            )
            conversation = conv.id
        await self._remember(chat, conversation=conversation, awaiting=task.id)
        return "Working on it…"

    async def _conversation(self, chat: int) -> Any:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT conversation_id FROM telegram_chats WHERE chat_id = %s", (chat,)
            )
            row = await cur.fetchone()
        return row["conversation_id"] if row else None

    async def _remember(self, chat: int, *, conversation: Any, awaiting: Any = None) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO telegram_chats (chat_id, conversation_id, awaiting_task)
                VALUES (%s, %s, %s)
                ON CONFLICT (chat_id) DO UPDATE SET conversation_id = excluded.conversation_id,
                    awaiting_task = excluded.awaiting_task, told_call = NULL, updated_at = now()
                """,
                (chat, conversation, awaiting),
            )

    async def deliver_answers(self) -> int:
        """Send the answer of each chat's turn once it has ended, and tell the chat
        once per call when the turn waits for an approval; returns answers sent."""
        if self.chat_id is None:
            return 0
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT c.chat_id, c.told_call, t.id, t.state, t.result_text, t.error,
                       t.conversation_id, t.awaiting_approval
                FROM telegram_chats c JOIN tasks t ON t.id = c.awaiting_task
                WHERE c.chat_id = %s
                """,
                (self.chat_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return 0
        here = self.link(f"/chat/{row['conversation_id']}")
        call = row["awaiting_approval"]
        if row["state"] == "waiting" and call and call.get("id") != row["told_call"]:
            await self.api.send_message(
                row["chat_id"],
                f"✋ Waiting for your approval to call {call.get('name')}. "
                f"Approve or deny it in SEED.{here}",
            )
            async with self.pool.connection() as conn:
                await conn.execute(
                    "UPDATE telegram_chats SET told_call = %s WHERE chat_id = %s",
                    (call.get("id"), row["chat_id"]),
                )
            return 0
        if row["state"] not in TERMINAL:
            return 0
        answered = row["state"] == "completed" and bool((row["result_text"] or "").strip())
        if row["state"] == "completed":
            answer = (row["result_text"] or "").strip()
            pieces = parts(answer) or [f"Done. The answer has no text to show here.{here}"]
        elif row["state"] == "failed":
            pieces = [f"❌ That failed: {row['error'] or 'no reason given'}{here}"]
        else:
            pieces = ["That message was canceled."]
        for piece in pieces:
            await self.api.send_message(row["chat_id"], piece, markdown=answered)
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE telegram_chats SET awaiting_task = NULL, told_call = NULL, "
                "updated_at = now() WHERE chat_id = %s AND awaiting_task = %s",
                (row["chat_id"], row["id"]),
            )
        return 1

    async def send_all(self) -> None:
        await self.deliver_answers()
        await self.send_pending()

    async def receive_once(self) -> int:
        if self.offset is None:
            async with self.pool.connection() as conn:
                cur = await conn.execute("SELECT next_update FROM telegram_offset WHERE id = 1")
                row = await cur.fetchone()
            self.offset = int(row["next_update"]) if row else None
        updates = await self.api.get_updates(self.offset)
        for u in updates:
            try:
                await self.handle(u)
            except TelegramError as e:
                log.warning("telegram reply failed: %s", e)
            self.offset = int(u["update_id"]) + 1
            async with self.pool.connection() as conn:
                await conn.execute(
                    "INSERT INTO telegram_offset (id, next_update) VALUES (1, %s) "
                    "ON CONFLICT (id) DO UPDATE SET next_update = excluded.next_update",
                    (self.offset,),
                )
        return len(updates)

    async def _loop(self, step: Any, pause: float) -> None:
        while not self.stop.is_set():
            try:
                await step()
                wait = pause
            except TelegramError as e:
                log.warning("telegram: %s", e)
                wait = BACKOFF_SECONDS
            except Exception:  # a database outage, say: keep the gateway up and retry
                log.exception("telegram gateway step failed")
                wait = BACKOFF_SECONDS
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=wait)
            except TimeoutError:
                pass

    async def run_forever(self) -> None:
        loops = [
            asyncio.create_task(self._loop(self.receive_once, 0)),
            asyncio.create_task(self._loop(self.send_all, SEND_EVERY_SECONDS)),
        ]
        # Stop at once on a signal, not after the current long poll: nothing is lost,
        # as a notification is marked sent only after Telegram took it.
        await self.stop.wait()
        for t in loops:
            t.cancel()
        await asyncio.gather(*loops, return_exceptions=True)


async def main(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.telegram_bot_token is None:
        log.info("SEED_TELEGRAM_BOT_TOKEN unset: the Telegram gateway is off")
        return
    if settings.database_url is None:
        raise SystemExit("SEED_DATABASE_URL is required for the Telegram gateway")
    if settings.telegram_chat_id is None:
        log.warning("SEED_TELEGRAM_CHAT_ID unset: message the bot to learn your chat's id")
    api = TelegramApi(settings.telegram_api_url, settings.telegram_bot_token.get_secret_value())
    pool = make_pool(settings.database_url.get_secret_value(), max_size=2)
    await pool.open(wait=True)
    try:
        await migrate(pool)
        gateway = TelegramGateway(pool, api, settings)
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
    # httpx logs each request URL, and a Bot API URL holds the token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
