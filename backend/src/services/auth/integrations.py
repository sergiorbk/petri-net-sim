"""Per-user integration switches for the machine-facing entry points.

Two doors into this app answer to a user's API keys rather than to a
browser session: the MCP server (``settings.MCP_PATH``) and the
OpenAI-compatible HTTP API (``/api/v1/chat/completions``). A user who
never uses either one has no way to close them short of revoking every
key, which also breaks the door they do use.

These flags close one door without touching the other. They are stored
in ``User.metadata_`` next to the profile fields, and both default to
enabled so that an account created before this existed keeps working
exactly as it did.

Deliberately, the flags gate API-key callers only. The web UI reaches
the same OpenAI-compatible endpoint with a JWT, so enforcing on every
caller would turn "stop programs from using my keys" into "stop my own
chat from answering" -- see AuthContext.api_key_hash, which is set for
sk- callers and None for everyone else.
"""

from typing import Any

METADATA_KEY = "integrations"

MCP = "mcp"
HTTP_API = "http_api"

INTEGRATIONS = (MCP, HTTP_API)


def integration_enabled(user: Any, name: str) -> bool:
    """Whether ``user`` allows API-key access through ``name``.

    Absent, malformed, or non-boolean values read as enabled: the flag is
    a switch the user has to actively turn off, not one they have to find
    and turn on.
    """
    meta = getattr(user, "metadata_", None) or {}
    flags = meta.get(METADATA_KEY)
    if not isinstance(flags, dict):
        return True
    return flags.get(name) is not False


def read_integrations(user: Any) -> dict[str, bool]:
    """Every switch's current state, for reporting back to the owner."""
    return {name: integration_enabled(user, name) for name in INTEGRATIONS}


def apply_integration(meta: dict, name: str, enabled: bool) -> dict:
    """Return ``meta`` with ``name`` set to ``enabled``.

    The nested mapping is rebuilt rather than edited in place, and that is
    load-bearing. Callers pass a shallow copy of User.metadata_, so the
    nested dict inside it is the very object SQLAlchemy holds as the
    column's committed value. Mutating it edits the "before" and the
    "after" at once: on flush the two compare equal, no UPDATE is emitted,
    and the switch reports success while the row keeps its old value.
    Every write after the first one would be lost that way.
    """
    existing = meta.get(METADATA_KEY)
    flags = dict(existing) if isinstance(existing, dict) else {}
    flags[name] = enabled
    meta[METADATA_KEY] = flags
    return meta


__all__ = [
    "HTTP_API",
    "INTEGRATIONS",
    "MCP",
    "METADATA_KEY",
    "apply_integration",
    "integration_enabled",
    "read_integrations",
]
