import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from seed_api.core.agent import Checkpoint, RunEvent, RunLimits, run_agent
from seed_api.core.messages import Message, ToolCall
from seed_api.core.providers.base import ProviderError
from seed_api.core.tools import Tool, ToolRegistry
from seed_api.core.workspace_tools import workspace_tools

from .fakes import ScriptedProvider, calls, reply

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def no_sleep(_: float) -> None:
    return None


async def no_event(_: RunEvent) -> None:
    return None


async def run(provider: ScriptedProvider, tmp: Path, **limits: object):  # type: ignore[no-untyped-def]
    events: list[RunEvent] = []

    async def sink(e: RunEvent) -> None:
        events.append(e)

    result = await run_agent(
        provider=provider,
        model="fake",
        messages=[Message(role="user", content="go")],
        tools=ToolRegistry(workspace_tools(tmp)),
        limits=RunLimits(**limits),  # type: ignore[arg-type]
        on_event=sink,
        sleep=no_sleep,
    )
    return result, events


async def test_plain_reply_completes_in_one_step(tmp_path: Path) -> None:
    result, events = await run(ScriptedProvider([reply("Hi there")]), tmp_path)
    assert result.termination == "completed" and result.final_text == "Hi there"
    assert result.steps == 1 and result.usage.input_tokens == 10
    types = [e.type for e in events]
    assert types == ["run_started", "step_started", "text_delta", "step_completed", "run_finished"]
    assert [e.seq for e in events] == list(range(1, len(events) + 1))


async def test_tool_round_trip_really_writes_and_reads(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            calls(("write_file", {"path": "notes/a.txt", "content": "hello"})),
            calls(("read_file", {"path": "notes/a.txt"})),
            reply("Done"),
        ]
    )
    result, events = await run(provider, tmp_path)
    assert result.termination == "completed" and result.steps == 3
    assert (tmp_path / "notes/a.txt").read_text() == "hello"
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert '"content": "hello"' in tool_msgs[1].content
    # the model saw the tool result on its next request
    assert provider.requests[2].messages[-1].role == "tool"
    assert result.usage.output_tokens == 30
    assert [e.data["ok"] for e in events if e.type == "tool_result"] == [True, True]


async def test_stops_at_max_steps(tmp_path: Path) -> None:
    loop = [calls(("list_files", {})) for _ in range(5)]
    result, events = await run(ScriptedProvider(loop), tmp_path, max_steps=3)
    assert result.termination == "max_steps" and result.steps == 3
    # The last step's tool call is not run: tools were withheld on that step.
    assert len([e for e in events if e.type == "tool_result"]) == 2


async def test_last_step_answers_without_tools(tmp_path: Path) -> None:
    """A run that spends its steps on tools still ends with an answer."""
    provider = ScriptedProvider(
        [calls(("list_files", {})), calls(("list_files", {})), reply("Here is the story.")]
    )
    result, events = await run(provider, tmp_path, max_steps=3)
    assert result.termination == "completed" and result.steps == 3
    assert result.final_text == "Here is the story."
    assert [bool(r.tools) for r in provider.requests] == [True, True, False]
    last = provider.requests[-1].messages
    assert last[-1].role == "system" and "step limit" in last[-1].content
    assert all(m.content != last[-1].content for m in result.messages)  # not kept in history
    started = [e.data for e in events if e.type == "step_started"]
    assert started[-1] == {"step": 3, "wrap_up": True} and "wrap_up" not in started[0]


async def test_a_one_step_run_keeps_its_tools(tmp_path: Path) -> None:
    provider = ScriptedProvider([reply("ok")])
    await run(provider, tmp_path, max_steps=1)
    assert provider.requests[0].tools


async def test_stops_at_token_budget(tmp_path: Path) -> None:
    loop = [calls(("list_files", {}), tokens=60) for _ in range(5)]
    result, _ = await run(ScriptedProvider(loop), tmp_path, max_total_tokens=200)
    assert result.termination == "token_budget" and result.steps == 2


async def test_retryable_error_is_retried_then_succeeds(tmp_path: Path) -> None:
    script = [ProviderError("fake", "rate_limited", "slow down", 429), reply("ok")]
    result, events = await run(ScriptedProvider(script), tmp_path)  # type: ignore[arg-type]
    assert result.termination == "completed"
    assert [e.data["kind"] for e in events if e.type == "provider_retry"] == ["rate_limited"]


async def test_retries_are_bounded(tmp_path: Path) -> None:
    err = ProviderError("fake", "unavailable", "down", 503)
    result, events = await run(
        ScriptedProvider([err, err, err, reply("x")]), tmp_path, provider_retries=2
    )  # type: ignore[arg-type]
    assert result.termination == "provider_error" and "unavailable" in (result.error or "")
    assert len([e for e in events if e.type == "provider_retry"]) == 2


async def test_non_retryable_error_stops_immediately(tmp_path: Path) -> None:
    script = [ProviderError("fake", "auth", "bad key", 401), reply("never")]
    result, events = await run(ScriptedProvider(script), tmp_path)  # type: ignore[arg-type]
    assert result.termination == "provider_error"
    assert not [e for e in events if e.type == "provider_retry"]


async def test_deadline_cuts_off_a_hanging_provider(tmp_path: Path) -> None:
    result, _ = await run(ScriptedProvider([5.0]), tmp_path, max_runtime_s=0.2)  # type: ignore[list-item]
    assert result.termination == "deadline"


async def test_cancellation_between_steps(tmp_path: Path) -> None:
    cancel = asyncio.Event()

    async def sink(e: RunEvent) -> None:
        if e.type == "tool_result":
            cancel.set()

    provider = ScriptedProvider([calls(("list_files", {})), reply("never")])
    result = await run_agent(
        provider=provider,
        model="fake",
        messages=[Message(role="user", content="go")],
        tools=ToolRegistry(workspace_tools(tmp_path)),
        limits=RunLimits(),
        on_event=sink,
        cancel=cancel,
    )
    assert result.termination == "cancelled" and len(provider.requests) == 1


async def test_cancellation_interrupts_a_blocked_provider(tmp_path: Path) -> None:
    cancel = asyncio.Event()
    asyncio.get_running_loop().call_later(0.1, cancel.set)
    result = await run_agent(
        provider=ScriptedProvider([30.0]),  # type: ignore[list-item]
        model="fake",
        messages=[Message(role="user", content="go")],
        tools=ToolRegistry(workspace_tools(tmp_path)),
        limits=RunLimits(),
        on_event=no_event,
        cancel=cancel,
    )
    assert result.termination == "cancelled"


async def test_checkpoints_after_tool_rounds_and_resumes_from_one(tmp_path: Path) -> None:
    saved: list[Checkpoint] = []

    async def keep(cp: Checkpoint) -> None:
        saved.append(cp.model_copy(deep=True))

    first = await run_agent(
        provider=ScriptedProvider([calls(("list_files", {})), reply("done")]),
        model="fake",
        messages=[Message(role="user", content="go")],
        tools=ToolRegistry(workspace_tools(tmp_path)),
        limits=RunLimits(),
        on_event=no_event,
        on_checkpoint=keep,
    )
    assert first.termination == "completed"
    assert len(saved) == 1 and saved[0].steps == 1
    assert [m.role for m in saved[0].messages] == ["user", "assistant", "tool"]

    provider = ScriptedProvider([reply("resumed")])
    resumed = await run_agent(
        provider=provider,
        model="fake",
        messages=[Message(role="user", content="ignored on resume")],
        tools=ToolRegistry(workspace_tools(tmp_path)),
        limits=RunLimits(max_steps=3),
        on_event=no_event,
        resume=saved[0],
    )
    assert resumed.termination == "completed" and resumed.steps == 2
    assert resumed.usage.input_tokens == 20  # carried over from the checkpoint
    assert provider.requests[0].messages == saved[0].messages


async def test_excess_tool_calls_in_one_step_are_skipped(tmp_path: Path) -> None:
    many = calls(*[("list_files", {}) for _ in range(4)])
    result, events = await run(
        ScriptedProvider([many, reply("ok")]), tmp_path, max_tool_calls_per_step=2
    )
    oks = [e.data["ok"] for e in events if e.type == "tool_result"]
    assert oks == [True, True, False, False]
    assert result.termination == "completed"


# --- Approvals ------------------------------------------------------------------


class _N(BaseModel):
    n: int


def gated(ran: list[int]) -> ToolRegistry:
    async def handler(inp: _N) -> _N:
        ran.append(inp.n)
        return _N(n=inp.n * 2)

    return ToolRegistry(
        [
            Tool("double", "Double n", _N, _N, handler, "read"),
            Tool("danger", "Double n, gated", _N, _N, handler, "exec", requires_approval=True),
        ]
    )


async def gated_run(provider: ScriptedProvider, registry: ToolRegistry, **kw: object):  # type: ignore[no-untyped-def]
    events: list[RunEvent] = []
    saved: list[Checkpoint] = []

    async def sink(e: RunEvent) -> None:
        events.append(e)

    async def keep(cp: Checkpoint) -> None:
        saved.append(cp.model_copy(deep=True))

    result = await run_agent(
        provider=provider,
        model="fake",
        messages=[Message(role="user", content="go")],
        tools=registry,
        limits=RunLimits(),
        on_event=sink,
        on_checkpoint=keep,
        sleep=no_sleep,
        **kw,  # type: ignore[arg-type]
    )
    return result, events, saved


async def test_a_gated_tool_pauses_the_run_before_it_runs() -> None:
    ran: list[int] = []
    step = calls(("double", {"n": 1}), ("danger", {"n": 2}), ("double", {"n": 3}))
    result, events, saved = await gated_run(ScriptedProvider([step]), gated(ran))
    assert result.termination == "awaiting_approval"
    assert result.awaiting is not None and result.awaiting.name == "danger"
    assert ran == [1]  # the call before ran; the gated one and the one after did not
    cp = saved[-1]
    assert [c.id for c in cp.pending] == ["call_1", "call_2"]
    assert [m.role for m in cp.messages] == ["user", "assistant", "tool"]
    asked = [e.data for e in events if e.type == "approval_requested"]
    assert asked == [{"step": 1, "id": "call_1", "name": "danger", "arguments": {"n": 2}}]


async def test_an_approved_call_runs_on_resume_and_the_run_carries_on() -> None:
    ran: list[int] = []
    step = calls(("double", {"n": 1}), ("danger", {"n": 2}), ("double", {"n": 3}))
    _, _, saved = await gated_run(ScriptedProvider([step]), gated(ran))
    provider = ScriptedProvider([reply("all done")])
    result, events, _ = await gated_run(
        provider, gated(ran), resume=saved[-1], approvals={"call_1": True}
    )
    assert result.termination == "completed" and result.final_text == "all done"
    assert ran == [1, 2, 3] and result.steps == 2
    # The paused call was announced before the pause; only the next one is new.
    assert [e.data["id"] for e in events if e.type == "tool_call"] == ["call_2"]
    tool_msgs = [m for m in provider.requests[0].messages if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["call_0", "call_1", "call_2"]


async def test_a_denied_call_never_runs_and_the_model_is_told() -> None:
    ran: list[int] = []
    _, _, saved = await gated_run(ScriptedProvider([calls(("danger", {"n": 5}))]), gated(ran))
    provider = ScriptedProvider([reply("ok, skipped")])
    result, events, _ = await gated_run(
        provider, gated(ran), resume=saved[-1], approvals={"call_0": False}
    )
    assert ran == [] and result.termination == "completed"
    [res] = [e.data for e in events if e.type == "tool_result"]
    assert res["ok"] is False and res["error_kind"] == "denied"
    told = [m.content for m in provider.requests[0].messages if m.role == "tool"]
    assert "denied" in told[0]


async def test_a_second_gated_call_pauses_again() -> None:
    ran: list[int] = []
    step = calls(("danger", {"n": 1}), ("danger", {"n": 2}))
    _, _, saved = await gated_run(ScriptedProvider([step]), gated(ran))
    result, _, again = await gated_run(
        ScriptedProvider([]), gated(ran), resume=saved[-1], approvals={"call_0": True}
    )
    assert result.termination == "awaiting_approval" and result.awaiting is not None
    assert result.awaiting.id == "call_1" and ran == [1]
    assert [c.id for c in again[-1].pending] == ["call_1"]


async def test_a_gated_call_with_bad_arguments_is_not_put_to_a_person() -> None:
    ran: list[int] = []
    step = calls(("danger", {"n": "x"}))
    result, events, _ = await gated_run(ScriptedProvider([step, reply("ok")]), gated(ran))
    assert result.termination == "completed" and ran == []
    types = [e.type for e in events]
    assert "approval_requested" not in types
    [res] = [e for e in events if e.type == "tool_result"]
    assert res.data["error_kind"] == "invalid_arguments"


async def test_the_registry_refuses_a_gated_tool_without_approval() -> None:
    ran: list[int] = []
    out = await gated(ran).execute(ToolCall(id="x", name="danger", arguments={"n": 1}))
    assert out.error_kind == "approval_required" and ran == []


async def test_stops_at_cost_budget(tmp_path: Path) -> None:
    from seed_api.core.pricing import ModelPrice

    loop = [calls(("list_files", {}), tokens=60) for _ in range(5)]
    price = ModelPrice(input_per_m=1_000_000, output_per_m=0)  # $1 per input token
    result, _ = await run(ScriptedProvider(loop), tmp_path, max_cost_usd=100, price=price)
    assert result.termination == "cost_budget" and result.steps == 2
