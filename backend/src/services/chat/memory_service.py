"""Service for managing conversation memory and context."""

from typing import List

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from src.core.agent_config import MemoryStrategy, agent_settings
from src.core.logger import get_logger
from src.services.llm.token_manager import TokenManager, get_token_manager

logger = get_logger()


class MemoryService:
    """Service for managing conversation memory and context windowing."""

    def __init__(
        self,
        strategy: MemoryStrategy | None = None,
        max_tokens: int | None = None,
        max_messages: int | None = None,
        summarization_threshold: int | None = None,
    ):
        self._strategy = strategy or agent_settings.AGENT_MEMORY_STRATEGY
        self._max_tokens = max_tokens or agent_settings.AGENT_MEMORY_MAX_TOKENS
        self._max_messages = max_messages or agent_settings.AGENT_MEMORY_MAX_MESSAGES
        self._summarization_threshold = (
            summarization_threshold or agent_settings.AGENT_MEMORY_SUMMARIZATION_THRESHOLD
        )
        self._token_manager = get_token_manager()

    def apply_context_window(
        self,
        messages: List[BaseMessage],
        system_prompt: str | None = None,
    ) -> List[BaseMessage]:
        """
        Apply context windowing strategy to messages.

        Args:
            messages: List of messages
            system_prompt: Optional system prompt (will be preserved)

        Returns:
            Windowed list of messages
        """
        if not messages:
            return messages

        if self._strategy == MemoryStrategy.SLIDING_WINDOW:
            return self._apply_sliding_window(messages, system_prompt)
        elif self._strategy == MemoryStrategy.TOKEN_WINDOW:
            return self._apply_token_window(messages, system_prompt)
        elif self._strategy == MemoryStrategy.SUMMARIZATION:
            return self._apply_summarization(messages, system_prompt)

        return messages

    def _apply_sliding_window(
        self,
        messages: List[BaseMessage],
        system_prompt: str | None = None,
    ) -> List[BaseMessage]:
        """
        Apply sliding window strategy - keep last N messages.

        N is a message count in its own right (AGENT_MEMORY_MAX_MESSAGES).
        It used to be derived from the TOKEN setting divided by a hardcoded
        "assume 100 tokens per message", so the knob said tokens, meant
        messages, and was wrong by however far real messages differed from
        100 tokens. Counting tokens for real is what TOKEN_WINDOW is for.
        """
        result: List[BaseMessage] = []
        system_messages: List[BaseMessage] = []

        # Separate system messages
        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_messages.append(msg)
            else:
                result.append(msg)

        window_size = self._max_messages

        # Keep last N messages
        if len(result) > window_size:
            result = result[-window_size:]
            logger.debug(f"Sliding window: kept last {window_size} messages")

        # Prepend system messages
        return system_messages + result

    def _apply_token_window(
        self,
        messages: List[BaseMessage],
        system_prompt: str | None = None,
    ) -> List[BaseMessage]:
        """
        Apply token-based windowing - keep messages within token limit.
        """
        return self._token_manager.truncate_messages(
            messages,
            max_tokens=self._max_tokens,
            preserve_system=True,
        )

    def _apply_summarization(
        self,
        messages: List[BaseMessage],
        system_prompt: str | None = None,
    ) -> List[BaseMessage]:
        """
        Apply summarization strategy - summarize old messages.

        Note: Full summarization requires LLM call, which should be done
        in the chat service. This method returns messages with a marker
        for summarization.
        """
        if len(messages) <= self._summarization_threshold:
            return messages

        # For now, fall back to token windowing
        # Full summarization should be implemented in ChatService
        logger.debug(
            f"Messages ({len(messages)}) exceed threshold ({self._summarization_threshold}), "
            f"falling back to token windowing"
        )
        return self._apply_token_window(messages, system_prompt)

    def get_context_stats(self, messages: List[BaseMessage]) -> dict:
        """
        Get statistics about the current context.

        Args:
            messages: List of messages

        Returns:
            Dictionary with context statistics
        """
        total_tokens = self._token_manager.count_messages_tokens(messages)

        role_counts = {"user": 0, "assistant": 0, "system": 0, "tool": 0}
        for msg in messages:
            if isinstance(msg, HumanMessage):
                role_counts["user"] += 1
            elif isinstance(msg, AIMessage):
                role_counts["assistant"] += 1
            elif isinstance(msg, SystemMessage):
                role_counts["system"] += 1
            else:
                role_counts["tool"] += 1

        return {
            "message_count": len(messages),
            "total_tokens": total_tokens,
            "max_tokens": self._max_tokens,
            "tokens_remaining": max(0, self._max_tokens - total_tokens),
            "strategy": self._strategy.value,
            "role_counts": role_counts,
        }

    def needs_summarization(self, messages: List[BaseMessage]) -> bool:
        """
        Check if messages need summarization.

        Args:
            messages: List of messages

        Returns:
            True if summarization is needed
        """
        if self._strategy != MemoryStrategy.SUMMARIZATION:
            return False

        return len(messages) > self._summarization_threshold

    async def create_summary(
        self,
        messages: List[BaseMessage],
        llm_generate_fn,
    ) -> str:
        """
        Create a summary of messages using LLM.

        Args:
            messages: Messages to summarize
            llm_generate_fn: Async function to generate LLM response

        Returns:
            Summary string
        """
        if not messages:
            return ""

        # Create summarization prompt
        conversation_text = self._format_messages_for_summary(messages)

        summary_prompt = [
            SystemMessage(
                content=(
                    "You are a helpful assistant that summarizes conversations. "
                    "Provide a concise summary of the key points discussed, "
                    "decisions made, and any important context needed for "
                    "continuing the conversation."
                )
            ),
            HumanMessage(
                content=f"Please summarize this conversation:\n\n{conversation_text}"
            ),
        ]

        response = await llm_generate_fn(summary_prompt)
        return response.content if hasattr(response, "content") else str(response)

    def _format_messages_for_summary(self, messages: List[BaseMessage]) -> str:
        """Format messages as text for summarization."""
        lines = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                role = "User"
            elif isinstance(msg, AIMessage):
                role = "Assistant"
            elif isinstance(msg, SystemMessage):
                continue  # Skip system messages in summary
            else:
                role = "Tool"

            content = msg.content if hasattr(msg, "content") else str(msg)
            lines.append(f"{role}: {content}")

        return "\n".join(lines)
