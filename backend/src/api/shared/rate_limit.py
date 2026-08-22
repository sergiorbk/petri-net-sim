"""Reusable in-memory rate-limit dependency for FastAPI routes.

Provides ``rate_limit(...)`` — a dependency factory that caps requests per
identity (per-credential or per-IP) within a fixed time window. Attach it via
``dependencies=[Depends(rate_limit(...))]`` on a router or path operation.

Counters live in process memory (a fixed-window per key), so the limit is
per-worker rather than shared across uvicorn workers. At this scale that is an
acceptable trade-off for having zero external dependencies; with N workers the
effective ceiling is up to N times the configured limit.

Identity resolution is intentionally cheap and DB-free:
- ``by="token"`` keys on a SHA-256 of the bearer credential (API key or JWT),
  so each key/token gets its own budget without a database lookup. Falls back
  to the client IP for unauthenticated callers.
- ``by="ip"`` keys on the trusted-proxy-aware client IP — used for endpoints
  that run before authentication (login, signup, refresh, oauth).

If the limiter ever raises unexpectedly the request fails open or closed per
``SECURITY_RATE_LIMIT_FAIL_OPEN`` (default open: availability over strictness).
"""

import asyncio
import hashlib
import math
import time
from typing import Awaitable, Callable, Literal

from fastapi import Request

from src.api.shared.client_ip import get_client_ip
from src.api.shared.exceptions import RateLimitException, ServiceUnavailableException
from src.core.logger import get_logger
from src.core.auth_config import auth_settings
from src.core.security_config import security_settings

logger = get_logger("api.rate_limit")

_KEY_PREFIX = "rl"

# In-memory fixed-window counters: key -> (count, window_expiry_monotonic).
_WINDOWS: dict[str, tuple[int, float]] = {}
_LOCK = asyncio.Lock()
# Opportunistic sweep bookkeeping so abandoned keys don't accumulate forever.
_SWEEP_INTERVAL = 60.0
_last_sweep = 0.0


def _identity(request: Request, by: Literal["token", "ip"]) -> str:
    """Compute the rate-limit identity for this request.

    Returns a short, non-reversible identifier so logs never carry raw
    credentials.
    """
    if by == "ip":
        return f"ip:{get_client_ip(request)}"

    # by == "token": hash the bearer credential when present.
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and len(auth) > 7:
        token = auth[7:].strip()
        if token:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
            return f"tok:{digest}"
    # No credential — degrade to per-IP so anonymous floods are still bounded.
    return f"ip:{get_client_ip(request)}"


def reset_rate_limit_state() -> None:
    """Clear all in-memory windows. Used by tests to isolate the limiter."""
    global _last_sweep
    _WINDOWS.clear()
    _last_sweep = 0.0


def _sweep_locked(now: float) -> None:
    """Drop expired windows. Must be called while holding ``_LOCK``."""
    global _last_sweep
    if now - _last_sweep < _SWEEP_INTERVAL:
        return
    _last_sweep = now
    expired = [k for k, (_, exp) in _WINDOWS.items() if exp <= now]
    for k in expired:
        del _WINDOWS[k]


async def _hit(key: str, max_requests: int, window: int) -> tuple[bool, int, int]:
    """Increment the window counter. Returns (allowed, count, retry_after).

    Fixed-window algorithm: the first hit for a key opens a window of
    ``window`` seconds; subsequent hits increment the count until the window
    expires, at which point it resets.
    """
    now = time.monotonic()
    async with _LOCK:
        _sweep_locked(now)

        count, expiry = _WINDOWS.get(key, (0, 0.0))
        if now >= expiry:
            # Start a fresh window.
            count = 1
            expiry = now + window
        else:
            count += 1
        _WINDOWS[key] = (count, expiry)
        retry_after = max(1, math.ceil(expiry - now))

    return count <= max_requests, count, retry_after


def rate_limit(
    scope: str,
    max_requests: int,
    window_seconds: int,
    by: Literal["token", "ip"] = "token",
) -> Callable[[Request], Awaitable[None]]:
    """Build a FastAPI dependency enforcing a fixed-window rate limit.

    Args:
        scope: namespace for the counter (e.g. "chat", "simulate"). Keeps
            independent budgets per endpoint class.
        max_requests: allowed requests per window.
        window_seconds: window length in seconds.
        by: identity strategy — "token" (per credential) or "ip".
    """

    async def dependency(request: Request) -> None:
        # Nothing to ration when there is one user. A rate limit exists to
        # keep one caller from crowding out the others, and single-user mode
        # has no others -- every rejection there would be the owner of the
        # machine being told to wait by their own machine.
        if auth_settings.AUTH_MODE == "single_user":
            return

        identity = _identity(request, by)
        key = f"{_KEY_PREFIX}:{scope}:{identity}"

        try:
            allowed, count, retry_after = await _hit(key, max_requests, window_seconds)
        except Exception as exc:
            if security_settings.SECURITY_RATE_LIMIT_FAIL_OPEN:
                logger.warning(
                    "Rate limiter errored for scope=%s identity=%s — failing "
                    "OPEN (allowing request): %s",
                    scope,
                    identity,
                    exc,
                )
                return
            logger.error(
                "Rate limiter errored for scope=%s identity=%s — failing "
                "CLOSED (rejecting request): %s",
                scope,
                identity,
                exc,
            )
            raise ServiceUnavailableException(
                message="Rate limiting is temporarily unavailable."
            )

        if not allowed:
            logger.warning(
                "Rate limit exceeded: scope=%s identity=%s count=%d limit=%d "
                "window=%ds path=%s",
                scope,
                identity,
                count,
                max_requests,
                window_seconds,
                request.url.path,
            )
            raise RateLimitException(
                message=(
                    f"Rate limit exceeded for '{scope}': "
                    f"max {max_requests} requests per {window_seconds}s. "
                    f"Retry after {retry_after}s."
                ),
                retry_after=retry_after,
                limit=max_requests,
                window=window_seconds,
            )

    return dependency
