"""Tool execution node for LangGraph workflow.

Every Petri Net tool call the LLM makes now resolves through the shared
agent_toolkit catalog (src/services/petri/agent_toolkit/): one
PetriNetSession is rehydrated from state's net_data, each tool_call in the
batch resolves its ToolSpec by name and calls spec.operation(session,
**args), and the session is re-serialized into net_data once the whole
batch has run. This replaces the previous ~40 hand-written
`_handle_*`/`_generic_add_action` functions and their own copy of
time-unit normalization -- every op_* function in operations.py already
does its own time-unit conversion and its own "no network yet" guard, so
there is nothing left for this dispatcher to duplicate.

create_network and show_chart are not catalog entries (create_network's
return shape and show_chart's chart-only behavior don't fit
`str | ToolError`), so they keep their own special-case branches here, same
as before.
"""

import json

from langchain_core.messages import ToolMessage

from src.core.logger import get_logger
from src.services.agent.state import AgentState
from src.services.petri.agent_toolkit.catalog import build_catalog
from src.services.petri.agent_toolkit.errors import ToolError
from src.services.agent.nodes.chat_node import (
    DEFAULT_LAYOUT_DIRECTION,
    DEFAULT_NET_STYLE,
)
from src.services.petri.session import PetriNetSession

logger = get_logger()

_EXPORT_READY_MESSAGE = (
    "PNML export ready. The server will attach a download link to your reply. "
    "Do NOT paste the XML into chat - just briefly confirm to the user."
)

#: Tolerant aliases for a tool name the LLM might still emit after a
#: catalog rename. export_pnml is the one unified name (matching MCP); the
#: chat surface used to expose it as "export_network" (see git history of
#: this module) and a model that saw that name in an earlier turn, or was
#: simply trained on the older convention, may still call it. Resolved to
#: the real catalog name before dispatch, so the ToolMessage reported back
#: still carries whichever name the LLM actually used.
_TOOL_NAME_ALIASES: dict[str, str] = {
    "export_network": "export_pnml",
}

# Registry of non-Petri tools available to the workflow (currently just the
# "echo" tool below, used in tests). Unrelated to the Petri Net catalog.
_tool_registry: dict[str, callable] = {}


def register_tool(name: str, func: callable) -> None:
    """Register a tool for use in the workflow."""
    _tool_registry[name] = func
    logger.info(f"Registered tool: {name}")


def get_available_tools() -> list[str]:
    """Get list of available tool names."""
    return list(_tool_registry.keys())


def _render_chart(tool_args: dict) -> str:
    """Package show_chart's args into the JSON blob the frontend's ChartRenderer expects."""
    data_json = tool_args.get("data_json", "[]")
    data = json.loads(data_json) if isinstance(data_json, str) else data_json
    return json.dumps({
        "type": tool_args.get("chart_type", "bar"),
        "title": tool_args.get("title", ""),
        "data": data,
        "xKey": tool_args.get("x_key", "name"),
        "yKey": tool_args.get("y_key", "value"),
    })


async def tool_node(state: AgentState) -> dict:  # NOSONAR
    """Execute every tool call on the last AI message."""
    logger.debug(f"Tool node processing for conversation {state['conversation_id']}")

    messages = list(state["messages"])

    if not messages:
        return {
            "error": "No messages to process",
            "next_action": "end",
        }

    last_message = messages[-1]

    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        logger.debug("No tool calls in last message")
        return {"next_action": "respond"}

    tool_messages: list[ToolMessage] = []
    # One session for the whole batch, not one per tool call: this is what
    # lets a run_simulation call's result be visible to a get_simulation_results
    # call immediately after it in the same turn -- PetriNetSession keeps that
    # result out of net_data on purpose (see session.py), so only the same
    # session instance carries it forward.
    # auto_optimize=False restores the pre-catalog chat behavior: nothing
    # but an explicit optimize_network call ever fuses Transfer transitions
    # on this surface (see operations.py's documented-divergence list and
    # PetriNetSession's own docstring). MCP's session store leaves the
    # session-level switch at its default (True) instead.
    source_net = dict(state.get("net_data", {}) or {})
    pending_downloads = list(source_net.pop("_pending_downloads", []))
    source_net.pop("_last_pnml_export", None)
    training_archive = source_net.pop("_training_archive_base64", None)
    interactive_runs = source_net.pop("_training_interactive_runs", [])
    session = PetriNetSession.from_net_data(source_net, auto_optimize=False)
    if training_archive:
        from src.api.versions.v1.routers.training import decode_archive
        session._training_archive = decode_archive(training_archive)
    session._training_interactive_runs = interactive_runs
    # In Object mode this turn's net is destined to be cut into one
    # Petri-object per pattern, and the seams it gets cut along are exactly
    # the hand-off places an optimize_network call would fuse away first.
    # Protecting them costs nothing (a pattern's own insides are designed,
    # not redundant) and is what keeps the model separable no matter what
    # order the agent calls its tools in. See PetriNetSession.optimize.
    session.protect_pattern_ports = (
        state.get("context", {}).get("net_style", DEFAULT_NET_STYLE) == "object"
    )
    catalog = build_catalog()
    pending_pnml_export: str | None = None

    for tool_call in last_message.tool_calls:
        tool_name = tool_call.get("name", "")
        tool_id = tool_call.get("id", "")
        tool_args = tool_call.get("args", {})
        catalog_name = _TOOL_NAME_ALIASES.get(tool_name, tool_name)

        logger.debug(f"[AGENT-TOOL-CALL] name={tool_name} id={tool_id} raw_args={tool_args}")

        status: str | None = None

        try:
            if tool_name == "create_network":
                name = tool_args.get("name", "PetriNet")
                session.create_network(name)
                result = f"Created new empty network '{name}'"

            elif tool_name == "show_chart":
                result = _render_chart(tool_args)

            elif catalog_name in catalog:
                spec = catalog[catalog_name]
                # Filter unknown kwargs before dispatch: spec.operation(...)
                # is plain keyword-argument binding, and a hallucinated
                # parameter name would otherwise reach it as a raw
                # TypeError naming the internal op_* function instead of a
                # clean ToolMessage.
                known_args, dropped = spec.filter_kwargs(tool_args)
                if spec.name in {"export_training_data", "export_training_review"} and "conversation" not in known_args:
                    from src.services.llm.message_content import content_to_text
                    known_args["conversation"] = [
                        {"role": "user" if message.type == "human" else "assistant", "content": content_to_text(message.content)}
                        for message in state.get("messages", [])
                        if message.type in {"human", "ai"} and message.content
                    ]
                    session._export_conversation_origin = "application"
                if spec.name in {"export_training_data", "export_image", "export_training_review", "training_bundle_image", "run_training_simulation", "open_training_bundle", "inspect_training_bundle", "compare_training_revisions"}:
                    from starlette.concurrency import run_in_threadpool
                    op_result = await run_in_threadpool(spec.operation, session, **known_args)
                else:
                    op_result = spec.operation(session, **known_args)
                if isinstance(op_result, ToolError):
                    result = op_result.message
                    status = "error"
                elif spec.name in {"export_training_data", "export_image", "export_training_review", "training_bundle_image"}:
                    pending_downloads.append(json.loads(op_result))
                    result = "Export ready. The application will provide the download link."
                elif spec.name == "export_pnml":
                    # Chat's file-download convention (unlike MCP, which can
                    # just return the XML as the tool result): the raw PNML
                    # never reaches chat content. It rides net_data's
                    # _last_pnml_export side channel; openai_chat_service
                    # picks that up, stores it as a file, and injects a
                    # download link into the reply instead.
                    pending_pnml_export = op_result
                    result = _EXPORT_READY_MESSAGE
                else:
                    result = op_result
                if dropped and status != "error":
                    result = f"{result} Ignored unknown parameter(s): {', '.join(dropped)}."

            elif tool_name in _tool_registry:
                result = await _tool_registry[tool_name](**tool_args)

            else:
                result = f"Unknown tool: '{tool_name}'"
                status = "error"
                logger.warning(result)

            message_kwargs = {"content": str(result), "tool_call_id": tool_id, "name": tool_name}
            if status:
                message_kwargs["status"] = status
            tool_messages.append(ToolMessage(**message_kwargs))

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            tool_messages.append(
                ToolMessage(
                    content=f"Error: {e}",
                    tool_call_id=tool_id,
                    name=tool_name,
                    status="error",
                )
            )

    # The build direction belongs to the user, not to the model, so it is
    # re-asserted here rather than left to whatever the tool batch did. This
    # runs even when the batch failed outright: the direction describes the
    # net that exists now, not the calls that were attempted.
    layout_direction = state.get("context", {}).get(
        "layout_direction", DEFAULT_LAYOUT_DIRECTION
    )
    try:
        relaid = session.apply_layout_direction(layout_direction)
        if relaid:
            logger.debug(
                f"[AGENT-LAYOUT] direction={layout_direction} relaid={relaid}"
            )
    except Exception as exc:
        # Never lose a completed tool batch over a layout pass: the net is
        # correct either way, it just keeps the direction it already had.
        logger.warning(f"Could not apply layout direction {layout_direction!r}: {exc}")

    try:
        net_data = session.to_net_data()
    except Exception as exc:
        # A serialization failure here used to propagate straight out of
        # tool_node, discarding every tool_messages entry the loop above
        # already built (every individual tool call could have succeeded)
        # and silently dropping the whole chat turn -- the caller never
        # even learns a tool ran. Recover instead: keep the PREVIOUS
        # net_data (this batch's changes did not durably save, so pretending
        # otherwise would desync net_data from what op_* calls actually
        # reported) and fold the failure into the batch's own result
        # instead of raising a brand-new ToolMessage: LangGraph's
        # "respond" node re-submits `messages` to the model as real
        # conversation history, where a ToolMessage's tool_call_id MUST
        # match a tool_call the immediately preceding AIMessage actually
        # made, or the provider rejects the whole request -- there is no
        # such id for "the batch's save step" itself to reuse safely, so
        # the last real tool call's own ToolMessage carries this note
        # instead of a synthetic sibling.
        logger.error(f"Failed to serialize net_data after tool batch: {exc}", exc_info=True)
        net_data = state.get("net_data", {}) or {}
        if tool_messages:
            last = tool_messages[-1]
            tool_messages[-1] = ToolMessage(
                content=(
                    f"{last.content}\n\n"
                    f"Error: failed to save the network changes from this batch ({exc}). "
                    "Reverted to the last saved state; please retry."
                ),
                tool_call_id=last.tool_call_id,
                name=last.name,
                status="error",
            )
    if pending_downloads:
        net_data["_pending_downloads"] = pending_downloads
    if getattr(session, "_training_archive", None):
        import base64
        net_data["_training_archive_base64"] = base64.b64encode(session._training_archive).decode("ascii")
        net_data["_training_interactive_runs"] = getattr(session, "_training_interactive_runs", [])
    if pending_pnml_export is not None:
        net_data["_last_pnml_export"] = pending_pnml_export

    return {
        "messages": tool_messages,
        "next_action": "respond",
        "error": None,
        "net_data": net_data,
    }


async def echo_tool(message: str) -> str:
    """Simple echo tool for testing."""
    return f"Echo: {message}"


register_tool("echo", echo_tool)
