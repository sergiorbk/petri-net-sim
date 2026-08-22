"""Token counting and management utilities."""

from typing import Any

import tiktoken
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.services.llm.message_content import content_to_text

from src.core.agent_config import agent_settings
from src.core.logger import get_logger

logger = get_logger()


class TokenManager:
    """Manages token counting for messages and conversations."""

    # Default encoding for OpenAI models
    DEFAULT_ENCODING = "cl100k_base"

    # Approximate tokens per message overhead
    TOKENS_PER_MESSAGE = 4
    TOKENS_PER_NAME = 1

    def __init__(self, encoding_name: str | None = None):
        self._encoding_name = encoding_name or self.DEFAULT_ENCODING
        self._encoding: tiktoken.Encoding | None = None

    def _get_encoding(self) -> tiktoken.Encoding:
        """Get or create the tiktoken encoding."""
        if self._encoding is None:
            try:
                self._encoding = tiktoken.get_encoding(self._encoding_name)
            except Exception as e:
                logger.warning(f"Failed to get encoding {self._encoding_name}: {e}")
                self._encoding = tiktoken.get_encoding(self.DEFAULT_ENCODING)
        return self._encoding

    def count_tokens(self, text: Any) -> int:
        """
        Count tokens in a text string.

        Args:
            text: The text to count tokens for. A message `content` value is
                accepted too -- a list of content blocks, which is what
                newer models answer with -- and reduces to its text first.
                tiktoken raises a bare "expected string or buffer" for
                anything else, which says nothing about which caller or
                which model produced it, so the shape is normalised here
                rather than left to every call site to remember.

        Returns:
            Number of tokens
        """
        text = text if isinstance(text, str) else content_to_text(text)
        encoding = self._get_encoding()
        return len(encoding.encode(text))

    def count_message_tokens(self, message: BaseMessage) -> int:
        """
        Count tokens in a single message.

        Args:
            message: The message to count tokens for

        Returns:
            Number of tokens including overhead
        """
        tokens = self.TOKENS_PER_MESSAGE

        # Count content tokens
        if message.content:
            if isinstance(message.content, str):
                tokens += self.count_tokens(message.content)
            elif isinstance(message.content, list):
                # Handle multimodal content
                for part in message.content:
                    if isinstance(part, str):
                        tokens += self.count_tokens(part)
                    elif isinstance(part, dict) and "text" in part:
                        tokens += self.count_tokens(part["text"])

        # Add role tokens
        role = self._get_role_name(message)
        tokens += self.count_tokens(role)

        # Add name tokens if present
        if hasattr(message, "name") and message.name:
            tokens += self.TOKENS_PER_NAME
            tokens += self.count_tokens(message.name)

        return tokens

    def count_messages_tokens(self, messages: list[BaseMessage]) -> int:
        """
        Count total tokens for a list of messages.

        Args:
            messages: List of messages

        Returns:
            Total number of tokens
        """
        total = 0
        for message in messages:
            total += self.count_message_tokens(message)
        # Add 3 tokens for the assistant's reply priming
        total += 3
        return total

    def _get_role_name(self, message: BaseMessage) -> str:
        """Get the role name for a message."""
        if isinstance(message, SystemMessage):
            return "system"
        elif isinstance(message, HumanMessage):
            return "user"
        elif isinstance(message, AIMessage):
            return "assistant"
        elif isinstance(message, ToolMessage):
            return "tool"
        return "user"

    def truncate_messages(
        self,
        messages: list[BaseMessage],
        max_tokens: int | None = None,
        preserve_system: bool = True,
    ) -> list[BaseMessage]:
        """
        Truncate messages to fit within token limit.

        Removes oldest messages first while optionally preserving
        system messages.

        Args:
            messages: List of messages to truncate
            max_tokens: Maximum tokens allowed (uses config default if None)
            preserve_system: Whether to preserve system messages

        Returns:
            Truncated list of messages
        """
        if max_tokens is None:
            max_tokens = agent_settings.AGENT_MEMORY_MAX_TOKENS

        if not messages:
            return messages

        current_tokens = self.count_messages_tokens(messages)
        if current_tokens <= max_tokens:
            return messages

        # Separate system messages if we need to preserve them
        system_messages: list[BaseMessage] = []
        other_messages: list[BaseMessage] = []

        for msg in messages:
            if preserve_system and isinstance(msg, SystemMessage):
                system_messages.append(msg)
            else:
                other_messages.append(msg)

        # Calculate tokens for system messages
        system_tokens = self.count_messages_tokens(system_messages) if system_messages else 0

        # Calculate available tokens for other messages
        available_tokens = max_tokens - system_tokens - 3  # Reserve for reply priming

        if available_tokens <= 0:
            logger.warning("System messages exceed token limit")
            return system_messages

        # Remove oldest non-system messages until we fit
        truncated: list[BaseMessage] = []
        running_tokens = 0

        # Process from newest to oldest
        for msg in reversed(other_messages):
            msg_tokens = self.count_message_tokens(msg)
            if running_tokens + msg_tokens <= available_tokens:
                truncated.insert(0, msg)
                running_tokens += msg_tokens
            else:
                break

        logger.debug(
            f"Truncated messages from {len(messages)} to {len(system_messages) + len(truncated)}"
        )

        return system_messages + truncated

    def estimate_response_tokens(
        self,
        prompt_tokens: int,
        max_completion_tokens: int | None = None,
    ) -> int | None:
        """
        Estimate maximum response tokens available.

        Args:
            prompt_tokens: Number of tokens in the prompt
            max_completion_tokens: Maximum completion tokens. Falls back to
                the configured ceiling, which is normally absent -- this app
                imposes none, so a model may answer up to its own maximum.

        Returns:
            Room left under the ceiling, or None when there is no ceiling to
            measure against. "How much is left" is a question about a limit,
            so with no limit the honest answer is that there is not one,
            rather than a number large enough to look like one.
        """
        if max_completion_tokens is None:
            max_completion_tokens = agent_settings.AGENT_LLM_MAX_TOKENS
        if max_completion_tokens is None:
            return None

        return max(0, max_completion_tokens - prompt_tokens)


# Global token manager instance
_token_manager: TokenManager | None = None


def get_token_manager() -> TokenManager:
    """Get or create the global token manager instance."""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager()
    return _token_manager
