"""Ollama adapter (Ollama Cloud at https://ollama.com, or a self-hosted server).

Uses the native `/api/chat` endpoint: NDJSON streaming, function tools, and token
counts in the final chunk (`prompt_eval_count`, `eval_count`). Ollama does not
assign tool-call ids, so this adapter assigns stable ones per response.
"""

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..messages import (
    ChatRequest,
    ChatResult,
    Completed,
    FinishReason,
    Message,
    ModelInfo,
    StreamEvent,
    TextDelta,
    ToolCall,
    Usage,
)
from .base import ErrorKind, ProviderError

NAME = "ollama"


def _to_wire(request: ChatRequest, stream: bool) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for m in request.messages:
        wire: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            wire["tool_calls"] = [
                {"function": {"name": c.name, "arguments": c.arguments}} for c in m.tool_calls
            ]
        if m.role == "tool" and m.tool_name:
            wire["tool_name"] = m.tool_name
        messages.append(wire)
    body: dict[str, Any] = {"model": request.model, "messages": messages, "stream": stream}
    if request.tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    options: dict[str, Any] = {}
    if request.max_output_tokens is not None:
        options["num_predict"] = request.max_output_tokens
    if request.temperature is not None:
        options["temperature"] = request.temperature
    if options:
        body["options"] = options
    return body


def _tool_calls(raw: Any, offset: int = 0) -> list[ToolCall]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ProviderError(NAME, "bad_response", "tool_calls is not a list")
    calls: list[ToolCall] = []
    for i, item in enumerate(raw):
        fn = item.get("function") if isinstance(item, dict) else None
        if not isinstance(fn, dict) or not isinstance(fn.get("name"), str):
            raise ProviderError(NAME, "bad_response", "malformed tool call")
        args = fn.get("arguments", {})
        if isinstance(args, str):  # some models emit a JSON string
            try:
                args = json.loads(args)
            except json.JSONDecodeError as e:
                raise ProviderError(NAME, "bad_response", "tool arguments are not JSON") from e
        if not isinstance(args, dict):
            raise ProviderError(NAME, "bad_response", "tool arguments are not an object")
        call_id = item.get("id") if isinstance(item.get("id"), str) else f"call_{offset + i}"
        calls.append(ToolCall(id=call_id, name=fn["name"], arguments=args))
    return calls


def _finish(done_reason: Any, calls: list[ToolCall]) -> FinishReason:
    if calls:
        return "tool_calls"
    if done_reason == "stop":
        return "stop"
    if done_reason == "length":
        return "length"
    return "other"


def _usage(chunk: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=int(chunk.get("prompt_eval_count") or 0),
        output_tokens=int(chunk.get("eval_count") or 0),
    )


def _kind_for_status(status: int) -> ErrorKind:
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "unavailable"
    return "bad_request"


def _error_text(body: bytes) -> str:
    try:
        data = json.loads(body)
        if isinstance(data, dict) and isinstance(data.get("error"), str):
            return str(data["error"])[:500]
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return body[:200].decode(errors="replace") or "no body"


class OllamaProvider:
    name = NAME

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _raise_for(self, status: int, body: bytes) -> None:
        raise ProviderError(NAME, _kind_for_status(status), _error_text(body), status)

    async def complete(self, request: ChatRequest) -> ChatResult:
        started = time.monotonic()
        try:
            res = await self._client.post("/api/chat", json=_to_wire(request, stream=False))
        except httpx.TimeoutException as e:
            raise ProviderError(NAME, "timeout", "request timed out") from e
        except httpx.TransportError as e:
            raise ProviderError(NAME, "unavailable", f"transport error: {type(e).__name__}") from e
        if res.status_code != 200:
            self._raise_for(res.status_code, res.content)
        try:
            data = res.json()
            msg = data["message"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ProviderError(NAME, "bad_response", "unexpected response shape") from e
        if isinstance(data.get("error"), str):
            raise ProviderError(NAME, "bad_response", data["error"][:500])
        calls = _tool_calls(msg.get("tool_calls"))
        return ChatResult(
            model=str(data.get("model", request.model)),
            message=Message(
                role="assistant", content=str(msg.get("content") or ""), tool_calls=calls
            ),
            usage=_usage(data),
            finish_reason=_finish(data.get("done_reason"), calls),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        started = time.monotonic()
        text: list[str] = []
        calls: list[ToolCall] = []
        try:
            async with self._client.stream(
                "POST", "/api/chat", json=_to_wire(request, stream=True)
            ) as res:
                if res.status_code != 200:
                    self._raise_for(res.status_code, await res.aread())
                async for line in res.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError as e:
                        raise ProviderError(NAME, "bad_response", "invalid NDJSON line") from e
                    if isinstance(chunk.get("error"), str):
                        raise ProviderError(NAME, "unavailable", chunk["error"][:500])
                    msg = chunk.get("message") or {}
                    delta = msg.get("content") or ""
                    if delta:
                        text.append(delta)
                        yield TextDelta(text=delta)
                    calls.extend(_tool_calls(msg.get("tool_calls"), offset=len(calls)))
                    if chunk.get("done"):
                        yield Completed(
                            result=ChatResult(
                                model=str(chunk.get("model", request.model)),
                                message=Message(
                                    role="assistant", content="".join(text), tool_calls=calls
                                ),
                                usage=_usage(chunk),
                                finish_reason=_finish(chunk.get("done_reason"), calls),
                                latency_ms=int((time.monotonic() - started) * 1000),
                            )
                        )
                        return
        except httpx.TimeoutException as e:
            raise ProviderError(NAME, "timeout", "stream timed out") from e
        except httpx.TransportError as e:
            raise ProviderError(NAME, "unavailable", f"transport error: {type(e).__name__}") from e
        raise ProviderError(NAME, "bad_response", "stream ended without a done chunk")

    async def list_models(self) -> list[ModelInfo]:
        try:
            res = await self._client.get("/api/tags")
        except httpx.TimeoutException as e:
            raise ProviderError(NAME, "timeout", "request timed out") from e
        except httpx.TransportError as e:
            raise ProviderError(NAME, "unavailable", f"transport error: {type(e).__name__}") from e
        if res.status_code != 200:
            self._raise_for(res.status_code, res.content)
        try:
            models = res.json()["models"]
            return [
                ModelInfo(id=str(m["name"]), provider=NAME, size_bytes=m.get("size"))
                for m in models
            ]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ProviderError(NAME, "bad_response", "unexpected model list shape") from e
