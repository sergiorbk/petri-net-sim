"""OpenAI Chat Completions API-compatible request/response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.core.security_config import security_settings


# --- Request schemas ---


class FunctionCall(BaseModel):
    """Function call within a tool call."""

    name: str
    arguments: str  # JSON string


class ToolCall(BaseModel):
    """Tool call made by the assistant."""

    id: str
    type: str = "function"
    function: FunctionCall


class AgentEventDelta(BaseModel):
    """Non-standard streaming extension: agent reasoning step.

    Emitted as `delta.agent_event` on chunk choices so OpenAI-compatible
    clients that don't know about it simply ignore the field. The
    Petri Net Sim UI renders each event as a step card inside the assistant
    message. Tool-call events ride on AIMessage tool_calls (Anthropic
    tool_use blocks parsed by LangChain); tool_result events ride on
    ToolMessage outputs from the LangGraph tool node.
    """

    type: Literal["tool_call", "tool_result"]
    id: str  # tool_call id — ties call and result together
    name: str | None = None  # tool name (on "tool_call")
    input: dict | None = None  # tool arguments (on "tool_call")
    status: Literal["running", "success", "error"] | None = None
    output: str | None = None  # truncated tool result text (on "tool_result")


class ChatMessage(BaseModel):
    """A single message in the conversation."""

    role: str  # system | user | assistant | tool
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    agent_events: list[AgentEventDelta] | None = None

    @field_validator("content")
    @classmethod
    def _cap_content(cls, v: str | None) -> str | None:
        """Bound message size to protect memory and downstream token budgets."""
        if v is not None and len(v) > security_settings.CHAT_MAX_MESSAGE_CHARS:
            raise ValueError(
                f"message content exceeds the maximum of "
                f"{security_settings.CHAT_MAX_MESSAGE_CHARS} characters"
            )
        return v


class StreamOptions(BaseModel):
    """Options for streaming responses."""

    include_usage: bool = False


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model: str
    messages: list[ChatMessage]
    stream: bool = False
    stream_options: StreamOptions | None = None
    # Accepted and ignored. Kept because the OpenAI schema defines it and a
    # generic client sends it unprompted -- rejecting the request over a
    # field it is entitled to send would be worse than not acting on it.
    # Nothing here forwards a temperature to any provider: a growing number
    # of models reject the parameter outright, and no request this app makes
    # has a reason to set one.
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stop: list[str] | str | None = None
    user: str | None = None

    # Accepted but not forwarded to the LLM — our agent uses its own tools
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None

    # Petri Net Sim extension: BYOK credential selection. The OpenAI spec accepts
    # arbitrary string-keyed metadata, so generic OpenAI-compatible clients
    # (OpenAI SDK, curl, etc.) work unchanged. We expect a single key "llm_credential_id"
    # holding the UUID of a credential profile owned by the authenticated user.
    metadata: dict[str, str] | None = None

    @field_validator("messages")
    @classmethod
    def _cap_messages(cls, v: list[ChatMessage]) -> list[ChatMessage]:
        """Bound conversation length to prevent oversized-payload DoS."""
        if len(v) > security_settings.CHAT_MAX_MESSAGES:
            raise ValueError(
                f"too many messages: {len(v)} exceeds the maximum of "
                f"{security_settings.CHAT_MAX_MESSAGES}"
            )
        return v

    @field_validator("metadata")
    @classmethod
    def _cap_metadata(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        """Bound metadata so it cannot be used as an arbitrary data sink."""
        if not v:
            return v
        if len(v) > security_settings.CHAT_MAX_METADATA_KEYS:
            raise ValueError(
                f"too many metadata keys: {len(v)} exceeds the maximum of "
                f"{security_settings.CHAT_MAX_METADATA_KEYS}"
            )
        limit = security_settings.CHAT_MAX_METADATA_VALUE_CHARS
        for key, value in v.items():
            if value is not None and len(value) > limit:
                raise ValueError(
                    f"metadata value for '{key}' exceeds the maximum of {limit} characters"
                )
        return v


# --- Non-streaming response schemas ---


class Usage(BaseModel):
    """Token usage statistics."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class Choice(BaseModel):
    """A single completion choice."""

    index: int = 0
    message: ChatMessage
    finish_reason: str | None = None  # stop | tool_calls | length


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage | None = None
    system_fingerprint: str | None = None


# --- Streaming response schemas ---


class FunctionCallDelta(BaseModel):
    """Incremental function call data in a stream chunk."""

    name: str | None = None
    arguments: str | None = None


class ToolCallDelta(BaseModel):
    """Incremental tool call data in a stream chunk."""

    index: int
    id: str | None = None
    type: str | None = None
    function: FunctionCallDelta | None = None


class ChatMessageDelta(BaseModel):
    """Incremental message data in a stream chunk."""

    role: str | None = None
    content: str | None = None
    tool_calls: list[ToolCallDelta] | None = None
    agent_event: AgentEventDelta | None = None  # Petri Net Sim extension


class ChunkChoice(BaseModel):
    """A single choice within a stream chunk."""

    index: int = 0
    delta: ChatMessageDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    """OpenAI-compatible streaming chunk."""

    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChunkChoice]
    usage: Usage | None = None
    system_fingerprint: str | None = None
    session_id: str | None = None      # Petri Net Sim extension — backend session fingerprint
    snapshot_id: str | None = None     # Petri Net Sim extension — net snapshot UUID for this turn


# --- Models endpoint schemas ---


class ModelObject(BaseModel):
    """A single model entry."""

    id: str
    object: str = "model"
    created: int
    owned_by: str


class ModelListResponse(BaseModel):
    """Response for GET /v1/models."""

    object: str = "list"
    data: list[ModelObject]


# --- Error schemas ---


class OpenAIErrorDetail(BaseModel):
    """Error detail in OpenAI format."""

    message: str
    type: str = "invalid_request_error"
    param: str | None = None
    code: str | None = None


class OpenAIErrorResponse(BaseModel):
    """OpenAI-compatible error response."""

    error: OpenAIErrorDetail
