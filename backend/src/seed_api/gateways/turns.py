"""A message from a chat app as a SEED chat turn, shared by the gateways (D-032, D-044)."""

import uuid

from ..chat.store import ChatError, ChatStore
from ..config import Settings

MAX_PROMPT_CHARS = 20_000


async def queue_turn(
    chats: ChatStore,
    settings: Settings,
    *,
    owner: str,
    conversation: uuid.UUID | None,
    prompt: str,
    key: str,
) -> tuple[uuid.UUID, uuid.UUID] | str:
    """Queue `prompt` as the next turn of `conversation`, or of a new one when there is
    none (or it was deleted in the app). Returns (conversation, task), or what to tell
    the person when it cannot be queued. `key` makes a message read twice one turn."""
    if settings.ollama_api_key is None:
        return "SEED has no model provider configured, so it cannot answer."
    if len(prompt) > MAX_PROMPT_CHARS:
        return f"That message is too long: send at most {MAX_PROMPT_CHARS:,} characters."
    try:
        if conversation is None:
            raise ChatError("not_found", "no conversation yet")
        task, _ = await chats.send(
            conversation,
            owner=owner,
            prompt=prompt,
            model=None,
            max_attempts=settings.task_max_attempts,
            idempotency_key=key,
            context_turns=settings.chat_context_turns,
        )
    except ChatError as e:
        if e.code == "turn_in_progress":
            return "SEED is still answering your last message. Send this again after."
        if e.code != "not_found":
            return e.message
        if settings.default_model is None:
            return "No model is chosen: set SEED_DEFAULT_MODEL on the server."
        conv, task, _ = await chats.start(
            owner=owner,
            model=settings.default_model,
            prompt=prompt,
            max_attempts=settings.task_max_attempts,
            idempotency_key=key,
        )
        conversation = conv.id
    return conversation, task.id
