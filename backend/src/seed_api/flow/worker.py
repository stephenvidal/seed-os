"""The SEED Flow worker: claims tasks, runs the agent loop, keeps the lease alive.

Run with `python -m seed_api.flow.worker`. A process runs `worker_concurrency`
workers, each executing one task at a time; scale by running more processes. A
worker that dies mid-task simply stops renewing its lease; once the lease expires
another worker resumes the task from its last checkpoint. SIGTERM/SIGINT stop the
workers gracefully: current runs are interrupted and their tasks handed back,
keeping their checkpoints.
"""

import asyncio
import logging
import os
import signal
import socket
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from ..agents.delegation import (
    DelegateInput,
    agent_system_prompt,
    delegate_tool,
    delegated_prompt,
)
from ..agents.store import AgentCopy, AgentStore
from ..chat.summary import SummaryFailed, summary_through
from ..config import Settings, get_settings
from ..core.agent import Checkpoint, RunEvent, RunLimits, RunResult, Termination, run_agent
from ..core.messages import Message, ToolCall, Usage
from ..core.providers.base import Provider, ProviderError
from ..core.tools import ToolFailure, ToolRegistry
from ..core.workspace_tools import workspace_tools
from ..errors import ApiError
from ..models import make_provider, system_prompt
from ..projects.knowledge import KnowledgeStore, knowledge_tool
from ..projects.memory import MemoryStore, remember_tool
from ..sandbox.client import SandboxClient, sandbox_tools
from ..schedules.store import ScheduleStore
from ..skills.manage import skill_manage_tool
from ..skills.runtime import forced_prompt, forced_skill, skill_tools, skills_index
from ..skills.store import SkillStore
from ..studio.capture import restore, save_changes
from ..studio.store import ArtifactStore
from ..studio.workspace import LocalFiles, SandboxFiles, WorkspaceFiles
from .db import make_pool, migrate
from .store import Delegation, Lease, LeaseLost, Task, TaskStore

log = logging.getLogger("seed.worker")

_STATE: dict[Termination, Literal["completed", "failed", "canceled"]] = {
    "completed": "completed",
    "cancelled": "canceled",
    "max_steps": "failed",
    "deadline": "failed",
    "token_budget": "failed",
    "cost_budget": "failed",
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
        artifacts: ArtifactStore | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.store = store
        self.schedules = ScheduleStore(store.pool)
        self.sandbox = sandbox
        self.artifacts = artifacts
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
        """Settle dead tasks, start the tasks of schedules that are due (D-029), then
        claim and execute at most one. Returns whether a task was executed."""
        await self.store.sweep()
        await self.schedules.fire_due(self.settings.task_max_attempts)
        claimed = await self.store.claim(self.worker_id, self.settings.worker_lease_seconds)
        if claimed is None:
            return False
        await self.execute(*claimed)
        return True

    async def _budget_stop(self, task: Task) -> tuple[str, str] | None:
        """Why the task may not run: (termination, message), or None (D-035). A
        spend limit that cannot be checked refuses the task rather than ignoring it."""
        s = self.settings
        if s.budget_task_usd is None and s.budget_daily_usd is None:
            return None
        if s.price_of(task.model) is None:
            return (
                "price_unknown",
                f"No price is known for {task.model}, so the spend limit cannot be "
                "checked. Add it to SEED_MODEL_PRICES.",
            )
        if s.budget_daily_usd is None:
            return None
        spent = 0.0
        for model, usage in (
            await self.store.usage_since(datetime.now(UTC) - timedelta(days=1))
        ).items():
            price = s.price_of(model)
            if price is not None:
                spent += price.cost(usage)
        if spent >= s.budget_daily_usd:
            return (
                "daily_budget",
                f"The daily spend limit of ${s.budget_daily_usd:.2f} is used up "
                f"(${spent:.2f} in the last 24 hours).",
            )
        return None

    async def execute(self, task: Task, lease: Lease) -> None:
        log.info("task %s attempt %d claimed", task.id, lease.attempt)
        stop = await self._budget_stop(task)
        if stop is not None:
            termination, message = stop
            await self.store.append_event(lease, "budget_stopped", {"reason": termination})
            await self.store.finish(
                lease,
                state="failed",
                termination=termination,
                error=message,
                result_text="",
                usage=task.checkpoint.usage if task.checkpoint is not None else Usage(),
            )
            log.warning("task %s refused: %s", task.id, message)
            return
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

        checkpoints: list[Checkpoint] = []

        async def on_checkpoint(cp: Checkpoint) -> None:
            await self.store.save_checkpoint(lease, cp)
            checkpoints[:] = [cp]

        # A chat turn works in its conversation's workspace, so files persist across turns.
        files: WorkspaceFiles
        if self.sandbox is not None:
            tools = sandbox_tools(
                self.sandbox, task.workspace, self.settings.sandbox_command_timeout_seconds
            )
            files = SandboxFiles(self.sandbox, task.workspace)
        else:  # no sandbox configured: file tools on local disk, no commands
            local = Path(self.settings.workspace_root) / str(task.workspace)
            tools = workspace_tools(local)
            files = LocalFiles(local)
        skill_store = SkillStore(self.store.pool)
        tools.append(  # D-033; each write waits for the owner's approval
            skill_manage_tool(
                skill_store,
                owner=task.created_by,
                agent_id=task.agent.id if task.agent is not None else None,
                task_id=task.id,
            )
        )
        if task.agent is not None:  # an agent's task (D-025): only the tools it may use
            if task.project_id is not None:
                tools.append(
                    knowledge_tool(KnowledgeStore(self.store.pool), project_id=task.project_id)
                )
            tools = [t for t in tools if t.name in task.agent.tools]
        elif task.project_id is not None:
            tools.append(
                remember_tool(
                    MemoryStore(self.store.pool),
                    project_id=task.project_id,
                    task_id=task.id,
                    conversation_id=task.conversation_id,
                )
            )
            tools.append(
                knowledge_tool(KnowledgeStore(self.store.pool), project_id=task.project_id)
            )
        if task.delegation_depth < self.settings.delegation_max_depth:
            agents = await AgentStore(self.store.pool).all(task.created_by)
            if agents:
                tools.append(delegate_tool(agents))
        # The skills it may see (D-033); a `/name` message from the owner follows one.
        skills = await skill_store.visible(task.created_by, task.agent)
        if skills:
            tools.extend(skill_tools(skills))
        forced = forced_skill(task.prompt, skills) if task.agent is None else None
        gated = set(self.settings.approval_required_tools)
        tools = [
            replace(t, requires_approval=t.requires_approval or t.name in gated) for t in tools
        ]
        registry = ToolRegistry(tools)
        limits = RunLimits(
            max_steps=self.settings.run_max_steps,
            max_runtime_s=self.settings.run_max_runtime_seconds,
            max_total_tokens=self.settings.run_max_total_tokens,
            max_cost_usd=self.settings.budget_task_usd,
            price=self.settings.price_of(task.model),
        )
        provider = self.provider_factory()
        beat = asyncio.create_task(heartbeat())
        try:
            await self._restore(task, lease, files)
            summary, extra = await self._summary(task, lease, provider)
            system = [
                agent_system_prompt(task.agent)
                if task.agent is not None
                else system_prompt(task.instructions, task.memory, summary)
            ]
            if skills:
                system.append(skills_index(skills))
            if forced is not None:
                system.append(forced_prompt(forced))
                if task.checkpoint is None:
                    await self.store.append_event(
                        lease, "skill_forced", {"name": forced.name, "found": bool(forced.skill)}
                    )
            result = await run_agent(
                provider=provider,
                model=task.model,
                messages=[
                    Message(role="system", content="\n\n".join(system)),
                    *(Message(role=m.role, content=m.content) for m in task.context),
                    Message(role="user", content=task.prompt),
                ],
                tools=registry,
                limits=limits,
                on_event=on_event,
                on_checkpoint=on_checkpoint,
                resume=task.checkpoint,
                approvals={call_id: d.approved for call_id, d in task.approvals.items()},
                delegated=task.delegations,
                cancel=cancel,
            )
            if not why["lost"]:
                await self._save(task, lease, files)
            if result.termination == "awaiting_delegation" and not why["lost"]:
                step = checkpoints[0] if checkpoints else None
                await self._delegate(task, lease, step, registry, limits)
                return
            await self._settle(
                task, lease, result.model_copy(update={"usage": result.usage + extra}), why
            )
        except LeaseLost:
            log.warning("task %s attempt %d: lease lost; abandoning", task.id, lease.attempt)
        finally:
            cancel.set()
            beat.cancel()
            await provider.aclose()

    async def _summary(
        self, task: Task, lease: Lease, provider: Provider
    ) -> tuple[str | None, Usage]:
        """The summary of the turns left out of this turn's context, and the tokens
        spent making it (D-022). A run resumed from a checkpoint already has it in
        its messages. A failed summary is recorded; the turn runs without it."""
        if task.summary_of is None or task.checkpoint is not None:
            return None, Usage()
        try:
            made = await summary_through(self.store.pool, provider, task.model, task.summary_of)
        except (ProviderError, SummaryFailed) as e:
            log.error("task %s: summarizing earlier turns failed: %s", task.id, e)
            await self.store.append_event(lease, "summary_failed", {"error": str(e)})
            return None, Usage()
        if made is None:
            return None, Usage()
        await self.store.append_event(
            lease,
            "context_summarized",
            {
                "through": str(task.summary_of),
                "turns": made.turns,
                "usage": made.usage.model_dump(),
            },
        )
        return made.text, made.usage

    async def _delegate(
        self,
        task: Task,
        lease: Lease,
        step: Checkpoint | None,
        tools: ToolRegistry,
        limits: RunLimits,
    ) -> None:
        """Start agent tasks for the step's delegate calls, from the one the run
        waits on, then park the task until that one has a result (D-025, D-026).
        The calls start together, up to the limit on agents working at once; a
        call stops the scan when it waits for approval, as the person decides
        before anything after it happens. Calls past the per-task limit, or naming
        no agent, are answered at once with the reason."""
        if step is None or not step.pending:  # the loop checkpoints before pausing
            raise RuntimeError(f"task {task.id}: paused for delegation without a checkpoint")
        sent = step.messages[-1].tool_calls if step.messages else []
        offset = len(sent) - len(step.pending)
        wait_for = step.pending[0]
        active, answered = await self.store.delegation_status(task.id)
        agents = AgentStore(self.store.pool)
        roster = {a.name.lower(): a for a in await agents.all(task.created_by)}
        handed = len(active) + len(answered)
        starts: list[Delegation] = []
        refusals: list[tuple[ToolCall, str]] = []
        for i, call in enumerate(step.pending):
            tool = tools.get(call.name)
            if offset + i >= limits.max_tool_calls_per_step or tool is None:
                break
            if i > 0 and tool.requires_approval:
                break
            if not tool.deferred or call.id in active or call.id in answered:
                continue
            try:
                inp = DelegateInput.model_validate(call.arguments)
            except ValidationError:
                continue  # the loop answers it as an ordinary tool error
            agent = roster.get(" ".join(inp.agent.split()).lower())
            busy = len(active) + len(starts) >= self.settings.delegation_max_parallel
            if agent is None:
                names = ", ".join(sorted(a.name for a in roster.values())) or "none"
                refusals.append((call, f"No agent named {inp.agent!r}. Agents: {names}."))
            elif handed >= self.settings.delegation_max_per_task:
                n = self.settings.delegation_max_per_task
                refusals.append((call, f"This task already handed out {n} jobs, the most allowed."))
            elif busy and call.id != wait_for.id:
                continue  # starts once one of the agents working now reports back
            else:
                prompt = delegated_prompt(inp)
                starts.append(
                    Delegation(call=call, agent=AgentCopy.of(agent), prompt=prompt, about=inp.task)
                )
            handed += 1
        children = await self.store.delegate(
            lease, starts=starts, refusals=refusals, wait_for=wait_for
        )
        for d, child in zip(starts, children, strict=True):
            log.info("task %s delegated to %s as task %s", task.id, d.agent.name, child)
        for call, reason in refusals:
            log.info("task %s: %s: %s", task.id, call.id, reason)

    async def _restore(self, task: Task, lease: Lease, files: WorkspaceFiles) -> None:
        """Refill a workspace the sandbox lost (it restarted) from saved artifacts."""
        if self.artifacts is None:
            return
        try:
            n = await restore(files, self.artifacts, task.workspace)
        except (ToolFailure, OSError) as e:
            log.error("task %s: restoring files failed: %s", task.id, e)
            await self.store.append_event(
                lease, "artifacts_failed", {"stage": "restore", "error": str(e)}
            )
            return
        if n:
            await self.store.append_event(lease, "workspace_restored", {"files": n})

    async def _save(self, task: Task, lease: Lease, files: WorkspaceFiles) -> None:
        """Save every file the run created, changed or deleted (ADR-0014). A failed
        save is recorded and does not change how the task ended."""
        if self.artifacts is None:
            return
        conversation_id = task.conversation_id
        if task.parent_task_id is not None:  # an agent's files belong to its parent's chat
            parent = await self.store.get(task.parent_task_id)
            conversation_id = parent.conversation_id if parent else None
        try:
            report = await save_changes(
                files,
                self.artifacts,
                workspace_id=task.workspace,
                conversation_id=conversation_id,
                task_id=task.id,
            )
        except (ToolFailure, OSError) as e:
            log.error("task %s: saving files failed: %s", task.id, e)
            await self.store.append_event(
                lease, "artifacts_failed", {"stage": "save", "error": str(e)}
            )
            return
        if report.saved or report.skipped or report.truncated:
            await self.store.append_event(lease, "artifacts_saved", report.model_dump())

    async def _settle(
        self, task: Task, lease: Lease, result: RunResult, why: dict[str, bool]
    ) -> None:
        if why["lost"]:
            raise LeaseLost(str(lease.task_id))
        if result.termination == "awaiting_approval" and result.awaiting is not None:
            await self.store.pause(lease, result.awaiting)
            log.info("task %s waiting for approval of %s", lease.task_id, result.awaiting.name)
            return
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
    # A running task holds up to two connections at once (its run and its heartbeat).
    n = settings.worker_concurrency
    pool = make_pool(settings.database_url.get_secret_value(), max_size=2 + 2 * n)
    await pool.open(wait=True)
    artifacts = None
    if settings.artifact_root:
        artifacts = ArtifactStore(pool, Path(settings.artifact_root))
    else:
        log.warning("SEED_ARTIFACT_ROOT unset: task files are not saved as artifacts")
    try:
        await migrate(pool)
        # Several workers per process (D-026), so a task waiting for its agents
        # does not stop the agents' own tasks from running.
        workers = [
            Worker(
                TaskStore(pool),
                settings,
                lambda: make_provider(settings),
                sandbox=sandbox,
                artifacts=artifacts,
            )
            for _ in range(n)
        ]

        def stop() -> None:
            for w in workers:
                w.stop.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop)
        async with asyncio.TaskGroup() as group:  # one failing stops the others
            for w in workers:
                group.create_task(w.run_forever())
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
