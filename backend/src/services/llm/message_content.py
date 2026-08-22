"""Reading the text out of a chat message's content.

A LangChain message's `content` is either a plain string or a list of
content blocks, and which one it is depends on the model rather than on
anything this app does: newer Claude models answer in blocks (text
alongside thinking and tool-use blocks) where older ones answered with a
string. Anything that treats content as text has to cope with both.

This lived privately in the chat service, which is why the agent side did
not cope: it handed a block list straight to the token counter and got
`TypeError: expected string or buffer` from tiktoken, after a perfectly
successful API call. One definition, shared, is the fix -- the question
"what is the text of this message" has one answer, not one per caller.
"""

from typing import Any


def content_to_text(content: Any) -> str:
    """The printable text of a message content value.

    Only blocks with ``type == "text"`` contribute: thinking blocks are the
    model's private reasoning and tool-use blocks are surfaced separately
    as agent events, so neither belongs in the visible answer. Returns an
    empty string when there is no text to show, including for None.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", "") or "")
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""
