import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from seed_api.core.messages import ChatRequest, Completed, Message, TextDelta, ToolCall, ToolSpec
from seed_api.core.providers.base import ProviderError
from seed_api.core.providers.ollama import OllamaProvider

pytestmark = pytest.mark.anyio

WEATHER = ToolSpec(
    name="get_weather",
    description="Weather for a city",
    parameters={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def make(handler: Callable[[httpx.Request], httpx.Response]) -> OllamaProvider:
    return OllamaProvider("https://ollama.test/", "k-123", transport=httpx.MockTransport(handler))


def req(**kw: Any) -> ChatRequest:
    return ChatRequest(model="m", messages=[Message(role="user", content="hi")], **kw)


async def test_complete_sends_auth_tools_and_options_and_maps_usage() -> None:
    seen: dict[str, Any] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["auth"] = r.headers.get("authorization")
        seen["path"] = r.url.path
        seen["body"] = json.loads(r.content)
        return httpx.Response(
            200,
            json={
                "model": "m",
                "message": {"role": "assistant", "content": "Hello"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 3,
            },
        )

    p = make(handler)
    result = await p.complete(req(tools=[WEATHER], max_output_tokens=64, temperature=0.2))
    assert seen["auth"] == "Bearer k-123" and seen["path"] == "/api/chat"
    body = seen["body"]
    assert body["stream"] is False
    assert body["tools"][0]["function"]["name"] == "get_weather"
    assert body["options"] == {"num_predict": 64, "temperature": 0.2}
    assert result.message.content == "Hello"
    assert result.finish_reason == "stop"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (12, 3)


async def test_tool_calls_are_parsed_with_ids_and_string_arguments() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        calls = [
            {"function": {"name": "get_weather", "arguments": {"city": "Oslo"}}},
            {"function": {"name": "get_weather", "arguments": '{"city": "Rome"}'}},
        ]
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "", "tool_calls": calls},
                "done": True,
            },
        )

    result = await make(handler).complete(req(tools=[WEATHER]))
    assert result.finish_reason == "tool_calls"
    assert [c.id for c in result.message.tool_calls] == ["call_0", "call_1"]
    assert result.message.tool_calls[1].arguments == {"city": "Rome"}


async def test_tool_history_is_sent_back_in_wire_format() -> None:
    seen: dict[str, Any] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(r.content)
        return httpx.Response(200, json={"message": {"content": "ok"}, "done": True})

    history = [
        Message(role="user", content="weather?"),
        Message(
            role="assistant",
            tool_calls=[ToolCall(id="call_0", name="get_weather", arguments={"city": "Oslo"})],
        ),
        Message(role="tool", content='{"temp": 3}', tool_call_id="call_0", tool_name="get_weather"),
    ]
    await make(handler).complete(ChatRequest(model="m", messages=history))
    sent = seen["body"]["messages"]
    assert sent[1]["tool_calls"][0]["function"] == {
        "name": "get_weather",
        "arguments": {"city": "Oslo"},
    }
    assert sent[2] == {"role": "tool", "content": '{"temp": 3}', "tool_name": "get_weather"}


@pytest.mark.parametrize(
    ("status", "kind", "retryable"),
    [
        (401, "auth", False),
        (429, "rate_limited", True),
        (503, "unavailable", True),
        (400, "bad_request", False),
    ],
)
async def test_http_errors_are_classified(status: int, kind: str, retryable: bool) -> None:
    p = make(lambda _: httpx.Response(status, json={"error": "nope"}))
    with pytest.raises(ProviderError) as e:
        await p.complete(req())
    assert e.value.kind == kind and e.value.retryable is retryable and e.value.message == "nope"


async def test_transport_failure_and_timeout_are_typed() -> None:
    def refuse(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=r)

    def slow(r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=r)

    with pytest.raises(ProviderError) as e:
        await make(refuse).complete(req())
    assert e.value.kind == "unavailable"
    with pytest.raises(ProviderError) as e:
        await make(slow).complete(req())
    assert e.value.kind == "timeout"


async def test_malformed_response_is_bad_response() -> None:
    with pytest.raises(ProviderError) as e:
        await make(lambda _: httpx.Response(200, json={"nope": 1})).complete(req())
    assert e.value.kind == "bad_response"


def ndjson(*chunks: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, content="\n".join(json.dumps(c) for c in chunks).encode())


async def test_stream_yields_deltas_then_completed_with_usage() -> None:
    p = make(
        lambda _: ndjson(
            {"message": {"content": "Hel"}, "done": False},
            {"message": {"content": "lo"}, "done": False},
            {
                "message": {"content": ""},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 5,
                "eval_count": 2,
            },
        )
    )
    events = [e async for e in p.stream(req())]
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Hel", "lo"]
    done = events[-1]
    assert isinstance(done, Completed)
    assert done.result.message.content == "Hello" and done.result.usage.output_tokens == 2


async def test_stream_collects_tool_calls_across_chunks() -> None:
    p = make(
        lambda _: ndjson(
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "get_weather", "arguments": {"city": "A"}}}
                    ],
                },
                "done": False,
            },
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "get_weather", "arguments": {"city": "B"}}}
                    ],
                },
                "done": False,
            },
            {"message": {"content": ""}, "done": True, "done_reason": "stop"},
        )
    )
    events = [e async for e in p.stream(req(tools=[WEATHER]))]
    done = events[-1]
    assert isinstance(done, Completed)
    assert [c.id for c in done.result.message.tool_calls] == ["call_0", "call_1"]
    assert done.result.finish_reason == "tool_calls"


async def test_stream_error_line_and_truncation_raise() -> None:
    with pytest.raises(ProviderError) as e:
        _ = [x async for x in make(lambda _: ndjson({"error": "model overloaded"})).stream(req())]
    assert e.value.kind == "unavailable"
    with pytest.raises(ProviderError) as e:
        _ = [
            x
            async for x in make(
                lambda _: ndjson({"message": {"content": "x"}, "done": False})
            ).stream(req())
        ]
    assert e.value.message == "stream ended without a done chunk"


async def test_list_models() -> None:
    p = make(lambda _: httpx.Response(200, json={"models": [{"name": "gemma3:12b", "size": 10}]}))
    models = await p.list_models()
    assert models[0].id == "gemma3:12b" and models[0].provider == "ollama"
