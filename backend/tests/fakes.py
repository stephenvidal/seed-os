"""Scripted provider for unit tests of the agent loop (not used outside tests)."""

import asyncio
from collections.abc import AsyncIterator

from seed_api.core.messages import (
    ChatRequest,
    ChatResult,
    Completed,
    Message,
    ModelInfo,
    StreamEvent,
    TextDelta,
    ToolCall,
    Usage,
)
from seed_api.core.providers.base import ProviderError

Step = ChatResult | ProviderError | float  # float = hang for that many seconds


def reply(text: str, tokens: int = 10) -> ChatResult:
    return ChatResult(
        model="fake",
        message=Message(role="assistant", content=text),
        usage=Usage(input_tokens=tokens, output_tokens=tokens),
        finish_reason="stop",
        latency_ms=1,
    )


def calls(*items: tuple[str, dict[str, object]], tokens: int = 10) -> ChatResult:
    return ChatResult(
        model="fake",
        message=Message(
            role="assistant",
            tool_calls=[
                ToolCall(id=f"call_{i}", name=n, arguments=a) for i, (n, a) in enumerate(items)
            ],
        ),
        usage=Usage(input_tokens=tokens, output_tokens=tokens),
        finish_reason="tool_calls",
        latency_ms=1,
    )


class ScriptedProvider:
    name = "fake"

    def __init__(self, script: list[Step]) -> None:
        self.script = list(script)
        self.requests: list[ChatRequest] = []
        self.closed = False

    async def complete(self, request: ChatRequest) -> ChatResult:
        raise NotImplementedError

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request.model_copy(deep=True))
        step = self.script.pop(0)
        if isinstance(step, float):
            await asyncio.sleep(step)
            raise AssertionError("should have been cut off")
        if isinstance(step, ProviderError):
            raise step
        if step.message.content:
            yield TextDelta(text=step.message.content)
        yield Completed(result=step)

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def aclose(self) -> None:
        self.closed = True
