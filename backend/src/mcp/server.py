"""MCP server for Petri Net Sim — exposes Petri Net tools via Model Context Protocol."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from petri_modeling_skills import catalog

from src.core.config import settings
from src.mcp.session_store import AbstractSessionStore, InMemorySessionStore

logger = logging.getLogger("mcp")

#: Cap on the periodic cleanup interval, in seconds (D1). A very long TTL
#: should not mean sessions sit around uncleaned for hours between passes.
_MAX_CLEANUP_INTERVAL_SECONDS = 300


@dataclass
class McpLifespanContext:
    """Shared state available to all MCP tools via lifespan."""

    session_store: AbstractSessionStore


def _build_session_store(ttl_seconds: int) -> AbstractSessionStore:
    logger.info("MCP session store: in-memory (TTL: %ds)", ttl_seconds)
    return InMemorySessionStore(ttl_seconds=ttl_seconds)


def _cleanup_interval_seconds(ttl_seconds: float) -> float:
    """D1: how often the periodic cleanup task runs, given the session TTL.

    A quarter of the TTL, capped at 5 minutes, so long-TTL deployments still
    reclaim expired sessions promptly instead of only at server shutdown.
    """
    return min(ttl_seconds / 4, _MAX_CLEANUP_INTERVAL_SECONDS)


async def _periodic_cleanup(store: AbstractSessionStore, interval_seconds: float) -> None:
    """D1: purge expired sessions on a fixed interval for the life of the server.

    Without this, InMemorySessionStore only ever loses stale sessions on
    server shutdown (mcp_lifespan's `finally`) or when something happens to
    call cleanup_expired() itself -- an idle deployment accumulates expired
    sessions in memory indefinitely between restarts. Runs until cancelled
    by mcp_lifespan on shutdown.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            expired = await store.cleanup_expired()
            if expired:
                logger.info("Periodic cleanup: removed %d expired session(s)", expired)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A cleanup failure must not kill the background loop -- log and
            # keep going, matching the "never crash the server" spirit of a
            # housekeeping task.
            logger.exception("Periodic session cleanup failed")


@asynccontextmanager
async def mcp_lifespan(server: FastMCP) -> AsyncIterator[McpLifespanContext]:
    """MCP server lifecycle: initialize session store, run periodic cleanup,
    cleanup once more on shutdown."""
    from src.core.config import settings

    store = _build_session_store(settings.MCP_SESSION_TTL_SECONDS)
    interval = _cleanup_interval_seconds(settings.MCP_SESSION_TTL_SECONDS)
    cleanup_task = asyncio.create_task(_periodic_cleanup(store, interval))
    logger.info(
        "MCP server starting (session TTL: %ds, cleanup every %ds)",
        settings.MCP_SESSION_TTL_SECONDS, interval,
    )
    try:
        yield McpLifespanContext(session_store=store)
    finally:
        cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup_task
        expired = await store.cleanup_expired()
        logger.info(
            "MCP server shutting down (cleaned %d expired sessions)", expired
        )


#: The installed FastMCP SDK's constructor takes no `version=` kwarg, so the
#: product version is surfaced in the instructions text instead.
_MCP_INSTRUCTIONS = (
    f"Petri Net Sim MCP Server (v{settings.APP_VERSION}). "
    "Before building or changing a model, read the shared modeling guides and "
    "the application's tool bindings. Use the build_queueing_system or "
    "build_production_line prompt for a complete task context. "
    "Shared resources: " + ", ".join(resource["uri"] for resource in catalog()) + ". "
    "Application bindings: petri://skills/petri-net-sim-api. "
    "Inspect the existing model and available tool schemas before editing."
)


def _register_all(mcp: FastMCP) -> None:
    """Register tools, resources, and prompts on a FastMCP instance."""
    from src.mcp.tools import register_tools
    from src.mcp.resources import register_resources
    from src.mcp.prompts import register_prompts

    register_tools(mcp)
    register_resources(mcp)
    register_prompts(mcp)


def create_mcp_server() -> FastMCP:
    """Create and configure the MCP server for standalone use."""
    from src.core.config import settings

    mcp = FastMCP(
        name=settings.MCP_NAME,
        instructions=_MCP_INSTRUCTIONS,
        host=settings.MCP_HOST,
        port=settings.MCP_PORT,
        lifespan=mcp_lifespan,
    )

    _register_all(mcp)
    logger.info("MCP server configured with tools, resources, and prompts")
    return mcp


def create_mcp_app_for_mount():
    """Create MCP server configured for mounting inside FastAPI.

    Returns (FastMCP instance, Starlette app).
    The caller must manage ``mcp.session_manager.run()`` in its own lifespan.
    """
    from src.core.config import settings

    mcp = FastMCP(
        name=settings.MCP_NAME,
        instructions=_MCP_INSTRUCTIONS,
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        streamable_http_path=settings.MCP_PATH,
        lifespan=mcp_lifespan,
    )

    _register_all(mcp)

    starlette_app = mcp.streamable_http_app()

    # Wrap with API key auth middleware for HTTP transport
    from src.mcp.auth import McpApiKeyAuthMiddleware

    starlette_app.add_middleware(McpApiKeyAuthMiddleware)

    logger.info("MCP server configured for FastAPI mount at %s (auth enabled)", settings.MCP_PATH)
    return mcp, starlette_app
