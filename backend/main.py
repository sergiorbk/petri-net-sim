"""
Main FastAPI application entry point.

Serves OpenAI-compatible API and/or MCP server depending on feature flags:
- openai.enabled  (OPENAI_ENABLED)  — OpenAI-compatible chat/completions API
- mcp.enabled     (MCP_ENABLED)     — Model Context Protocol server at /mcp
"""

import os
import signal
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from src.api import register_routers
from src.api.shared.exceptions import ApiException
from src.api.shared.handlers import (
    api_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from src.api.shared.middleware import (
    ApiVersionMiddleware,
    RequestIdMiddleware,
    RequestLoggingMiddleware,
)
from src.api.shared.security_middleware import (
    BodySizeLimitMiddleware,
    ConcurrencyLimitMiddleware,
    RequestTimeoutMiddleware,
    SecurityHeadersMiddleware,
)
from src.core import get_logger, settings
from src.core.config import validate_production_settings
from src.core.lifecycle import initialize_services, shutdown_services
from src.core.security_config import security_settings

logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    logger.info("Running startup tasks...")

    # Refuse to boot with insecure configuration in deployed environments.
    validate_production_settings()

    try:
        await initialize_services()
    except Exception:
        # Kill parent process (reloader) and current process
        os.kill(os.getppid(), signal.SIGTERM)
        os._exit(1)

    logger.info(f"{settings.APP_NAME} application started")

    async with AsyncExitStack() as stack:
        # Start MCP session manager if MCP is mounted
        if settings.MCP_ENABLED and hasattr(app.state, "mcp_session_manager"):
            await stack.enter_async_context(app.state.mcp_session_manager.run())
            logger.info("MCP session manager started at %s", settings.MCP_PATH)

        yield

    logger.info("Running shutdown tasks...")
    await shutdown_services()
    logger.info("Shutdown complete")


# API docs are disabled by default in deployed (stage/prod) environments to
# avoid advertising the full surface area; controlled by DOCS_ENABLED / APP_ENV.
_docs_enabled = settings.docs_enabled
if not _docs_enabled:
    logger.info("API docs disabled (APP_ENV=%s, DOCS_ENABLED=%s)", settings.APP_ENV, settings.DOCS_ENABLED)

# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="Text to PNML converter API - Converts textual descriptions of queueing systems into Petri Net models in PNML format",
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# A wildcard CORS origin combined with credentials is both spec-invalid and a
# security risk; drop credentials when origins are unrestricted.
_cors_origins = settings.cors_origins_list
_cors_allow_credentials = settings.CORS_ALLOW_CREDENTIALS
if "*" in _cors_origins and _cors_allow_credentials:
    logger.warning(
        "CORS: wildcard origin '*' is incompatible with credentials — "
        "forcing allow_credentials=False. Pin explicit origins to use credentials."
    )
    _cors_allow_credentials = False

# Middleware order matters — first added = outermost (sees the request first,
# the response last). Body-size and concurrency limits sit outermost so abusive
# traffic is shed before reaching any handler.
app.add_middleware(BodySizeLimitMiddleware)
if security_settings.SECURITY_MAX_CONCURRENT_REQUESTS > 0:
    app.add_middleware(
        ConcurrencyLimitMiddleware,
        max_concurrent=security_settings.SECURITY_MAX_CONCURRENT_REQUESTS,
    )

# Request-id generation must run before anything that reads the id (logging,
# response headers). Adding it here — just inside the traffic-shedding limits —
# makes it the outermost id-aware middleware, so every log line and the
# X-Request-ID response header carry the real id rather than "unknown".
app.add_middleware(RequestIdMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=settings.cors_methods_list,
    allow_headers=settings.cors_headers_list,
)

# Hardening response headers
app.add_middleware(SecurityHeadersMiddleware)

# Request logging (outer to the timeout so a 504 is still logged; inner to
# RequestIdMiddleware so request.state.request_id is already populated)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(ApiVersionMiddleware)

# Non-streaming request timeout (inner — wraps the handler)
app.add_middleware(
    RequestTimeoutMiddleware,
    timeout_seconds=security_settings.SECURITY_REQUEST_TIMEOUT_SECONDS,
)

# Register exception handlers
app.add_exception_handler(ApiException, api_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Register routers (health always; OpenAI API conditionally)
register_routers(app)

# Mount MCP server into FastAPI when enabled
if settings.MCP_ENABLED:
    from src.mcp.server import create_mcp_app_for_mount

    _mcp_instance, _mcp_starlette_app = create_mcp_app_for_mount()
    app.state.mcp_session_manager = _mcp_instance.session_manager

    # MCP claims "/" below (its own route lives at settings.MCP_PATH, e.g.
    # /mcp; everything else under "/" 404s inside its own sub-app today). A
    # second Mount("/", ...) on the outer app would never be reached once
    # that one is registered, so a pre-built frontend has to be attached to
    # this SAME sub-app instead -- see src/api/static_frontend.py.
    if settings.FRONTEND_STATIC_DIR:
        from src.api.static_frontend import mount_static_frontend

        mount_static_frontend(_mcp_starlette_app, settings.FRONTEND_STATIC_DIR)

    # Mount at root — MCP Starlette app has its own route at settings.MCP_PATH (e.g. /mcp)
    app.mount("/", _mcp_starlette_app)
    logger.info("MCP server mounted at %s", settings.MCP_PATH)
elif settings.FRONTEND_STATIC_DIR:
    from src.api.static_frontend import mount_static_frontend

    mount_static_frontend(app, settings.FRONTEND_STATIC_DIR)
