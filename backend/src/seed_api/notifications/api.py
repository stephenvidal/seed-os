"""Notifications API (D-030): the bell's list, its unread count, and marking read."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from ..auth import Principal, require_role
from ..errors import ApiError
from .store import Notification, NotificationStore

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

AdminOnly = Annotated[Principal, Depends(require_role("admin"))]


def get_notifications(request: Request) -> NotificationStore:
    store: NotificationStore | None = getattr(request.app.state, "notification_store", None)
    if store is None:
        raise ApiError(
            503,
            "database_not_configured",
            "Notifications need a database. Set SEED_DATABASE_URL.",
        )
    return store


NotificationsDep = Annotated[NotificationStore, Depends(get_notifications)]


class NotificationList(BaseModel):
    # All unread, not only those in `items`.
    unread: int
    items: list[Notification]


@router.get("", response_model=NotificationList)
async def list_notifications(
    principal: AdminOnly,
    store: NotificationsDep,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> NotificationList:
    """The signed-in user's notifications, newest first."""
    return NotificationList(
        unread=await store.unread(principal.username),
        items=await store.recent(principal.username, limit=limit, unread_only=unread_only),
    )


@router.post("/read-all", status_code=204)
async def read_all(principal: AdminOnly, store: NotificationsDep) -> Response:
    await store.mark_all_read(principal.username)
    return Response(status_code=204)


@router.post("/{notification_id}/read", status_code=204)
async def read_one(
    notification_id: uuid.UUID, principal: AdminOnly, store: NotificationsDep
) -> Response:
    if not await store.mark_read(principal.username, notification_id):
        raise ApiError(404, "not_found", "No such notification.")
    return Response(status_code=204)
