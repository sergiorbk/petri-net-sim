"""Chat node for LLM response generation."""

from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage

from src.core.agent_config import agent_settings
from src.core.logger import get_logger
from src.services.agent.state import AgentState
from src.services.agent.tools import PETRI_TOOLS
from src.services.llm import get_llm_factory
from src.services.llm.credentials import LLMCredentials
from src.services.llm.message_content import content_to_text
from src.services.llm.providers.base import BaseLLMProvider
from src.services.llm.token_manager import get_token_manager

logger = get_logger()

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "petri_net_expert.md"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

# Per-turn override of the base prompt's PETRI-OBJECTS section (which
# defaults to "flat unless genuinely separate modules"), keyed by the
# chat workbench's net-style toggle -- see ChatWorkbench's NetStyleToggle
# and openai_chat_service._build_state's net_style param for how a value
# gets here (AgentState.context["net_style"]). Kept OUT of SYSTEM_PROMPT
# itself so the cached prefix (see _build_system_message) never varies.
_NET_STYLE_NOTES = {
    "object": (
        "NET STYLE FOR THIS TURN: Petri-object (composed model). HARD "
        "REQUIREMENT that OVERRIDES the PETRI-OBJECTS section above -- "
        "including its \"a single linear flow (Generator -> machines -> "
        "Exit) stays flat, do not create an object for it\" example. That "
        "example does NOT apply in this mode; ignore it completely, even "
        "when the request is exactly that simple.\n"
        "1. ONE OBJECT PER LOGICAL BLOCK. A generator is a block; each "
        "machine, queue or router is a block; each exit/counter is a "
        "block. \"Generator, processor, counter\" is THREE objects, not "
        "one.\n"
        "2. NEVER put the whole model in a single object. An object named "
        "after the model, or after the net, is wrong: that is a flat net "
        "with one frame drawn round it, which says nothing a flat net did "
        "not already say. Build one object for everything ONLY if the user "
        "explicitly asked for exactly that.\n"
        "3. Per block: call create_object(name) (which also makes that "
        "object active), build that block with the usual add_*/pattern "
        "tools, then move on to the next block. Never build directly in "
        "the free pool in this mode.\n"
        "4. NEST when a block is itself made of blocks: a line made of "
        "stations, a terminal made of desks and gates, a cell made of "
        "machines. Create the outer object first, then pass "
        "parent=<outer name> when creating each inner one -- the outer "
        "object MUST already exist before any child names it, and if a "
        "parent turns out to be missing, create it and retry rather than "
        "giving the nesting up. An object can hold plain places/transitions "
        "AND child objects at once, so the outer one may keep what belongs "
        "to it directly (a shared buffer) alongside its children. Do not "
        "flatten a hierarchy the user described into one row of siblings.\n"
        "5. Wire objects together with link_objects "
        "(placeFusion/transitionToPlace) once every side exists. Do NOT "
        "join two objects by adding a pass-through transition between "
        "them: a fused place says the same thing with nothing standing "
        "in between. Then call validate_model (not validate_net -- that "
        "only checks one object).\n"
        "6. Do NOT call optimize_network in this mode. It fuses the place "
        "where one block hands off to the next, and that place is the "
        "boundary between two objects -- once it is gone the model cannot "
        "be separated any more.\n"
        "A response containing zero create_object calls is WRONG in this "
        "mode, no matter how small or simple the requested system sounds, "
        "and so is one containing a single create_object call for a model "
        "that has more than one block. This mirrors the ISO/IEC 15909 "
        "module convention the editor's own object frames follow."
    ),
    "classical": (
        "NET STYLE FOR THIS TURN: classical flat net. Do NOT call "
        "create_object or any object/link tool -- build directly in the "
        "free pool with the usual add_*/pattern tools, exactly as a "
        "session that never touches objects always has."
    ),
}
DEFAULT_NET_STYLE = "object"

# Which way a generated net flows, straight through from the workbench's
# DirectionToggle. "LR" grows the net left to right with parallel steps
# stacked underneath each other; "TB" is the same layout turned a quarter
# turn. Matches _resolve_layout_direction's own default in the chat router.
DEFAULT_LAYOUT_DIRECTION = "LR"

# The layout direction is the USER's choice, not the model's, and it is
# enforced after every tool batch (tool_node's apply_layout_direction call)
# regardless of what the model did. This note exists so the model does not
# waste a tool call fighting an override it cannot win, and so it does not
# reach for the manual-placement tools, whose whole effect is discarded the
# moment the direction is re-applied.
_LAYOUT_DIRECTION_NOTE = (
    "LAYOUT FOR THIS TURN: the user has already chosen the build direction "
    "({direction}) and it is applied for you after your tools run. Do NOT "
    "call set_layout_direction or auto_layout, and do NOT place elements by "
    "hand with set_positions, move_elements_by or arrange_patterns. "
    "Coordinates are computed by the layout engine, never by you."
)


def _build_system_message(
    provider: BaseLLMProvider,
    net_style: str = DEFAULT_NET_STYLE,
    layout_direction: str = DEFAULT_LAYOUT_DIRECTION,
) -> SystemMessage:
    """
    Build the system message, enabling Anthropic prompt caching when applicable.

    For Anthropic with caching enabled, the system prompt (and the tool
    schemas bound just before it by LangChain) are marked as a cache
    breakpoint so repeated `respond` turns inside a single tool loop
    reuse them without re-billing input tokens. The net-style note is
    appended as a SEPARATE, uncached block after that breakpoint: prompt
    caching is prefix-based, so a value that varies per conversation here
    never invalidates the cached SYSTEM_PROMPT prefix.
    """
    note = "\n\n".join([
        _NET_STYLE_NOTES.get(net_style, _NET_STYLE_NOTES[DEFAULT_NET_STYLE]),
        _LAYOUT_DIRECTION_NOTE.format(direction=layout_direction),
    ])
    if (
        provider.provider_name == "anthropic"
        and agent_settings.ANTHROPIC_PROMPT_CACHING
    ):
        return SystemMessage(
            content=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": note},
            ]
        )
    return SystemMessage(content=f"{SYSTEM_PROMPT}\n\n{note}")


def _credentials_from_state(state: AgentState) -> LLMCredentials:
    """
    Extract LLMCredentials from agent state.

    The chat completions router resolves credentials before invoking the
    graph and threads them through state. Missing credentials are a
    programming error — every entry into the graph should set them.
    """
    creds = state.get("credentials")
    if creds is None:
        raise RuntimeError(
            "Agent state is missing 'credentials'. The chat completions "
            "layer must resolve a credential set before invoking the graph."
        )
    if not isinstance(creds, LLMCredentials):
        raise TypeError(
            f"AgentState.credentials must be LLMCredentials, got {type(creds).__name__}"
        )
    return creds


def _nothing_to_say(response: Any, content: Any, model: str) -> dict:
    """Turn a reply with no text and no tool calls into something the caller
    can act on.

    Such a reply is a successful API call that said nothing usable, and the
    node used to pass it on as an ordinary empty answer: the stream closed
    with no content and no error, which reaches the user as a request that
    simply never came back. Whatever the cause, silence is the one response
    that cannot be acted on.

    The commonest cause is the output budget: a model that reasons before
    answering spends the same allowance on thinking, and once it is gone
    there is nothing left to say the answer with. That case is named
    explicitly, because the fix is a setting rather than a retry.
    """
    metadata = getattr(response, "response_metadata", None) or {}
    stop_reason = metadata.get("stop_reason") or metadata.get("finish_reason")
    kinds = (
        sorted({b.get("type", "?") for b in content if isinstance(b, dict)})
        if isinstance(content, list)
        else [type(content).__name__]
    )
    logger.warning(
        "Empty reply from %s: stop_reason=%s, content blocks=%s, usage=%s",
        model, stop_reason, kinds, getattr(response, "usage_metadata", None),
    )
    if stop_reason == "max_tokens":
        message = (
            f"{model} used its whole output allowance before answering "
            "(stop_reason=max_tokens), so the reply came back empty. Raise "
            "AGENT_LLM_MAX_TOKENS, or set a larger max_tokens on this "
            "credential profile."
        )
    else:
        message = (
            f"{model} returned no text and asked for no tools "
            f"(stop_reason={stop_reason}). Nothing was generated to show."
        )
    return {"error": message, "next_action": "end"}


async def chat_node(state: AgentState) -> dict:
    """
    Generate LLM response based on conversation history.

    Args:
        state: Current agent state (must include resolved credentials)

    Returns:
        State update with new AI message
    """
    logger.debug(f"Chat node processing for conversation {state['conversation_id']}")

    try:
        credentials = _credentials_from_state(state)
        factory = get_llm_factory()
        provider = await factory.for_credentials(credentials)
        token_manager = get_token_manager()

        messages = list(state["messages"])
        if not messages:
            logger.warning("No messages in state")
            return {
                "error": "No messages to process",
                "next_action": "end",
            }

        context = state.get("context", {})
        net_style = context.get("net_style", DEFAULT_NET_STYLE)
        layout_direction = context.get("layout_direction", DEFAULT_LAYOUT_DIRECTION)
        system_msg = _build_system_message(provider, net_style, layout_direction)
        full_messages = [system_msg] + messages

        llm = provider.get_chat_model()
        llm_with_tools = llm.bind_tools(PETRI_TOOLS)

        try:
            response = await llm_with_tools.ainvoke(full_messages)
        except Exception as exc:
            # Some refusals are answerable: asking Anthropic for more output
            # room than a model allows is refused WITH the number it allows,
            # so the provider can take that number and the same request then
            # goes through. Providers that cannot adapt say so and the error
            # travels on untouched -- this is a second chance, not a retry
            # loop, and it is offered exactly once.
            if not provider.adapt_to_error(exc):
                raise
            llm_with_tools = provider.get_chat_model().bind_tools(PETRI_TOOLS)
            response = await llm_with_tools.ainvoke(full_messages)

        if hasattr(response, "tool_calls") and response.tool_calls:
            logger.debug(f"LLM wants to call {len(response.tool_calls)} tools")
            return {
                "messages": [response],
                "next_action": "use_tool",
                "error": None,
            }

        content = response.content if hasattr(response, "content") else str(response)
        # Count the TEXT, not the raw content: a newer Claude model answers
        # with a list of blocks, and handing that to tiktoken raised
        # "expected string or buffer" AFTER a successful API call, so the
        # turn died with a reply already paid for. The message itself keeps
        # its blocks -- they are what the model actually said.
        text = content_to_text(content)
        if not text:
            return _nothing_to_say(response, content, provider.model_name)
        token_count = token_manager.count_tokens(text)

        logger.debug(
            f"Generated response with {token_count} tokens "
            f"(model={provider.model_name})"
        )

        return {
            "messages": [AIMessage(content=content)],
            "token_count": state["token_count"] + token_count,
            "next_action": "end",
            "error": None,
        }

    except Exception as e:
        logger.error(f"Error in chat node: {e}")
        return {
            "error": str(e),
            "next_action": "end",
        }


async def chat_node_stream(state: AgentState):
    """
    Stream LLM response based on conversation history.

    This is an async generator that yields tokens.

    Args:
        state: Current agent state

    Yields:
        Token chunks
    """
    logger.debug(
        f"Chat node streaming for conversation {state['conversation_id']}"
    )

    try:
        credentials = _credentials_from_state(state)
        factory = get_llm_factory()
        provider = await factory.for_credentials(credentials)

        messages = list(state["messages"])
        if not messages:
            yield {"error": "No messages to process"}
            return

        async for token in provider.stream(messages):
            yield {"token": token}

    except Exception as e:
        logger.error(f"Error in chat node stream: {e}")
        yield {"error": str(e)}
