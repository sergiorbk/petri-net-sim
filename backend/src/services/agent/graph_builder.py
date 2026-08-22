"""LangGraph workflow builder."""

from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.core.logger import get_logger
from src.services.agent.nodes.chat_node import chat_node
from src.services.agent.nodes.router_node import router_node
from src.services.agent.nodes.tool_node import tool_node
from src.services.agent.state import AgentState

logger = get_logger()


class GraphBuilder:
    """
    Builder for LangGraph chat workflow.

    Creates a state graph with the following structure:

    [Entry] -> process_input -> route -+-> respond -> [END]
                                  ^    |
                                  |    +-> execute_tool -+
                                  |                      |
                                  +----------------------+
    """

    def __init__(self):
        self._graph: CompiledStateGraph | None = None
        self._built = False

    def build(self) -> CompiledStateGraph:
        """
        Build the LangGraph workflow.

        Returns:
            Compiled state graph
        """
        if self._built and self._graph:
            return self._graph

        logger.info("Building LangGraph workflow...")

        # Create state graph
        workflow = StateGraph(AgentState)

        # Add nodes
        workflow.add_node("respond", chat_node)
        workflow.add_node("execute_tool", tool_node)

        # Set entry point
        workflow.set_entry_point("respond")

        # Add conditional edges from respond
        workflow.add_conditional_edges(
            "respond",
            router_node,
            {
                "respond": "respond",
                "execute_tool": "execute_tool",
                "end": END,
            },
        )

        # Add edge from tool execution back to router
        workflow.add_conditional_edges(
            "execute_tool",
            router_node,
            {
                "respond": "respond",
                "execute_tool": "execute_tool",
                "end": END,
            },
        )

        # Compile the graph
        self._graph = workflow.compile()
        self._built = True

        logger.info("LangGraph workflow built successfully")
        return self._graph

    def build_with_checkpointer(self, checkpointer) -> CompiledStateGraph:
        """
        Build the LangGraph workflow with checkpointing.

        Args:
            checkpointer: LangGraph checkpointer for state persistence

        Returns:
            Compiled state graph with checkpointing
        """
        logger.info("Building LangGraph workflow with checkpointing...")

        # Create state graph
        workflow = StateGraph(AgentState)

        # Add nodes
        workflow.add_node("respond", chat_node)
        workflow.add_node("execute_tool", tool_node)

        # Set entry point
        workflow.set_entry_point("respond")

        # Add conditional edges from respond
        workflow.add_conditional_edges(
            "respond",
            router_node,
            {
                "respond": "respond",
                "execute_tool": "execute_tool",
                "end": END,
            },
        )

        # Add edge from tool execution back to router
        workflow.add_conditional_edges(
            "execute_tool",
            router_node,
            {
                "respond": "respond",
                "execute_tool": "execute_tool",
                "end": END,
            },
        )

        # Compile with checkpointer
        graph = workflow.compile(checkpointer=checkpointer)

        logger.info("LangGraph workflow with checkpointing built successfully")
        return graph

    @property
    def graph(self) -> CompiledStateGraph | None:
        """Get the compiled graph."""
        return self._graph


# Global graph builder instance
_graph_builder: GraphBuilder | None = None


def get_graph_builder() -> GraphBuilder:
    """Get or create the global graph builder instance."""
    global _graph_builder
    if _graph_builder is None:
        _graph_builder = GraphBuilder()
    return _graph_builder


def get_graph() -> CompiledStateGraph:
    """Get the compiled graph."""
    builder = get_graph_builder()
    return builder.build()


async def get_graph_with_checkpointing() -> CompiledStateGraph:
    """Get the compiled graph with checkpointing enabled."""
    from src.services.agent.checkpointer import get_checkpointer

    builder = get_graph_builder()
    checkpointer = await get_checkpointer()
    return builder.build_with_checkpointer(checkpointer)
