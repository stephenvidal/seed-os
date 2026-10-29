"""SEED Flow against a real Postgres: state machine, leases, recovery, cancellation."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from seed_api.auth import AuthStore, bootstrap_admin
from seed_api.config import Settings, get_settings
from seed_api.core.providers.base import ProviderError
from seed_api.flow import api as tasks_api
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import LeaseLost, Task, TaskStore
from seed_api.flow.worker import Worker
from seed_api.main import create_app

from .fakes import ScriptedProvider, Step, calls, reply

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def pool(db_url: str) -> AsyncIterator[Pool]:
    pool = make_pool(db_url, max_size=4)
    await pool.open(wait=True)
    assert await migrate(pool) == ["0001_tasks", "0002_auth"]
    yield pool
    await pool.close()


@pytest.fixture
def store(pool: Pool) -> TaskStore:
    return TaskStore(pool)


@pytest.fixture
def wsettings(tmp_path: Path) -> Settings:
    return Settings(workspace_root=str(tmp_path), worker_lease_seconds=3, task_max_attempts=3)


async def new_task(store: TaskStore, *, max_attempts: int = 3, key: str | None = None) -> Task:
    task, _ = await store.create(
        created_by="admin",
        title="t",
        model="fake",
        prompt="write a.txt",
        max_attempts=max_attempts,
        idempotency_key=key,
    )
    return task


def worker(store: TaskStore, settings: Settings, script: list[Step], name: str) -> Worker:
    provider = ScriptedProvider(script)
    w = Worker(store, settings, lambda: provider, worker_id=name)
    w.provider = provider  # type: ignore[attr-defined]
    return w


async def expire_lease(pool: Pool, task_id: uuid.UUID) -> None:
    """Stand-in for the lease running out after a worker died."""
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE tasks SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
            (task_id,),
        )


async def until(predicate, timeout: float = 5.0) -> None:  # type: ignore[no-untyped-def]
    deadline = asyncio.get_running_loop().time() + timeout
    while not await predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached in time"
        await asyncio.sleep(0.02)


async def test_migrations_are_idempotent(pool: Pool) -> None:
    assert await migrate(pool) == []


async def test_worker_completes_task_with_ordered_audit_log(
    store: TaskStore, wsettings: Settings, tmp_path: Path
) -> None:
    task = await new_task(store)
    w = worker(
        store,
        wsettings,
        [calls(("write_file", {"path": "a.txt", "content": "hi"})), reply("Wrote a.txt")],
        "w1",
    )
    assert await w.run_once() is True
    assert await w.run_once() is False  # nothing left to claim

    done = await store.get(task.id)
    assert done is not None
    assert done.state == "completed" and done.termination == "completed"
    assert done.result_text == "Wrote a.txt"
    assert done.usage.input_tokens == 20 and done.attempt == 1 and done.lease_owner is None
    assert (tmp_path / str(task.id) / "a.txt").read_text() == "hi"

    events = await store.events(task.id, after=0, limit=100)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    types = [e.type for e in events]
    assert types[:3] == ["task_created", "attempt_started", "run_started"]
    assert types[-1] == "run_finished" and "tool_result" in types
    assert done.last_seq == len(events)
    assert len(await store.events(task.id, after=3, limit=2)) == 2


async def test_crashed_worker_task_resumes_from_checkpoint(
    pool: Pool, store: TaskStore, wsettings: Settings, tmp_path: Path
) -> None:
    task = await new_task(store)
    a = worker(
        store, wsettings, [calls(("write_file", {"path": "a.txt", "content": "1"})), 30.0], "a"
    )
    running = asyncio.create_task(a.run_once())

    async def checkpointed() -> bool:
        t = await store.get(task.id)
        return t is not None and t.checkpoint is not None

    await until(checkpointed)
    running.cancel()  # the process dies: no further writes from worker a
    with pytest.raises(asyncio.CancelledError):
        await running
    still = await store.get(task.id)
    assert still is not None and still.state == "running" and still.lease_owner == "a"

    await expire_lease(pool, task.id)
    b = worker(store, wsettings, [reply("Finished")], "b")
    assert await b.run_once() is True

    done = await store.get(task.id)
    assert done is not None and done.state == "completed" and done.attempt == 2
    # b continued the conversation instead of starting over: step 1's tool result is there.
    resumed_request = b.provider.requests[0]  # type: ignore[attr-defined]
    assert [m.role for m in resumed_request.messages] == ["system", "user", "assistant", "tool"]
    assert done.usage.input_tokens == 20  # step 1 from a + step 2 from b
    assert (tmp_path / str(task.id) / "a.txt").read_text() == "1"
    events = await store.events(task.id, after=0, limit=100)
    started = [e.data for e in events if e.type == "attempt_started"]
    assert started == [
        {"attempt": 1, "worker": "a", "resumed_at_step": None},
        {"attempt": 2, "worker": "b", "resumed_at_step": 1},
    ]


async def test_stale_worker_is_fenced_out(pool: Pool, store: TaskStore) -> None:
    task = await new_task(store)
    claim_a = await store.claim("a", 30)
    assert claim_a is not None
    await expire_lease(pool, task.id)
    claim_b = await store.claim("b", 30)
    assert claim_b is not None and claim_b[1].attempt == 2

    lease_a = claim_a[1]
    with pytest.raises(LeaseLost):
        await store.append_event(lease_a, "text_delta", {"text": "late"})
    with pytest.raises(LeaseLost):
        await store.heartbeat(lease_a, 30)
    with pytest.raises(LeaseLost):
        await store.finish(
            lease_a,
            state="completed",
            termination="completed",
            error=None,
            result_text="",
            usage=claim_b[0].usage,
        )
    after = await store.get(task.id)
    assert after is not None and after.state == "running" and after.lease_owner == "b"


async def test_task_out_of_attempts_is_dead_lettered(pool: Pool, store: TaskStore) -> None:
    task = await new_task(store, max_attempts=1)
    assert await store.claim("a", 30) is not None
    await expire_lease(pool, task.id)
    assert await store.claim("b", 30) is None  # not reclaimable: no attempts left
    assert await store.sweep() == 1
    dead = await store.get(task.id)
    assert dead is not None and dead.state == "failed" and dead.termination == "abandoned"
    assert dead.error and "every allowed attempt" in dead.error


async def test_cancel_reaches_a_running_task(store: TaskStore, wsettings: Settings) -> None:
    task = await new_task(store)
    w = worker(store, wsettings, [30.0], "w")
    running = asyncio.create_task(w.run_once())

    async def is_running() -> bool:
        t = await store.get(task.id)
        return t is not None and t.state == "running"

    await until(is_running)
    flagged = await store.request_cancel(task.id)
    assert flagged is not None and flagged.state == "running" and flagged.cancel_requested
    await asyncio.wait_for(running, timeout=5)  # next heartbeat (≤1 s) stops the run
    done = await store.get(task.id)
    assert done is not None and done.state == "canceled" and done.termination == "cancelled"


async def test_cancel_queued_task_is_immediate_and_final(store: TaskStore) -> None:
    task = await new_task(store)
    canceled = await store.request_cancel(task.id)
    assert canceled is not None and canceled.state == "canceled"
    assert await store.request_cancel(task.id) is None
    assert await store.claim("w", 30) is None


async def test_graceful_shutdown_hands_task_back_with_checkpoint(
    store: TaskStore, wsettings: Settings
) -> None:
    task = await new_task(store)
    a = worker(
        store, wsettings, [calls(("write_file", {"path": "a.txt", "content": "1"})), 30.0], "a"
    )
    running = asyncio.create_task(a.run_once())

    async def checkpointed() -> bool:
        t = await store.get(task.id)
        return t is not None and t.checkpoint is not None

    await until(checkpointed)
    a.stop.set()  # SIGTERM
    await asyncio.wait_for(running, timeout=5)
    back = await store.get(task.id)
    assert back is not None and back.state == "queued" and back.attempt == 0
    assert back.checkpoint is not None and back.checkpoint.steps == 1

    b = worker(store, wsettings, [reply("Done")], "b")
    assert await b.run_once() is True
    done = await store.get(task.id)
    assert done is not None and done.state == "completed" and done.attempt == 1


async def test_failed_task_can_be_retried_from_scratch(
    store: TaskStore, wsettings: Settings
) -> None:
    task = await new_task(store)
    w = worker(store, wsettings, [ProviderError("fake", "auth", "bad key")], "w")
    await w.run_once()
    failed = await store.get(task.id)
    assert failed is not None and failed.state == "failed"
    assert failed.termination == "provider_error" and failed.error == "auth: bad key"
    assert await store.retry(uuid.uuid4(), extra_attempts=3) is None

    queued = await store.retry(task.id, extra_attempts=3)
    assert queued is not None and queued.state == "queued" and queued.max_attempts == 4
    assert queued.error is None and queued.checkpoint is None
    w2 = worker(store, wsettings, [reply("ok")], "w2")
    assert await w2.run_once() is True
    done = await store.get(task.id)
    assert done is not None and done.state == "completed" and done.attempt == 2
    assert await store.retry(task.id, extra_attempts=3) is None  # completed is final


async def test_idempotency_key_returns_the_same_task(store: TaskStore) -> None:
    first = await new_task(store, key="k-1")
    again, created = await store.create(
        created_by="admin",
        title="t",
        model="fake",
        prompt="other",
        max_attempts=3,
        idempotency_key="k-1",
    )
    assert created is False and again.id == first.id
    other = await new_task(store, key="k-2")
    assert other.id != first.id


async def test_stream_delivers_events_written_after_it_opened(
    store: TaskStore, wsettings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks_api, "STREAM_POLL_S", 0.02)
    settings = wsettings.model_copy(update={"admin_password": SecretStr("a-long-password")})
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.task_store = store
    app.state.auth_store = AuthStore(store.pool)
    await bootstrap_admin(app.state.auth_store, settings)
    task = await new_task(store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        login = {"username": "admin", "password": "a-long-password"}
        assert (await client.post("/api/v1/auth/login", json=login)).status_code == 200
        stream = asyncio.create_task(client.get(f"/api/v1/tasks/{task.id}/stream"))
        await asyncio.sleep(0.1)  # the stream is open and idle before any work happens
        assert not stream.done()
        await worker(store, wsettings, [reply("hello")], "w").run_once()
        body = (await asyncio.wait_for(stream, timeout=5)).text
    types = [
        json.loads(line[6:])["type"] for line in body.splitlines() if line.startswith('data: {"seq')
    ]
    assert types[0] == "task_created" and types[-1] == "run_finished"
    assert "text_delta" in types and body.rstrip().endswith('data: {"state": "completed"}')
