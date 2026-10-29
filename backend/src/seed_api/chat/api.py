"""Chat API: saved conversations. Each message sent becomes a task; clients follow
its reply on the task's event stream (GET /api/v1/tasks/{id}/stream)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, Field

from ..auth import AuthStoreDep, Principal, client_ip, require_role
from ..config import Settings, get_settings
from ..errors import ApiError
from ..flow.api import TaskView
from .store import ChatError, ChatStore, Conversation, ConversationSummary

router = APIRouter(prefix="/api/v1/conversations", tags=["chat"])

AdminOnly = Annotated[Principal, Depends(require_role("admin"))]
SettingsDep = Annotated[Settings, Depends(get_settings)]
IdempotencyKey = Annotated[
    str | None, Header(min_length=1, max_length=200, pattern=r"^[\x21-\x7e]+$")
]
_STATUS = {"not_found": 404, "turn_in_progress": 409, "idempotency_conflict": 409}


def get_chat(request: Request) -> ChatStore:
    store: ChatStore | None = getattr(request.app.state, "chat_store", None)
    if store is None:
        raise ApiError(
            503, "database_not_configured", "Chat needs a database. Set SEED_DATABASE_URL."
        )
    return store


ChatDep = Annotated[ChatStore, Depends(get_chat)]


def _need_provider(settings: Settings) -> None:
    if settings.ollama_api_key is None:
        raise ApiError(
            503,
            "provider_not_configured",
            "No model provider is configured. Set SEED_OLLAMA_API_KEY.",
        )


def _api_error(e: ChatError) -> ApiError:
    return ApiError(_STATUS[e.code], e.code, e.message)


class StartConversation(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=20_000)


class SendMessage(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    # Switches the conversation's model from this turn on.
    model: str | None = Field(default=None, min_length=1, max_length=200)


class ConversationDetail(BaseModel):
    conversation: Conversation
    turns: list[TaskView]


@router.post("", response_model=ConversationDetail, status_code=201)
async def start_conversation(
    body: StartConversation,
    request: Request,
    response: Response,
    principal: AdminOnly,
    chat: ChatDep,
    audit: AuthStoreDep,
    settings: SettingsDep,
    idempotency_key: IdempotencyKey = None,
) -> ConversationDetail:
    """Start a conversation with its first message, which is queued as a task."""
    _need_provider(settings)
    try:
        conv, task, created = await chat.start(
            owner=principal.username,
            model=body.model,
            prompt=body.prompt,
            max_attempts=settings.task_max_attempts,
            idempotency_key=idempotency_key,
        )
    except ChatError as e:
        raise _api_error(e) from e
    if created:
        for action, target in (("conversation_created", conv.id), ("task_created", task.id)):
            await audit.audit(
                action, actor=principal.username, target=str(target), ip=client_ip(request)
            )
    else:
        response.status_code = 200
    return ConversationDetail(conversation=conv, turns=[TaskView.of(task)])


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    principal: AdminOnly,
    chat: ChatDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ConversationSummary]:
    """The signed-in user's conversations, most recently active first."""
    return await chat.list(principal.username, limit=limit)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, principal: AdminOnly, chat: ChatDep
) -> ConversationDetail:
    conv = await chat.get(principal.username, conversation_id)
    if conv is None:
        raise ApiError(404, "not_found", "No such conversation.")
    turns = await chat.turns(conversation_id)
    return ConversationDetail(conversation=conv, turns=[TaskView.of(t) for t in turns])


@router.post("/{conversation_id}/turns", response_model=TaskView, status_code=201)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessage,
    request: Request,
    response: Response,
    principal: AdminOnly,
    chat: ChatDep,
    audit: AuthStoreDep,
    settings: SettingsDep,
    idempotency_key: IdempotencyKey = None,
) -> TaskView:
    """Send a message: queues a task carrying the conversation so far. Answers 409
    turn_in_progress while the previous message is still being answered."""
    _need_provider(settings)
    try:
        task, created = await chat.send(
            conversation_id,
            owner=principal.username,
            prompt=body.prompt,
            model=body.model,
            max_attempts=settings.task_max_attempts,
            idempotency_key=idempotency_key,
            context_turns=settings.chat_context_turns,
        )
    except ChatError as e:
        raise _api_error(e) from e
    if created:
        await audit.audit(
            "task_created", actor=principal.username, target=str(task.id), ip=client_ip(request)
        )
    else:
        response.status_code = 200
    return TaskView.of(task)
