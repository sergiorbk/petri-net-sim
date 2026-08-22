"""
Health check endpoints for monitoring and orchestration.
"""

from datetime import UTC, datetime
from typing import Any, Dict

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from src.core import get_logger, settings

logger = get_logger("api.health")
router = APIRouter(tags=["health"])


# Application start time for uptime calculation
_start_time = datetime.now(UTC)


class HealthStatus(BaseModel):
    """Health check response model."""

    status: str = Field(description="Service status: healthy, degraded, unhealthy")
    timestamp: datetime = Field(description="Current timestamp")
    uptime_seconds: float = Field(description="Application uptime in seconds")
    version: str = Field(default="1.0.0", description="Application version")
    environment: str = Field(description="Current environment")
    features: Dict[str, bool] = Field(
        default_factory=dict, description="Enabled feature flags"
    )


class DetailedHealthStatus(HealthStatus):
    """Detailed health check with component statuses."""

    components: Dict[str, Any] = Field(
        description="Status of individual components"
    )


@router.get(
    "/health",
    response_model=HealthStatus,
    status_code=status.HTTP_200_OK,
    summary="Basic health check",
    description="Returns basic application health status",
)
async def health_check() -> HealthStatus:
    """
    Basic health check endpoint.
    Returns 200 if application is running.
    Used by load balancers and basic monitoring.
    """
    uptime = (datetime.now(UTC) - _start_time).total_seconds()

    return HealthStatus(
        status="healthy",
        timestamp=datetime.now(UTC),
        uptime_seconds=uptime,
        version=settings.APP_VERSION,
        environment=settings.APP_NAME,
        features={
            "openai_api": settings.OPENAI_ENABLED,
            "mcp": settings.MCP_ENABLED,
        },
    )


@router.get(
    "/health/live",
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
    description="Kubernetes liveness probe - checks if application is alive",
)
async def liveness() -> Dict[str, str]:
    """
    Liveness probe for Kubernetes.
    Returns 200 if process is alive.
    If this fails, container should be restarted.
    """
    return {"status": "alive"}


@router.get(
    "/health/ready",
    response_model=DetailedHealthStatus,
    status_code=status.HTTP_200_OK,
    summary="Readiness probe",
    description="Kubernetes readiness probe - checks if application can handle traffic",
)
async def readiness() -> DetailedHealthStatus:
    """
    Readiness probe for Kubernetes.
    Returns 200 if application is ready to handle requests.
    Checks dependencies like databases, external services, etc.
    """
    uptime = (datetime.now(UTC) - _start_time).total_seconds()

    # Check various components
    components = {
        "logger": _check_logger(),
        "config": _check_config(),
        "database": await _check_database(),
        "llm": await _check_llm(),
        "agent": _check_agent(),
    }

    # Determine overall status
    component_statuses = [comp["status"] for comp in components.values()]
    if all(s == "healthy" for s in component_statuses):
        overall_status = "healthy"
    elif any(s == "unhealthy" for s in component_statuses):
        overall_status = "unhealthy"
    else:
        overall_status = "degraded"

    return DetailedHealthStatus(
        status=overall_status,
        timestamp=datetime.now(UTC),
        uptime_seconds=uptime,
        version=settings.APP_VERSION,
        environment=settings.APP_NAME,
        components=components,
    )


@router.get(
    "/health/startup",
    status_code=status.HTTP_200_OK,
    summary="Startup probe",
    description="Kubernetes startup probe - checks if application has started",
)
async def startup() -> Dict[str, str]:
    """
    Startup probe for Kubernetes.
    Returns 200 when application has finished initialization.
    Useful for slow-starting applications.
    """
    # Add initialization checks here if needed
    # For example, check if database migrations completed

    return {"status": "started"}


# Component check functions

def _check_logger() -> Dict[str, str]:
    """Check if logger is working."""
    try:
        test_logger = get_logger("health.check")
        test_logger.debug("Logger health check")
        return {"status": "healthy", "message": "Logger operational"}
    except Exception as e:
        logger.error(f"Logger health check failed: {e}")
        return {"status": "unhealthy", "message": str(e)}


def _check_config() -> Dict[str, str]:
    """Check if configuration is loaded."""
    try:
        # Verify essential config is present
        if settings.APP_NAME:
            return {"status": "healthy", "message": "Configuration loaded"}
        return {"status": "degraded", "message": "Partial configuration"}
    except Exception as e:
        logger.error(f"Config health check failed: {e}")
        return {"status": "unhealthy", "message": str(e)}


async def _check_database() -> Dict[str, Any]:
    """Check database connectivity."""
    try:
        from src.infrastructure.postgres.database import (
            AsyncSessionLocal,
            check_database_health,
        )

        async with AsyncSessionLocal() as session:
            health = await check_database_health(session)
            if health["status"] == "healthy":
                return {
                    "status": "healthy",
                    "message": "Database connected",
                    "latency_ms": health.get("latency_ms"),
                    "pool_size": health.get("pool_size"),
                }
            return {
                "status": "unhealthy",
                "message": health.get("error", "Database unhealthy"),
            }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {"status": "unhealthy", "message": str(e)}


async def _check_llm() -> Dict[str, Any]:
    """
    Check LLM connectivity.

    The app is BYOK-only: every user brings their own key, so there is no
    shared credential to ping. We just report the BYOK mode and how many
    per-credential provider clients are currently cached.
    """
    try:
        from src.services.llm import get_llm_factory

        factory = get_llm_factory()
        return {
            "status": "healthy",
            "message": "BYOK mode — per-user credentials are required",
            "mode": "byok_required",
            "cached_clients": factory.cache_size,
        }
    except Exception as e:
        logger.error(f"LLM health check failed: {e}")
        return {"status": "degraded", "message": str(e)}


def _check_agent() -> Dict[str, Any]:
    """Check LangGraph agent availability."""
    try:
        from src.services.agent.graph_builder import get_graph_builder

        builder = get_graph_builder()
        graph = builder.graph

        if graph is not None:
            return {
                "status": "healthy",
                "message": "Agent graph built",
                "nodes": ["respond", "execute_tool"],
            }
        return {
            "status": "degraded",
            "message": "Agent graph not built yet",
        }
    except Exception as e:
        logger.error(f"Agent health check failed: {e}")
        return {"status": "degraded", "message": str(e)}
