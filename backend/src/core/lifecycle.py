"""
Application lifecycle management.
Handles initialization and shutdown of all services.
"""

import asyncio

from src.core.logger import get_logger

logger = get_logger()


# --- LLM Service Initialization ---


async def initialize_llm_services() -> None:
    """
    Initialize LLM services.

    The app is BYOK-only: provider clients are minted on demand per user
    credential, so there is nothing to construct at boot beyond the factory
    singleton (whose shutdown path tears down any cached clients).
    """
    from src.services.llm import get_llm_factory

    logger.info("Initializing LLM services...")
    get_llm_factory()  # ensures the singleton exists
    logger.info(
        "LLM services ready — chat completions require user-provided credentials (BYOK)"
    )


async def initialize_simulation_backend() -> None:
    """Probe the remote simulation backend if configured."""
    from src.core.config import settings

    url = settings.simulation_remote_target
    if not url:
        logger.info(
            "Simulation backend: built-in engine (SIMULATION_ENGINE=%s)",
            settings.SIMULATION_ENGINE,
        )
        return

    import httpx

    fallback = settings.SIMULATION_REMOTE_FALLBACK
    fallback_note = ", fallback to built-in enabled" if fallback else ", fallback disabled"

    probe = url.rstrip("/") + "/actuator/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(probe)
            resp.raise_for_status()
        logger.info("Simulation backend: remote %s (reachable%s)", url, fallback_note)
    except Exception as e:
        logger.warning("Simulation backend: remote %s unreachable — %s%s", url, e, fallback_note)


async def initialize_auth_mode() -> None:
    """Bootstrap the fixed local user when AUTH_MODE=single_user.

    The same idempotent get-or-create also runs lazily inside the auth
    dependencies themselves (core/dependencies.py), so a request never has
    to wait on this -- this call is purely a startup-time convenience: it
    puts the row (and a confirming log line) in place before the first
    request arrives, and is a no-op in the default multi-user mode.

    ensure_local_user() also doubles as a safety check: if the fixed local
    email was already registered by some other path before single-user
    mode was ever enabled (see services/auth/local_user.py), it raises
    LocalUserBootstrapError instead of adopting that row. Left unguarded
    here, that raise propagates through initialize_services() and aborts
    startup (see the lifespan handler in main.py) -- deliberately: this is
    a boot-time integrity check, and refusing to start is correct, not a
    runtime 500 on the first request.
    """
    from src.core.auth_config import auth_settings

    if auth_settings.AUTH_MODE != "single_user":
        return

    from src.infrastructure.postgres.database import AsyncSessionLocal
    from src.services.auth.local_user import LOCAL_USER_EMAIL, ensure_local_user

    async with AsyncSessionLocal() as session:
        await ensure_local_user(session)

    logger.info(
        "AUTH_MODE=single_user -- no login required; unauthenticated "
        "requests are treated as the local user (%s)",
        LOCAL_USER_EMAIL,
    )


async def initialize_agent_services() -> None:
    """Initialize LangGraph agent services including checkpointer."""
    from src.services.agent.checkpointer import get_checkpointer_manager

    logger.info("Initializing agent services...")

    try:
        manager = get_checkpointer_manager()
        await manager.initialize()
        logger.info("Agent checkpointer initialized")
    except Exception as e:
        logger.warning(f"Agent checkpointer initialization failed (non-critical): {e}")
        # Checkpointer is optional for basic operation


# --- Initialization functions ---


async def initialize_postgres() -> None:
    """Initialize PostgreSQL connection and schema"""
    from src.core.config import settings
    from src.infrastructure.postgres import engine
    from src.infrastructure.postgres.base import Base
    from src.infrastructure.postgres.database import (
        AsyncSessionLocal,
        check_database_health,
    )

    logger.info("Initializing PostgreSQL connection pool...")

    async with AsyncSessionLocal() as session:
        health = await check_database_health(session)
        if health["status"] != "healthy":
            logger.error(f"PostgreSQL health check failed: {health}")
            logger.error("Application startup aborted due to database initialization failure")
            raise RuntimeError("PostgreSQL initialization failed")

        logger.info(
            f"PostgreSQL ready (latency: {health['latency_ms']}ms, pool: {health['pool_size']})"
        )

    # Create tables in dev mode
    if settings.DEBUG:
        logger.info("Creating database tables...")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")


async def initialize_services() -> None:
    """Initialize all application services"""
    logger.info("Initializing services...")

    # Initialize core services first
    await asyncio.gather(
        initialize_postgres(),
        initialize_llm_services(),
        initialize_simulation_backend(),
    )

    # Bootstrap the single-user local account, if enabled (depends on
    # postgres being ready, hence sequenced after the gather above).
    await initialize_auth_mode()

    # Initialize agent services (depends on postgres for checkpointer)
    await initialize_agent_services()

    logger.info("All services initialized")


# --- Shutdown functions ---


async def shutdown_llm_services() -> None:
    """Shutdown LLM services"""
    from src.services.llm import get_llm_factory

    logger.info("Shutting down LLM services...")

    try:
        factory = get_llm_factory()
        await factory.shutdown()
        logger.info("LLM services shut down")
    except Exception as e:
        logger.error(f"Error shutting down LLM services: {e}")


async def shutdown_agent_services() -> None:
    """Shutdown agent services"""
    from src.services.agent.checkpointer import get_checkpointer_manager

    logger.info("Shutting down agent services...")

    try:
        manager = get_checkpointer_manager()
        await manager.shutdown()
        logger.info("Agent services shut down")
    except Exception as e:
        logger.error(f"Error shutting down agent services: {e}")


async def shutdown_postgres() -> None:
    """Close PostgreSQL connections"""
    from src.infrastructure.postgres import engine

    logger.info("Closing PostgreSQL connections...")
    await engine.dispose()
    logger.info("PostgreSQL connections closed")


async def shutdown_services() -> None:
    """Shutdown all application services"""
    logger.info("Shutting down services...")

    try:
        await asyncio.gather(
            shutdown_agent_services(),
            shutdown_llm_services(),
        )
        # Shutdown postgres last as other services may depend on it
        await shutdown_postgres()
        logger.info("All services shut down")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
        # Don't raise during shutdown to allow graceful exit
