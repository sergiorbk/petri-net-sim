"""Agent state definition for LangGraph workflow."""

from typing import Annotated, Any, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """
    State schema for the chat agent workflow.

    Attributes:
        messages: Conversation messages with automatic merging
        conversation_id: UUID of the current conversation
        user_id: User identifier
        next_action: Next action to take (respond, use_tool, end)
        context: Additional context dictionary
        token_count: Current token count
        error: Error message if any
        net_data: Serialized PetriNet being built (dict from model_dump())
        credentials: Resolved LLMCredentials value object passed in by the
            chat completions router. The chat node uses these to obtain a
            per-user provider client; threading them through state (rather
            than reaching into a global) is what makes BYOK isolation work.
    """

    messages: Annotated[Sequence[BaseMessage], add_messages]
    conversation_id: str
    user_id: str
    next_action: str
    context: dict[str, Any]
    token_count: int
    error: str | None
    net_data: dict[str, Any]
    credentials: Any  # LLMCredentials — typed Any to avoid LangGraph TypedDict-import cycle


def create_initial_state(
    conversation_id: str,
    user_id: str,
    credentials: Any,
    messages: list[BaseMessage] | None = None,
    context: dict[str, Any] | None = None,
) -> AgentState:
    """
    Create initial agent state.

    Args:
        conversation_id: Conversation UUID as string
        user_id: User identifier
        credentials: LLMCredentials resolved by the request layer
        messages: Optional initial messages
        context: Optional initial context

    Returns:
        Initial AgentState
    """
    return AgentState(
        messages=messages or [],
        conversation_id=conversation_id,
        user_id=user_id,
        next_action="respond",
        context=context or {},
        token_count=0,
        error=None,
        net_data={},
        credentials=credentials,
    )
