"""Application-layer security middlewares (defense-in-depth).

These run for every request — including the mounted MCP sub-app — and protect
the process from the resource-exhaustion vectors that a direct (proxy-less)
uvicorn/Docker deployment is otherwise exposed to:

- ``BodySizeLimitMiddleware``    — caps request body size (memory exhaustion).
- ``ConcurrencyLimitMiddleware`` — caps total in-flight requests (worker / DB
  pool exhaustion); sheds load with 503 instead of collapsing.
- ``RequestTimeoutMiddleware``   — hard wall-clock ceiling for non-streaming
  requests (slow/hung handlers); returns 504.
- ``SecurityHeadersMiddleware``  — sets standard hardening response headers.

Everything logs loudly when it trips so abuse is visible in the operational logs.
"""

import asyncio

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.core.logger import get_logger
from src.core.security_config import security_settings

logger = get_logger("api.security")

_HEALTH_PATH = "/health"


def _client_from_scope(scope: Scope) -> str:
    client = scope.get("client")
    if client and isinstance(client, (tuple, list)) and client:
        return str(client[0])
    return "unknown"


# ---------------------------------------------------------------------------
# Body size limit (pure ASGI — must see the raw receive stream)
# ---------------------------------------------------------------------------


class _BodyTooLarge(Exception):
    """Internal signal raised from the wrapped receive when the cap is hit."""


class BodySizeLimitMiddleware:
    """Reject request bodies larger than the configured cap with HTTP 413.

    Enforced two ways:
      1. Fast path — reject immediately when the ``Content-Length`` header
         already exceeds the cap (covers all well-behaved HTTP clients).
      2. Streaming path — count bytes as the body arrives and abort if the
         total exceeds the cap (covers chunked / Content-Length-less uploads).

    Endpoints under the configured "large body" prefixes (chat, simulate) get a
    higher cap because they legitimately accept full Petri-net JSON payloads.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._default_max = security_settings.SECURITY_MAX_BODY_BYTES
        self._large_max = security_settings.SECURITY_MAX_BODY_BYTES_LARGE
        self._large_prefixes = security_settings.large_body_prefixes

    def _max_for(self, path: str) -> int:
        if path.startswith(self._large_prefixes):
            return self._large_max
        return self._default_max

    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None

    async def _reject(self, scope: Scope, send: Send, max_bytes: int) -> None:
        logger.warning(
            "Request body too large: path=%s client=%s limit=%d bytes",
            scope.get("path", ""),
            _client_from_scope(scope),
            max_bytes,
        )
        response = JSONResponse(
            status_code=413,
            content={
                "error": "Request body too large",
                "max_bytes": max_bytes,
            },
        )
        await response(scope, _empty_receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        max_bytes = self._max_for(scope.get("path", ""))

        content_length = self._content_length(scope)
        if content_length is not None and content_length > max_bytes:
            await self._reject(scope, send, max_bytes)
            return

        total = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > max_bytes:
                    raise _BodyTooLarge()
            return message

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, send_wrapper)
        except _BodyTooLarge:
            if not response_started:
                await self._reject(scope, send, max_bytes)
            else:
                # Body overran after the handler already started responding —
                # nothing safe to send; surface for diagnostics.
                logger.error(
                    "Body cap exceeded after response started: path=%s",
                    scope.get("path", ""),
                )
                raise


async def _empty_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


# ---------------------------------------------------------------------------
# Concurrency limit
# ---------------------------------------------------------------------------


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    """Cap total in-flight requests; shed excess with HTTP 503.

    Protects the DB connection pool and the event loop from unbounded fan-out
    under a flood. Rejection is immediate (no queueing) so attackers get a fast
    503 rather than tying up resources. The check/increment pair runs without
    an intervening ``await``, so it is atomic on the single-threaded event loop.
    """

    def __init__(self, app: ASGIApp, max_concurrent: int) -> None:
        super().__init__(app)
        self._max = max_concurrent
        self._in_flight = 0

    async def dispatch(self, request, call_next):
        if self._max <= 0 or request.url.path == _HEALTH_PATH:
            return await call_next(request)

        if self._in_flight >= self._max:
            logger.warning(
                "Concurrency limit reached (%d/%d) — shedding request: %s %s from %s",
                self._in_flight,
                self._max,
                request.method,
                request.url.path,
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=503,
                content={"error": "Server is busy, please retry shortly."},
                headers={"Retry-After": "1"},
            )

        self._in_flight += 1
        try:
            return await call_next(request)
        finally:
            self._in_flight -= 1


# ---------------------------------------------------------------------------
# Request timeout (non-streaming)
# ---------------------------------------------------------------------------


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Abort non-streaming requests that exceed the wall-clock timeout (504).

    Streaming endpoints (SSE chat/simulate, MCP) are excluded — they are
    legitimately long-lived and rely on their own internal caps (simulation
    step/wall-clock limits, LLM client timeout).
    """

    def __init__(self, app: ASGIApp, timeout_seconds: float) -> None:
        super().__init__(app)
        self._timeout = timeout_seconds
        self._streaming_prefixes = security_settings.streaming_prefixes

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith(self._streaming_prefixes):
            return await call_next(request)

        try:
            return await asyncio.wait_for(call_next(request), timeout=self._timeout)
        except asyncio.TimeoutError:
            logger.error(
                "Request timed out after %.1fs: %s %s from %s",
                self._timeout,
                request.method,
                path,
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=504,
                content={"error": "Request timed out."},
            )


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

# Doc UIs need inline scripts/styles + a CDN, so they get a relaxed CSP.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "worker-src 'self' blob:"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach standard hardening headers to every response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._s = security_settings

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        headers = response.headers

        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", self._s.SECURITY_REFERRER_POLICY)
        headers.setdefault("X-XSS-Protection", "0")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if self._s.SECURITY_PERMISSIONS_POLICY:
            headers.setdefault("Permissions-Policy", self._s.SECURITY_PERMISSIONS_POLICY)
        if self._s.SECURITY_FRAME_DENY:
            headers.setdefault("X-Frame-Options", "DENY")

        path = request.url.path
        if path.startswith(_DOCS_PATHS):
            headers.setdefault("Content-Security-Policy", _DOCS_CSP)
        elif self._s.SECURITY_CSP:
            headers.setdefault("Content-Security-Policy", self._s.SECURITY_CSP)

        if self._s.SECURITY_HSTS_ENABLED:
            hsts = f"max-age={self._s.SECURITY_HSTS_MAX_AGE}"
            if self._s.SECURITY_HSTS_INCLUDE_SUBDOMAINS:
                hsts += "; includeSubDomains"
            headers.setdefault("Strict-Transport-Security", hsts)

        return response
