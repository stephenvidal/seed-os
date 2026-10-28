import asyncio
from pathlib import Path

import pytest

from seed_api.core.agent import RunEvent, RunLimits, run_agent
from seed_api.core.messages import Message
from seed_api.core.providers.base import ProviderError
from seed_api.core.tools import ToolRegistry
from seed_api.core.workspace_tools import workspace_tools

from .fakes import ScriptedProvider, calls, reply

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def no_sleep(_: float) -> None:
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
    result, _ = await run(ScriptedProvider(loop), tmp_path, max_steps=3)
    assert result.termination == "max_steps" and result.steps == 3


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


async def test_excess_tool_calls_in_one_step_are_skipped(tmp_path: Path) -> None:
    many = calls(*[("list_files", {}) for _ in range(4)])
    result, events = await run(
        ScriptedProvider([many, reply("ok")]), tmp_path, max_tool_calls_per_step=2
    )
    oks = [e.data["ok"] for e in events if e.type == "tool_result"]
    assert oks == [True, True, False, False]
    assert result.termination == "completed"
