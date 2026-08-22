"""Extracts the human-readable rejection reason out of a petri-server error
response body.

Used by every router that talks to petri-server (`simulate.py`, `sessions.py`,
`simulate_composed.py`) so a 4xx carries the one sentence the canvas user can
act on instead of a bare "HTTP 400". Lived as `simulate_composed.py`'s private
`_remote_error_detail` first; extracted here once the flat-net routers needed
the identical behavior, rather than keeping three near-copies in sync by hand.
"""

from __future__ import annotations

import httpx


def remote_error_detail(response: httpx.Response) -> str | None:
    """The human-readable rejection out of a petri-server error body, or
    None when the body carries nothing usable (unparseable JSON with no
    text fallback, or a JSON body with none of the known message fields)."""
    try:
        body = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:500] if text else None
    if isinstance(body, dict):
        for key in ("message", "detail", "error"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
    return None
