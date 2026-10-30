"""Notifications (D-030): written with the change they report, only for work a person
started and is not watching, and listed and marked read through the API."""

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient

from seed_api.config import Settings
from seed_api.core.messages import ToolCall, Usage
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import Lease, TaskStore, insert_task
from seed_api.notifications.store import BODY_CHARS, NotificationStore
from seed_api.schedules.store import ScheduleInput, ScheduleStore

from .conftest import sign_in, start

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def pool(db_url: str) -> AsyncIterator[Pool]:
    pool = make_pool(db_url, max_size=4)
    await pool.open(wait=True)
    await migrate(pool)
    yield pool
    await pool.close()


async def running(store: TaskStore, **over: object) -> Lease:
    """Create a task and claim it, as a worker would."""
    async with store.pool.connection() as conn:
        row = await insert_task(
            conn,
            **{  # type: ignore[arg-type]
                "created_by": "admin",
                "title": "Weekly report",
                "model": "fake",
                "prompt": "p",
                "max_attempts": 3,
                "idempotency_key": None,
                **over,
            },
        )
    assert row is not None
    claimed = await store.claim("w", 30)
    assert claimed is not None
    return claimed[1]


async def finish(
    store: TaskStore, lease: Lease, state: str, *, text: str = "", error: str = ""
) -> None:
    await store.finish(
        lease,
        state=state,  # type: ignore[arg-type]
        termination="done",
        error=error or None,
        result_text=text,
        usage=Usage(),
    )


async def heard(pool: Pool, owner: str = "admin") -> list[tuple[str, str, str]]:
    return [
        (n.kind, n.title, n.body)
        for n in await NotificationStore(pool).recent(owner, limit=50, unread_only=False)
    ][::-1]


async def test_a_finished_task_tells_its_owner_how_it_went(pool: Pool) -> None:
    store = TaskStore(pool)
    await finish(store, await running(store), "completed", text="All  good.\nSee notes.")
    await finish(
        store, await running(store, title="Backup"), "failed", error="Disk is full" + "!" * 400
    )
    ok, bad = await heard(pool)
    assert ok == ("task_completed", "Weekly report", "All good. See notes.")
    assert bad[:2] == ("task_failed", "Backup")
    assert bad[2].startswith("Disk is full!") and len(bad[2]) == BODY_CHARS and bad[2].endswith("…")
    [n] = [n for n in await NotificationStore(pool).recent("admin", limit=1, unread_only=False)]
    assert n.task_id is not None and n.read_at is None


async def test_a_task_the_owner_canceled_is_not_news(pool: Pool) -> None:
    store = TaskStore(pool)
    await finish(store, await running(store), "canceled")
    assert await heard(pool) == []


async def test_chat_turns_and_agent_tasks_are_not_announced_but_their_approvals_are(
    pool: Pool,
) -> None:
    store = TaskStore(pool)
    first, second = uuid.uuid4(), uuid.uuid4()
    async with pool.connection() as conn:
        for c in (first, second):
            await conn.execute(
                "INSERT INTO conversations (id, owner, title, model) "
                "VALUES (%s, 'admin', 'c', 'm')",
                (c,),
            )
    await finish(store, await running(store, conversation_id=first, turn=1), "completed")
    parent = await running(store, title="Parent")
    await finish(
        store,
        await running(store, title="Child", parent_task_id=parent.task_id, delegated_call="c1"),
        "completed",
        text="done",
    )
    assert await heard(pool) == []

    call = ToolCall(id="c2", name="run_command", arguments={"command": "ls"})
    await store.pause(await running(store, title="Agent", parent_task_id=parent.task_id), call)
    chat = await running(store, conversation_id=second, turn=1)
    await store.pause(chat, call)
    [(kind, title, body)] = await heard(pool)
    assert (kind, title) == ("approval_needed", "Agent")
    assert body == "Waiting for your approval to call run_command."


async def test_a_skipped_schedule_run_is_announced(pool: Pool) -> None:
    schedules = ScheduleStore(pool)
    s = await schedules.create(
        "admin",
        ScheduleInput(
            name="Report",
            prompt="p",
            model="fake",
            project_id=None,
            kind="interval",
            every_minutes=60,
            at_time=None,
            timezone="UTC",
            enabled=True,
        ),
    )
    for _ in range(2):  # the second run finds the first task still queued
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE schedules SET next_run_at = now() - interval '1 minute' WHERE id = %s",
                (s.id,),
            )
        await schedules.fire_due(3)
    assert await heard(pool) == [
        (
            "schedule_skipped",
            "Report",
            "Skipped a run: the task it started last time is still going.",
        )
    ]
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM schedules WHERE id = %s", (s.id,))
    assert await heard(pool) == []  # gone with the schedule


async def test_reading_is_per_owner(pool: Pool) -> None:
    store = TaskStore(pool)
    notes = NotificationStore(pool)
    await finish(store, await running(store), "completed")
    await finish(store, await running(store, created_by="other"), "completed")
    [mine] = await notes.recent("admin", limit=5, unread_only=False)
    [theirs] = await notes.recent("other", limit=5, unread_only=False)
    assert await notes.unread("admin") == 1
    assert not await notes.mark_read("other", mine.id)  # not theirs to read
    assert await notes.unread("admin") == 1
    assert await notes.mark_read("admin", mine.id) and await notes.mark_read("admin", mine.id)
    assert await notes.unread("admin") == 0 and await notes.unread("other") == 1
    assert await notes.recent("admin", limit=5, unread_only=True) == []
    assert await notes.mark_all_read("other") == 1 and await notes.mark_all_read("other") == 0
    assert theirs.id != mine.id


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings) as c:
        yield sign_in(c)


def test_the_api_lists_counts_and_marks_read(api: TestClient, db_url: str) -> None:
    import psycopg

    empty = api.get("/api/v1/notifications").json()
    assert empty == {"unread": 0, "items": []}
    with psycopg.connect(db_url, autocommit=True) as conn:
        for i in range(3):
            conn.execute(
                "INSERT INTO notifications (owner, kind, title, created_at) "
                "VALUES ('admin', 'task_completed', %s, now() + make_interval(secs => %s))",
                (f"n{i}", i),
            )
    body = api.get("/api/v1/notifications?limit=2").json()
    assert body["unread"] == 3  # all of them, not only the two listed
    assert [n["title"] for n in body["items"]] == ["n2", "n1"]  # newest first
    first = body["items"][0]["id"]
    assert api.post(f"/api/v1/notifications/{first}/read").status_code == 204
    after = api.get("/api/v1/notifications?unread_only=true").json()
    assert after["unread"] == 2 and [n["title"] for n in after["items"]] == ["n1", "n0"]
    assert api.post(f"/api/v1/notifications/{uuid.uuid4()}/read").status_code == 404
    assert api.post("/api/v1/notifications/read-all").status_code == 204
    assert api.get("/api/v1/notifications").json()["unread"] == 0
    assert api.get("/api/v1/notifications?limit=0").status_code == 422


def test_notifications_need_a_session(db_settings: Settings) -> None:
    with start(db_settings) as c:
        assert c.get("/api/v1/notifications").status_code == 401


async def test_only_notifications_read_long_ago_are_deleted(pool: Pool) -> None:
    notes = NotificationStore(pool)
    async with pool.connection() as conn:
        for title, read in [
            ("old read", "now() - interval '31 days'"),
            ("new read", "now() - interval '29 days'"),
            ("unread", "NULL"),
        ]:
            await conn.execute(
                f"INSERT INTO notifications (owner, kind, title, read_at, created_at) "  # noqa: S608
                f"VALUES ('admin', 'task_completed', %s, {read}, now() - interval '90 days')",
                (title,),
            )
    assert await notes.purge_read(30) == 1
    left = {n.title for n in await notes.recent("admin", limit=10, unread_only=False)}
    assert left == {"new read", "unread"}
