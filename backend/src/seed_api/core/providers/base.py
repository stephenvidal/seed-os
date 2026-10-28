"""The provider contract every adapter implements, and its typed failures."""

from collections.abc import AsyncIterator
from typing import Literal, Protocol

from ..messages import ChatRequest, ChatResult, ModelInfo, StreamEvent

ErrorKind = Literal["auth", "rate_limited", "unavailable", "bad_request", "bad_response", "timeout"]

_RETRYABLE: frozenset[ErrorKind] = frozenset({"rate_limited", "unavailable", "timeout"})


class ProviderError(Exception):
    """A provider failure, classified so callers can decide to retry, fall back, or stop."""

    def __init__(self, provider: str, kind: ErrorKind, message: str, status: int | None = None):
        super().__init__(f"{provider}: {kind}: {message}")
        self.provider = provider
        self.kind = kind
        self.status = status
        self.message = message

    @property
    def retryable(self) -> bool:
        return self.kind in _RETRYABLE


class Provider(Protocol):
    name: str

    async def complete(self, request: ChatRequest) -> ChatResult: ...

    def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]: ...

    async def list_models(self) -> list[ModelInfo]: ...

    async def aclose(self) -> None: ...
