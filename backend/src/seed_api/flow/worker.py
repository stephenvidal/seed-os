"""The SEED Flow worker: claims tasks, runs the agent loop, keeps the lease alive.

Run with `python -m seed_api.flow.worker`. Scale by running more processes; each
executes one task at a time. A worker that dies mid-task simply stops renewing
its lease; once the lease expires another worker resumes the task from its last
checkpoint. SIGTERM/SIGINT stop the worker gracefully: the current run is
interrupted and the task is handed back, keeping its checkpoint.
"""

import asyncio
import logging
import os
import signal
import socket
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from ..config import Settings, get_settings
from ..core.agent import Checkpoint, RunEvent, RunLimits, RunResult, Termination, run_agent
from ..core.messages import Message
from ..core.providers.base import Provider
from ..core.tools import ToolRegistry
from ..core.workspace_tools import workspace_tools
from ..errors import ApiError
from ..models import SYSTEM_PROMPT, make_provider
from ..sandbox.client import SandboxClient, sandbox_tools
from .db import make_pool, migrate
from .store import Lease, LeaseLost, Task, TaskStore

log = logging.getLogger("seed.worker")

_STATE: dict[Termination, Literal["completed", "failed", "canceled"]] = {
    "completed": "completed",
    "cancelled": "canceled",
    "max_steps": "failed",
    "deadline": "failed",
    "token_budget": "failed",
    "provider_error": "failed",
}

ProviderFactory = Callable[[], Provider]


class Worker:
    def __init__(
        self,
        store: TaskStore,
        settings: Settings,
        provider_factory: ProviderFactory,
        *,
        sandbox: SandboxClient | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.store = store
        self.sandbox = sandbox
        self.settings = settings
        self.provider_factory = provider_factory
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.stop = asyncio.Event()

    async def run_forever(self) -> None:
        log.info("worker %s started", self.worker_id)
        while not self.stop.is_set():
            if not await self.run_once():
                try:
                    await asyncio.wait_for(self.stop.wait(), self.settings.worker_poll_seconds)
                except TimeoutError:
                    pass
        log.info("worker %s stopped", self.worker_id)

    async def run_once(self) -> bool:
        """Settle dead tasks, then claim and execute at most one. Returns whether
        a task was executed."""
        await self.store.sweep()
        claimed = await self.store.claim(self.worker_id, self.settings.worker_lease_seconds)
        if claimed is None:
            return False
        await self.execute(*claimed)
        return True

    async def execute(self, task: Task, lease: Lease) -> None:
        log.info("task %s attempt %d claimed", task.id, lease.attempt)
        cancel = asyncio.Event()
        why: dict[str, bool] = {"user": False, "shutdown": False, "lost": False}

        async def heartbeat() -> None:
            interval = self.settings.worker_lease_seconds / 3
            while not cancel.is_set():
                try:
                    await asyncio.wait_for(self.stop.wait(), interval)
                except TimeoutError:
                    pass
                if self.stop.is_set():
                    why["shutdown"] = True
                    cancel.set()
                    return
                try:
                    if await self.store.heartbeat(lease, self.settings.worker_lease_seconds):
                        why["user"] = True
                        cancel.set()
                except LeaseLost:
                    why["lost"] = True
                    cancel.set()

        async def on_event(event: RunEvent) -> None:
            await self.store.append_event(lease, event.type, event.data)

        async def on_checkpoint(cp: Checkpoint) -> None:
            await self.store.save_checkpoint(lease, cp)

        # A chat turn works in its conversation's workspace, so files persist across turns.
        if self.sandbox is not None:
            tools = sandbox_tools(
                self.sandbox, task.workspace, self.settings.sandbox_command_timeout_seconds
            )
        else:  # no sandbox configured: file tools on local disk, no commands
            tools = workspace_tools(Path(self.settings.workspace_root) / str(task.workspace))
        provider = self.provider_factory()
        beat = asyncio.create_task(heartbeat())
        try:
            result = await run_agent(
                provider=provider,
                model=task.model,
                messages=[
                    Message(role="system", content=SYSTEM_PROMPT),
                    *(Message(role=m.role, content=m.content) for m in task.context),
                    Message(role="user", content=task.prompt),
                ],
                tools=ToolRegistry(tools),
                limits=RunLimits(
                    max_steps=self.settings.run_max_steps,
                    max_runtime_s=self.settings.run_max_runtime_seconds,
                    max_total_tokens=self.settings.run_max_total_tokens,
                ),
                on_event=on_event,
                on_checkpoint=on_checkpoint,
                resume=task.checkpoint,
                cancel=cancel,
            )
            await self._settle(lease, result, why)
        except LeaseLost:
            log.warning("task %s attempt %d: lease lost; abandoning", task.id, lease.attempt)
        finally:
            cancel.set()
            beat.cancel()
            await provider.aclose()

    async def _settle(self, lease: Lease, result: RunResult, why: dict[str, bool]) -> None:
        if why["lost"]:
            raise LeaseLost(str(lease.task_id))
        if result.termination == "cancelled" and why["shutdown"] and not why["user"]:
            await self.store.release(lease)
            log.info("task %s released on shutdown", lease.task_id)
            return
        state = _STATE[result.termination]
        await self.store.finish(
            lease,
            state=state,
            termination=result.termination,
            error=result.error,
            result_text=result.final_text,
            usage=result.usage,
        )
        log.info("task %s %s (%s)", lease.task_id, state, result.termination)


async def main(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.database_url is None:
        raise SystemExit("SEED_DATABASE_URL is required for the worker")
    try:
        # Fail at start, not once per task, when no provider is configured.
        await make_provider(settings).aclose()
    except ApiError as e:
        raise SystemExit(e.message) from e
    sandbox = None
    if settings.sandbox_url:
        timeout = settings.sandbox_command_timeout_seconds + 30
        sandbox = SandboxClient.connect(settings.sandbox_url, timeout)
    else:
        log.warning("SEED_SANDBOX_URL unset: tasks get file tools only, no commands")
    pool = make_pool(settings.database_url.get_secret_value(), max_size=4)
    await pool.open(wait=True)
    try:
        await migrate(pool)
        worker = Worker(TaskStore(pool), settings, lambda: make_provider(settings), sandbox=sandbox)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, worker.stop.set)
        await worker.run_forever()
    finally:
        await pool.close()
        if sandbox is not None:
            await sandbox.aclose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    )
    asyncio.run(main())
