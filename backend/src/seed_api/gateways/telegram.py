"""Telegram gateway (D-031): sends a person's notifications to one Telegram chat.

It runs as its own process (`python -m seed_api.gateways.telegram`), as Telegram
lets one client at a time read a bot's updates. It long-polls for messages, so it
needs no inbound port: a message from the linked chat gets a short reply, one from
any other chat is told its id, which the owner sets as SEED_TELEGRAM_CHAT_ID to link
it. Notifications are sent once each: a row is marked sent only after Telegram took
it, and only those from the last hour are sent, so a gateway that was off does not
send a backlog when it starts.
"""

import asyncio
import logging
import signal
from datetime import timedelta
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..flow.db import Pool, make_pool, migrate
from ..notifications.store import Notification

log = logging.getLogger("seed.telegram")

FRESH = timedelta(hours=1)
BATCH = 20
POLL_SECONDS = 25
SEND_EVERY_SECONDS = 3.0
BACKOFF_SECONDS = 10.0

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

    async def send_message(self, chat_id: int, text: str) -> None:
        await self._call(
            "sendMessage",
            {"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}},
        )

    async def aclose(self) -> None:
        await self._http.aclose()


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
        self.stop = asyncio.Event()

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
        await self.api.send_message(
            chat, f"This chat is linked to SEED. Notifications for {self.owner} arrive here."
        )

    async def receive_once(self) -> int:
        updates = await self.api.get_updates(self.offset)
        for u in updates:
            self.offset = int(u["update_id"]) + 1
            try:
                await self.handle(u)
            except TelegramError as e:
                log.warning("telegram reply failed: %s", e)
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
            asyncio.create_task(self._loop(self.send_pending, SEND_EVERY_SECONDS)),
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
