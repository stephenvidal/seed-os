"""Past Hermes Agent sessions as SEED chats (D-045).

Hermes keeps its sessions in `~/.hermes/state.db` (SQLite): a `sessions` table and a
`messages` table whose `role` is user, assistant, tool, system or session_meta, with
times as unix seconds. The page reads that file in the browser and sends the
sessions here in batches, keeping only user messages and assistant text.

Each session becomes a conversation: a user message starts a turn, and the assistant
text after it, up to the next user message, is that turn's answer. Turns are stored
finished (`termination = 'imported'`) at their original times, so they show in Chat
and past-chat search (D-039) but never run, use no tokens, and count by their original
dates. A session
is imported once: its conversation id is derived from the owner and the session id.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from ..auth import AuthStoreDep, Principal, client_ip, require_role
from ..flow.db import Pool
from .api import ChatDep

router = APIRouter(prefix="/api/v1/conversations", tags=["chat"])
AdminOnly = Annotated[Principal, Depends(require_role("admin"))]

# Fixed, so the same Hermes session always maps to the same conversation id.
NAMESPACE = uuid.UUID("5c3b1f0e-9a57-4d1e-8d0a-1f6e2b7c9a44")
MAX_SESSIONS = 50
MAX_MESSAGES = 5_000
MAX_CONTENT = 100_000
MAX_PROMPT = 20_000  # what a turn's prompt may hold, as when typed in Chat


class HermesMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_CONTENT)
    timestamp: float = Field(ge=0)


class HermesSession(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=200)
    started_at: float = Field(ge=0)
    messages: list[HermesMessage] = Field(max_length=MAX_MESSAGES)


class HermesBatch(BaseModel):
    sessions: list[HermesSession] = Field(min_length=1, max_length=MAX_SESSIONS)


Outcome = Literal["imported", "already_imported", "empty"]


class SessionResult(BaseModel):
    id: str
    outcome: Outcome
    turns: int
    conversation_id: uuid.UUID | None


class Turn(BaseModel):
    prompt: str
    answer: str
    asked_at: float
    answered_at: float


def turns_of(messages: list[HermesMessage]) -> list[Turn]:
    """User messages with the assistant text that followed each. Assistant text
    before the first user message has no question and is left out."""
    out: list[Turn] = []
    for m in sorted(messages, key=lambda m: m.timestamp):
        text = m.content.strip()
        if m.role == "user":
            if text:
                out.append(
                    Turn(prompt=text, answer="", asked_at=m.timestamp, answered_at=m.timestamp)
                )
        elif out and text:
            last = out[-1]
            last.answer = f"{last.answer}\n\n{text}" if last.answer else text
            last.answered_at = m.timestamp
    return out


def _at(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=UTC)


def conversation_id(owner: str, session_id: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{owner}/{session_id}")


async def import_session(pool: Pool, owner: str, session: HermesSession) -> SessionResult:
    turns = turns_of(session.messages)
    conv_id = conversation_id(owner, session.id)
    if not turns:
        return SessionResult(id=session.id, outcome="empty", turns=0, conversation_id=None)
    model = session.model or "hermes"
    title = " ".join((session.title or turns[0].prompt).split())[:80] or "Hermes session"
    async with pool.connection() as conn, conn.transaction():
        cur = await conn.execute(
            "INSERT INTO conversations (id, owner, title, model, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING RETURNING id",
            (
                conv_id,
                owner,
                title,
                model,
                _at(min(session.started_at, turns[0].asked_at)),
                _at(turns[-1].answered_at),
            ),
        )
        if await cur.fetchone() is None:
            return SessionResult(
                id=session.id, outcome="already_imported", turns=0, conversation_id=conv_id
            )
        parent: uuid.UUID | None = None
        for n, t in enumerate(turns, 1):
            task_id = uuid.uuid4()
            prompt = t.prompt[:MAX_PROMPT]
            await conn.execute(
                """
                INSERT INTO tasks (id, created_by, title, model, prompt, state, termination,
                                   result_text, max_attempts, last_seq, conversation_id, turn,
                                   parent_id, context, workspace_id, created_at, updated_at,
                                   started_at, finished_at)
                VALUES (%s, %s, %s, %s, %s, 'completed', 'imported', %s, 1, 0, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s)
                """,
                (
                    task_id,
                    owner,
                    " ".join(prompt.split())[:80],
                    model,
                    prompt,
                    t.answer,
                    conv_id,
                    n,
                    parent,
                    Jsonb([]),
                    conv_id,
                    _at(t.asked_at),
                    _at(t.answered_at),
                    _at(t.asked_at),
                    _at(t.answered_at),
                ),
            )
            parent = task_id
        await conn.execute("UPDATE conversations SET head_id = %s WHERE id = %s", (parent, conv_id))
    return SessionResult(
        id=session.id, outcome="imported", turns=len(turns), conversation_id=conv_id
    )


@router.post("/import-hermes", response_model=list[SessionResult])
async def import_hermes(
    body: HermesBatch,
    request: Request,
    principal: AdminOnly,
    chat: ChatDep,
    audit: AuthStoreDep,
) -> list[SessionResult]:
    """Import past Hermes Agent sessions as chats, each once. A session with no user
    message is skipped as empty; one imported before is left as it is."""
    results = [await import_session(chat.pool, principal.username, s) for s in body.sessions]
    imported = [r for r in results if r.outcome == "imported"]
    if imported:
        await audit.audit(
            "hermes_sessions_imported",
            actor=principal.username,
            target="hermes",
            ip=client_ip(request),
            detail={"sessions": len(imported), "turns": sum(r.turns for r in imported)},
        )
    return results
