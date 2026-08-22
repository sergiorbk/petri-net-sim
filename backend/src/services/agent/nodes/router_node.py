"""Router node for decision making in LangGraph workflow."""

from src.core.logger import get_logger
from src.services.agent.state import AgentState

logger = get_logger()


def router_node(state: AgentState) -> str:
    """
    Route to the next node based on current state.

    This is a conditional edge function that determines
    the next step in the workflow.

    Args:
        state: Current agent state

    Returns:
        Next node name: "respond", "execute_tool", or "end"
    """
    from langchain_core.messages import AIMessage, ToolMessage

    # Check for errors
    if state.get("error"):
        logger.debug("Router: error detected, routing to end")
        return "end"

    # Get next action from state - this is the PRIMARY routing signal
    next_action = state.get("next_action", "respond")

    # If next_action explicitly says "end", respect it
    if next_action == "end":
        logger.debug("Router: next_action=end, routing to end")
        return "end"

    # Check last message for tool calls
    # Only route to execute_tool if the LAST message is an AIMessage with tool_calls
    messages = state.get("messages", [])
    if messages:
        last_message = messages[-1]
        # Only check AIMessage (not ToolMessage) for tool_calls
        if isinstance(last_message, AIMessage):
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                logger.debug("Router: AIMessage with tool calls, routing to execute_tool")
                return "execute_tool"

    # Route based on next_action
    if next_action == "use_tool":
        logger.debug("Router: next_action=use_tool, routing to execute_tool")
        return "execute_tool"
    else:
        logger.debug("Router: routing to respond")
        return "respond"


def should_continue(state: AgentState) -> bool:
    """
    Determine if the workflow should continue.

    Args:
        state: Current agent state

    Returns:
        True if workflow should continue
    """
    # Stop on error
    if state.get("error"):
        return False

    # Stop if next action is end
    if state.get("next_action") == "end":
        return False

    return True
