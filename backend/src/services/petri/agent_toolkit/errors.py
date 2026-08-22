"""One error envelope for every agent-facing Petri Net tool operation.

Today the MCP tool bodies and the tool_node handlers each grew their own
half of an error convention: roughly a third of them catch ValueError by
hand and return an "Error: ..." string (a soft, isError=False failure);
the rest let exceptions propagate uncaught, and each SDK's generic
exception handler turns those into a differently-shaped hard failure. This
module replaces both with one typed result: every operation in
operations.py returns either a plain `str` (success, or a purely
informational message like "No network yet") or a `ToolError` (a
recognized domain-level failure). Genuinely unexpected exceptions are bugs
and are left to propagate; they should not be silently downgraded to
tool-error text.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from typing import Callable, TypeVar

_R = TypeVar("_R", bound=str)


@dataclass(frozen=True)
class ToolError:
    """A recognized, user-facing tool failure.

    Carries the exact "Error: <message>" text every hand-written tool used
    to build by hand, but as a typed value so an adapter can tell a
    failure apart from a normal result without pattern-matching on the
    returned string's prefix.
    """

    message: str

    def __str__(self) -> str:
        return self.message


def tool_operation(func: Callable[..., _R]) -> Callable[..., "str | ToolError"]:
    """Wrap an operation so domain validation/lookup failures become a ToolError.

    ValueError and KeyError are the two shapes the domain and builder
    layers already raise for "bad input" or "not found" (see
    src/domain/models/net.py's update_*/remove_* methods, and every
    pattern's own capacity/threshold guards). Both are converted here to
    `ToolError(f"Error: {exc}")`. Any other exception is an actual bug in
    the operation, the domain layer, or the caller's plumbing, and
    propagates unchanged so it surfaces loudly instead of being
    misreported as ordinary bad input.
    """

    @wraps(func)
    def wrapper(*args, **kwargs) -> "str | ToolError":
        try:
            return func(*args, **kwargs)
        except (ValueError, KeyError) as exc:
            return ToolError(f"Error: {exc}")

    return wrapper
