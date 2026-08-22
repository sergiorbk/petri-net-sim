"""Trusted-proxy-aware client IP resolution.

Resolving the *real* client IP correctly is a security control: rate limiting,
abuse counters and audit logs key on it. Blindly trusting ``X-Forwarded-For``
lets any client spoof its IP and bypass per-IP limits, so by default
(``SECURITY_TRUST_PROXY_HEADERS=false``, the right choice for a direct
uvicorn/Docker deploy) we ignore forwarding headers entirely and use the real
TCP peer address.

When the app *is* behind a trusted proxy, set ``SECURITY_TRUST_PROXY_HEADERS=true``
and ``SECURITY_TRUSTED_PROXY_HOPS`` to the number of proxies you control; the
client IP is then taken that many entries from the right of the XFF chain
(entries the trusted proxies appended cannot be spoofed by the client).
"""

from fastapi import Request

from src.core.security_config import security_settings

_UNKNOWN = "unknown"


def get_client_ip(request: Request) -> str:
    """Return the best-effort client IP, honoring the trusted-proxy policy."""
    peer = request.client.host if request.client else _UNKNOWN

    if not security_settings.SECURITY_TRUST_PROXY_HEADERS:
        # Forwarding headers are attacker-controlled here — never trust them.
        return peer

    xff = request.headers.get("X-Forwarded-For")
    if not xff:
        # No proxy header present; fall back to the X-Real-IP convention, then peer.
        return (request.headers.get("X-Real-IP") or peer).strip()

    # XFF is "client, proxy1, proxy2, ...". Each trusted hop appended one entry
    # on the right. The client-supplied portion is everything the trusted hops
    # did NOT append, so we index `hops` from the right.
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if not parts:
        return peer

    hops = security_settings.SECURITY_TRUSTED_PROXY_HOPS
    idx = len(parts) - hops
    if idx < 0:
        idx = 0
    return parts[idx]
