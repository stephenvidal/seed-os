"""Provider-neutral message and result types. Adapters translate to and from these."""

from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]
FinishReason = Literal["stop", "tool_calls", "length", "other"]


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class Message(BaseModel):
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    # For role="tool": which call this result answers.
    tool_call_id: str | None = None
    tool_name: str | None = None


class ToolSpec(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,64}$")
    description: str
    parameters: dict[str, Any]  # JSON Schema (object)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


class ChatRequest(BaseModel):
    model: str = Field(min_length=1)
    messages: list[Message] = Field(min_length=1)
    tools: list[ToolSpec] = Field(default_factory=list)
    max_output_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0, le=2)


class ChatResult(BaseModel):
    model: str
    message: Message
    usage: Usage
    finish_reason: FinishReason
    latency_ms: int


class TextDelta(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    text: str


class Completed(BaseModel):
    type: Literal["completed"] = "completed"
    result: ChatResult


StreamEvent = TextDelta | Completed


class ModelInfo(BaseModel):
    id: str
    provider: str
    size_bytes: int | None = None
