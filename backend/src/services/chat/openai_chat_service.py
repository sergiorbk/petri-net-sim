"""OpenAI-compatible chat service bridging the OpenAI protocol to LangGraph agent."""

import hashlib
import json
import re
import time
import uuid
from typing import Any, AsyncIterator, Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.openai_api.v1.schemas.chat import (
    AgentEventDelta,
    ChatCompletionChunk,
    ChatCompletionResponse,
    ChatMessage,
    ChatMessageDelta,
    Choice,
    ChunkChoice,
    Usage,
)
from src.core.config import settings
from src.core.logger import get_logger
from src.services.agent.graph_builder import get_graph
from src.services.agent.nodes.chat_node import DEFAULT_LAYOUT_DIRECTION, DEFAULT_NET_STYLE
from src.services.agent.state import AgentState
from src.services.petri.session import PetriNetSession
from src.services.chat.file_service import FileService
from src.services.chat.memory_service import MemoryService
from src.services.auth.jwt_service import get_jwt_service
from src.services.chat.session_service import SessionService
from src.services.llm.credentials_resolver import ResolvedCredentials
from src.services.llm.message_content import content_to_text
from src.services.llm.token_manager import get_token_manager

logger = get_logger()

MODEL_ID = "petri-net-sim"


def _net_structure_hash(net_data: dict) -> str:
    """Hash the structural content of a net, ignoring internal tracking keys."""
    clean = {k: v for k, v in net_data.items() if not k.startswith("_")}
    return hashlib.sha256(
        json.dumps(clean, sort_keys=True, default=str).encode()
    ).hexdigest()
PNML_PATTERN = re.compile(r"<\?xml.*<pnml", re.DOTALL)


def _ensure_object_style(net_data: dict, net_style: str) -> dict:
    """Deterministic fallback for Object net-style mode: the agent is
    instructed (chat_node.py's _NET_STYLE_NOTES) to give every logical
    block its own Petri-object, but that instruction is not 100% reliable
    on a smaller/faster model -- a turn can still come back built entirely
    flat in the free pool. If so, draw the frames after the fact via
    PetriNetSession.ensure_patterns_in_objects, which frames each PATTERN
    the agent used, since those are the logical blocks and the builder
    already knows their names and membership.

    Deliberately not "wrap it all in one object": a single frame around
    the whole net says nothing a flat net did not, so a net with no
    patterns to separate is left flat.

    Returns net_data UNCHANGED (the same object) when there's nothing to
    frame -- callers that compare by identity (net_changed checks in the
    streaming path) still work correctly.
    """
    if net_style != "object" or not net_data:
        return net_data
    # _last_pnml_export is a non-standard side-channel key merged into
    # net_data by tool_node.py, not a PetriNet/ComposedModel field --
    # PetriNetSession.from_net_data would reject it as an unexpected kwarg.
    pnml_export = net_data.get("_last_pnml_export")
    pending_downloads = net_data.get("_pending_downloads")
    clean = {k: v for k, v in net_data.items() if k not in {"_last_pnml_export", "_pending_downloads"}}
    session = PetriNetSession.from_net_data(clean)
    if not session.ensure_patterns_in_objects():
        return net_data
    wrapped = session.to_net_data()
    if pending_downloads:
        wrapped["_pending_downloads"] = pending_downloads
    if pnml_export is not None:
        wrapped["_last_pnml_export"] = pnml_export
    return wrapped


class OpenAIChatService:
    """
    Core service that translates OpenAI Chat Completions requests into
    LangGraph agent invocations and formats the results back.
    """

    def __init__(self, session: AsyncSession):
        self._session = session
        self._session_service = SessionService(session)
        self._file_service = FileService(session)
        self._memory_service = MemoryService()
        self._token_manager = get_token_manager()
        self._graph = get_graph()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: list[ChatMessage],
        user_id: uuid.UUID,
        resolved: ResolvedCredentials,
        api_key_hash: str | None = None,
        max_tokens: int | None = None,
        net_style: str = DEFAULT_NET_STYLE,
        layout_direction: str = DEFAULT_LAYOUT_DIRECTION,
        recursion_limit: int | None = None,
    ) -> ChatCompletionResponse:
        """Non-streaming chat completion."""
        completion_id = _make_completion_id()
        created = int(time.time())
        # Read from settings at call time, not baked into the default
        # parameter value -- settings.AGENT_RECURSION_LIMIT is patched
        # directly in tests (a module-import-time default would miss that).
        recursion_limit = recursion_limit or settings.AGENT_RECURSION_LIMIT

        # Session handling
        session_id, net_data = await self._resolve_session(messages, user_id, api_key_hash)
        await self._bind_session_to_credential(session_id, resolved)

        # Auto-title from first user message
        first_content = SessionService.extract_first_user_content(
            [m.model_dump() for m in messages]
        )
        if first_content:
            title = first_content[:100] + ("..." if len(first_content) > 100 else "")
            await self._session_service.set_title_if_empty(session_id, title)

        # Convert messages and run agent
        lc_messages = self._openai_to_langchain(messages)
        lc_messages = self._memory_service.apply_context_window(lc_messages)

        state = self._build_state(
            session_id,
            user_id,
            lc_messages,
            net_data,
            resolved.credentials,
            net_style,
            layout_direction,
        )
        result = await self._graph.ainvoke(
            state, config={"recursion_limit": recursion_limit}
        )

        # Collect new messages produced by the agent
        original_count = len(lc_messages)
        all_result_messages: list[BaseMessage] = list(result.get("messages", []))
        new_messages = all_result_messages[original_count:]

        # Build the OpenAI response message
        response_message = self._build_response_message(new_messages)

        # Persist net_data and extract any PNML export side-channel
        new_net_data = result.get("net_data", {}) or {}
        # Only the fallback wrap needs to know THIS turn actually touched
        # net_data -- a pure Q&A turn must never silently restructure
        # whatever net a PRIOR, possibly differently-styled turn left behind.
        if _net_structure_hash(new_net_data) != _net_structure_hash(net_data):
            new_net_data = _ensure_object_style(new_net_data, net_style)
        downloads = new_net_data.pop("_pending_downloads", [])
        pnml_content = new_net_data.pop("_last_pnml_export", None)
        await self._session_service.save_net_data(session_id, new_net_data)

        if pnml_content:
            response_message = await self._inject_pnml_download(
                response_message, pnml_content, session_id, user_id
            )

        for download in downloads:
            response_message = response_message.model_copy(update={
                "content": (response_message.content or "") + await self._binary_download_link(download, session_id, user_id)
            })

        # Token usage
        prompt_tokens = self._token_manager.count_messages_tokens(lc_messages)
        completion_tokens = self._token_manager.count_tokens(
            response_message.content or ""
        )

        finish_reason = "stop"

        return ChatCompletionResponse(
            id=completion_id,
            created=created,
            model=MODEL_ID,
            choices=[
                Choice(
                    index=0,
                    message=response_message,
                    finish_reason=finish_reason,
                )
            ],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    async def complete_stream(  # NOSONAR
        self,
        messages: list[ChatMessage],
        user_id: uuid.UUID,
        resolved: ResolvedCredentials,
        api_key_hash: str | None = None,
        max_tokens: int | None = None,
        include_usage: bool = False,
        net_style: str = DEFAULT_NET_STYLE,
        layout_direction: str = DEFAULT_LAYOUT_DIRECTION,
        recursion_limit: int | None = None,
    ) -> AsyncIterator[str]:
        """Streaming chat completion yielding SSE-formatted lines."""
        completion_id = _make_completion_id()
        created = int(time.time())
        recursion_limit = recursion_limit or settings.AGENT_RECURSION_LIMIT

        session_id, net_data = await self._resolve_session(messages, user_id, api_key_hash)
        await self._bind_session_to_credential(session_id, resolved)

        # Auto-title from first user message
        first_content = SessionService.extract_first_user_content(
            [m.model_dump() for m in messages]
        )
        if first_content:
            title = first_content[:100] + ("..." if len(first_content) > 100 else "")
            await self._session_service.set_title_if_empty(session_id, title)

        lc_messages = self._openai_to_langchain(messages)
        lc_messages = self._memory_service.apply_context_window(lc_messages)

        state = self._build_state(
            session_id,
            user_id,
            lc_messages,
            net_data,
            resolved.credentials,
            net_style,
            layout_direction,
        )

        # First chunk: role announcement + session fingerprint so the UI can
        # link this stream to a backend session for net/simulate endpoints.
        yield _format_sse(ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=MODEL_ID,
            session_id=session_id,
            choices=[ChunkChoice(
                index=0,
                delta=ChatMessageDelta(role="assistant"),
            )],
        ))

        final_net_data = net_data
        initial_net_hash = _net_structure_hash(net_data)
        prompt_tokens = self._token_manager.count_messages_tokens(lc_messages)
        completion_tokens = 0

        try:
            # Two modes, not one. "updates" fires once a NODE has finished,
            # which is what carries tool calls, errors and net_data -- but it
            # also means a model that thinks for a minute and then emits six
            # tool calls delivers all six at once after a minute of nothing.
            # "messages" carries the model's own tokens as they are produced,
            # which is the only thing that can fill that minute.
            streamed = ""
            async for mode, payload in self._graph.astream(
                state,
                stream_mode=["updates", "messages"],
                config={"recursion_limit": recursion_limit},
            ):
                if mode == "messages":
                    chunk, _metadata = payload
                    token_text = _extract_text(getattr(chunk, "content", None))
                    if token_text:
                        streamed += token_text
                        completion_tokens += self._token_manager.count_tokens(token_text)
                        yield _format_sse(ChatCompletionChunk(
                            id=completion_id,
                            created=created,
                            model=MODEL_ID,
                            choices=[ChunkChoice(
                                index=0,
                                delta=ChatMessageDelta(content=token_text),
                            )],
                        ))
                    continue

                for node_name, node_output in payload.items():
                    node_messages = node_output.get("messages", [])

                    # Track net_data updates
                    if "net_data" in node_output:
                        final_net_data = node_output["net_data"]

                    # Propagate agent-level errors (e.g. LLM API failures caught
                    # inside chat_node) as visible text so the client is not left
                    # with a silent empty message.
                    node_error = node_output.get("error")
                    if node_error:
                        error_text = _clean_llm_error(node_error)
                        completion_tokens += self._token_manager.count_tokens(error_text)
                        yield _format_sse(ChatCompletionChunk(
                            id=completion_id,
                            created=created,
                            model=MODEL_ID,
                            choices=[ChunkChoice(
                                index=0,
                                delta=ChatMessageDelta(content=error_text),
                            )],
                        ))

                    for msg in node_messages:
                        if isinstance(msg, AIMessage):
                            # Whatever token streaming already delivered is
                            # not sent again. Only the remainder goes out,
                            # which is everything when nothing streamed --
                            # a provider that cannot stream still gets its
                            # answer through this path, in one piece.
                            text = _extract_text(msg.content)
                            remainder = (
                                text[len(streamed):]
                                if streamed and text.startswith(streamed)
                                else ("" if streamed else text)
                            )
                            streamed = ""
                            if remainder:
                                completion_tokens += self._token_manager.count_tokens(remainder)
                                for chunk_text in _chunk_text(remainder):
                                    yield _format_sse(ChatCompletionChunk(
                                        id=completion_id,
                                        created=created,
                                        model=MODEL_ID,
                                        choices=[ChunkChoice(
                                            index=0,
                                            delta=ChatMessageDelta(content=chunk_text),
                                        )],
                                    ))

                            # Surface structured tool invocations as
                            # agent_event chunks (non-standard extension).
                            # LangChain parses Anthropic tool_use blocks into
                            # AIMessage.tool_calls = [{id, name, args}, ...].
                            for tc in (msg.tool_calls or []):
                                yield _format_sse(ChatCompletionChunk(
                                    id=completion_id,
                                    created=created,
                                    model=MODEL_ID,
                                    choices=[ChunkChoice(
                                        index=0,
                                        delta=ChatMessageDelta(
                                            agent_event=AgentEventDelta(
                                                type="tool_call",
                                                id=tc.get("id") or "",
                                                name=tc.get("name"),
                                                input=tc.get("args") or {},
                                                status="running",
                                            ),
                                        ),
                                    )],
                                ))

                        elif isinstance(msg, ToolMessage):
                            # Emit a matching tool_result event so the UI can
                            # close out the running step card. PNML content
                            # is still injected below via _last_pnml_export.
                            output = _truncate_tool_output(_extract_text(msg.content))
                            status: Literal["success", "error"] = (
                                "error"
                                if getattr(msg, "status", None) == "error"
                                else "success"
                            )
                            yield _format_sse(ChatCompletionChunk(
                                id=completion_id,
                                created=created,
                                model=MODEL_ID,
                                choices=[ChunkChoice(
                                    index=0,
                                    delta=ChatMessageDelta(
                                        agent_event=AgentEventDelta(
                                            type="tool_result",
                                            id=msg.tool_call_id or "",
                                            status=status,
                                            output=output,
                                        ),
                                    ),
                                )],
                            ))

        except Exception as e:
            logger.error(f"Error during streaming: {e}")
            error_text = f"\n\nError: {e}"
            yield _format_sse(ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=MODEL_ID,
                choices=[ChunkChoice(
                    index=0,
                    delta=ChatMessageDelta(content=error_text),
                )],
            ))

        # Only the fallback wrap, not the rest of this turn's persistence
        # logic, needs to know THIS turn actually touched net_data (a pure
        # Q&A turn must never silently restructure whatever net a PRIOR,
        # possibly differently-styled turn left behind).
        if final_net_data is not net_data:
            final_net_data = _ensure_object_style(final_net_data, net_style)

        downloads = final_net_data.pop("_pending_downloads", []) if final_net_data else []
        for download in downloads:
            link_text = await self._binary_download_link(download, session_id, user_id)
            completion_tokens += self._token_manager.count_tokens(link_text)
            yield _format_sse(ChatCompletionChunk(
                id=completion_id, created=created, model=MODEL_ID,
                choices=[ChunkChoice(index=0, delta=ChatMessageDelta(content=link_text))],
            ))

        # If the agent produced PNML, store it and stream a download link
        pnml_content = final_net_data.pop("_last_pnml_export", None) if final_net_data else None
        if pnml_content:
            try:
                file_id = await self._file_service.store_pnml(
                    session_id=session_id,
                    user_id=user_id,
                    pnml_content=pnml_content,
                    filename="model.pnml",
                )
                download_token = get_jwt_service().create_download_token(
                    file_id=uuid.UUID(file_id),
                    user_id=user_id,
                )
                link_text = (
                    f"\n\n[Download PNML]({settings.APP_PUBLIC_URL.rstrip('/')}"
                    f"/api/v1/files/{file_id}?token={download_token})"
                )
                completion_tokens += self._token_manager.count_tokens(link_text)
                yield _format_sse(ChatCompletionChunk(
                    id=completion_id,
                    created=created,
                    model=MODEL_ID,
                    choices=[ChunkChoice(
                        index=0,
                        delta=ChatMessageDelta(content=link_text),
                    )],
                ))
            except Exception as e:
                logger.error(f"Failed to store PNML file: {e}")

        # Persist snapshot + net_data only when the net structure actually changed.
        # Unchanged turns (Q&A, explanations) produce no new snapshot.
        net_changed = (
            final_net_data is not net_data
            or _net_structure_hash(final_net_data) != initial_net_hash
        )
        snapshot_id: str | None = (
            await self._session_service.save_snapshot_and_net(session_id, final_net_data)
            if net_changed
            else None
        )

        # Emit snapshot_id chunk so the frontend can store it alongside the message.
        if snapshot_id:
            yield _format_sse(ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=MODEL_ID,
                choices=[],
                snapshot_id=snapshot_id,
            ))

        # Finish chunk — always "stop" since tool execution is hidden from client
        yield _format_sse(ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=MODEL_ID,
            choices=[ChunkChoice(
                index=0,
                delta=ChatMessageDelta(),
                finish_reason="stop",
            )],
        ))

        # Usage chunk (optional)
        if include_usage:
            yield _format_sse(ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=MODEL_ID,
                choices=[],
                usage=Usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                ),
            ))

        yield "data: [DONE]\n\n"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_session(
        self,
        messages: list[ChatMessage],
        user_id: uuid.UUID,
        api_key_hash: str | None,
    ) -> tuple[str, dict]:
        """Compute session fingerprint, load or create session, return (id, net_data)."""
        raw_messages = [m.model_dump() for m in messages]
        first_content = SessionService.extract_first_user_content(raw_messages)
        if not first_content:
            first_content = "__empty__"

        session_id = SessionService.compute_fingerprint(first_content, user_id, api_key_hash)
        await self._session_service.get_or_create(session_id, user_id)
        net_data = await self._session_service.restore_net_data(session_id)
        return session_id, net_data

    @staticmethod
    def _build_state(
        session_id: str,
        user_id: uuid.UUID,
        messages: list[BaseMessage],
        net_data: dict,
        credentials,
        net_style: str = DEFAULT_NET_STYLE,
        layout_direction: str = DEFAULT_LAYOUT_DIRECTION,
    ) -> AgentState:
        return AgentState(
            messages=messages,
            conversation_id=session_id,
            user_id=str(user_id),
            next_action="respond",
            context={"net_style": net_style, "layout_direction": layout_direction},
            token_count=0,
            error=None,
            net_data=net_data,
            credentials=credentials,
        )

    async def _bind_session_to_credential(
        self, session_id: str, resolved: ResolvedCredentials
    ) -> None:
        """
        Persist the resolved BYOK profile id on the session row.

        This makes follow-up turns work without re-passing
        ``metadata.llm_credential_id`` (the resolver still requires it on the
        first turn — implicit-binding by recall is a separate UX feature).
        """
        if resolved.source != "byok" or resolved.profile_id is None:
            return
        try:
            await self._session_service.session_repository.update_llm_credential(
                session_id, resolved.profile_id
            )
        except Exception as e:
            logger.warning(f"Failed to bind session {session_id} to credential: {e}")

    @staticmethod
    def _openai_to_langchain(messages: list[ChatMessage]) -> list[BaseMessage]:
        """Convert OpenAI ChatMessage list to LangChain BaseMessage list."""
        result: list[BaseMessage] = []
        for msg in messages:
            role = msg.role
            content = msg.content or ""

            if role == "system":
                result.append(SystemMessage(content=content))
            elif role == "user":
                result.append(HumanMessage(content=content))
            elif role == "assistant":
                kwargs: dict[str, Any] = {"content": content}
                if msg.tool_calls:
                    kwargs["tool_calls"] = [
                        {
                            "id": tc.id,
                            "name": tc.function.name,
                            "args": json.loads(tc.function.arguments)
                            if tc.function.arguments
                            else {},
                        }
                        for tc in msg.tool_calls
                    ]
                result.append(AIMessage(**kwargs))
            elif role == "tool":
                result.append(
                    ToolMessage(
                        content=content,
                        tool_call_id=msg.tool_call_id or "",
                    )
                )
        return result

    @staticmethod
    def _build_response_message(new_messages: list[BaseMessage]) -> ChatMessage:  # NOSONAR
        """
        Combine all new messages from the agent loop into a single OpenAI response.

        The final AIMessage's text content becomes ``content``; the intermediate
        tool calls and tool results are attached as a non-standard
        ``agent_events`` list so the UI can render the agent's chain of thought.
        They are NOT exposed as OpenAI ``tool_calls`` because that would make
        generic clients try to execute them on their side.
        """
        final_text: str = ""
        events: list[AgentEventDelta] = []

        for msg in new_messages:
            if isinstance(msg, AIMessage):
                text = _extract_text(msg.content)
                if text:
                    final_text = text  # keep the last assistant text as final reply
                for tc in (msg.tool_calls or []):
                    events.append(
                        AgentEventDelta(
                            type="tool_call",
                            id=tc.get("id") or "",
                            name=tc.get("name"),
                            input=tc.get("args") or {},
                            status="running",
                        )
                    )
            elif isinstance(msg, ToolMessage):
                output = _truncate_tool_output(_extract_text(msg.content))
                status: Literal["success", "error"] = (
                    "error"
                    if getattr(msg, "status", None) == "error"
                    else "success"
                )
                events.append(
                    AgentEventDelta(
                        type="tool_result",
                        id=msg.tool_call_id or "",
                        status=status,
                        output=output,
                    )
                )

        return ChatMessage(
            role="assistant",
            content=final_text or None,
            agent_events=events or None,
        )

    async def _binary_download_link(self, download: dict, session_id: str, user_id: uuid.UUID) -> str:
        try:
            file_id = await self._file_service.store_download(session_id, user_id, download)
            token = get_jwt_service().create_download_token(file_id=uuid.UUID(file_id), user_id=user_id)
            label = "Download PNG" if download["media_type"] == "image/png" else "Download training ZIP"
            return f"\n\n[{label}]({settings.APP_PUBLIC_URL.rstrip('/')}/api/v1/files/{file_id}?token={token})"
        except Exception:
            logger.exception("Could not save the generated binary export")
            return "\n\nThe export could not be saved. Please retry the export."

    async def _inject_pnml_download(
        self,
        response_message: ChatMessage,
        pnml_content: str,
        session_id: str,
        user_id: uuid.UUID,
    ) -> ChatMessage:
        """Store PNML content as a file and inject a download link into the reply."""
        try:
            file_id = await self._file_service.store_pnml(
                session_id=session_id,
                user_id=user_id,
                pnml_content=pnml_content,
                filename="model.pnml",
            )
            download_token = get_jwt_service().create_download_token(
                file_id=uuid.UUID(file_id),
                user_id=user_id,
            )
        except Exception as e:
            logger.error(f"Failed to store PNML file: {e}")
            return response_message

        download_link = (
            f"\n\n[Download PNML]({settings.APP_PUBLIC_URL.rstrip('/')}"
            f"/api/v1/files/{file_id}?token={download_token})"
        )
        current = response_message.content or ""
        return response_message.model_copy(
            update={"content": current + download_link}
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _make_completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:12]}"


def _format_sse(chunk: ChatCompletionChunk) -> str:
    return f"data: {chunk.model_dump_json()}\n\n"


#: Kept under this name because this module is read and tested by it; the
#: definition moved so the agent side shares one answer to "what is the
#: text of this message" instead of having none -- see message_content.py.
_extract_text = content_to_text


def _truncate_tool_output(text: str, limit: int = 2000) -> str:
    """Cap tool output text for streaming to keep SSE frames reasonable."""
    if len(text) <= limit:
        return text
    return text[:limit] + "... (truncated)"


def _clean_llm_error(error_str: str) -> str:
    """Extract a human-readable message from an LLM API error string.

    Anthropic/OpenAI SDK errors are stringified as:
    "Error code: 400 - {'type': 'error', 'error': {'message': '...'}, ...}"
    """
    match = re.search(r'\{.*\}', error_str, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            msg = data.get("error", {}).get("message")
            if msg:
                return msg
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    return error_str


def _chunk_text(text: str, max_chunk: int = 80) -> list[str]:
    """Split text into word-boundary chunks for streaming."""
    if len(text) <= max_chunk:
        return [text]

    chunks: list[str] = []
    words = text.split(" ")
    current: list[str] = []
    current_len = 0

    for word in words:
        if current_len + len(word) + 1 > max_chunk and current:
            chunks.append(" ".join(current) + " ")
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += len(word) + 1

    if current:
        chunks.append(" ".join(current))

    return chunks or [text]
