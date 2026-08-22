"""
Centralized router registry.
Import this module to include all API routers at once.
"""

from datetime import datetime

from fastapi import FastAPI

from .routers.health import router as health_router
from .version_manager import VersionStatus, version_manager
from .versions import v1_router


def register_versions() -> None:
    """
    Register all API versions with the version manager.

    This configures version lifecycle information, deprecation dates,
    and documentation links for each API version.
    """
    # Register V1 - Initial stable version
    version_manager.register_version(
        "v1",
        status=VersionStatus.STABLE,
        release_date=datetime(2026, 1, 1),
        documentation_url="/docs",
        changelog_url="/docs#v1-changelog",
    )

    # Example: Register V2 when ready
    # version_manager.register_version(
    #     "v2",
    #     status=VersionStatus.BETA,
    #     release_date=datetime(2024, 6, 1),
    #     documentation_url="/docs/v2",
    # )

    # Example: Deprecate V1 when V2 is stable
    # version_manager.register_version(
    #     "v1",
    #     status=VersionStatus.DEPRECATED,
    #     release_date=datetime(2024, 1, 1),
    #     deprecation_date=datetime(2024, 6, 1),
    #     sunset_date=datetime(2025, 1, 1),
    #     documentation_url="/docs/v1",
    # )


def register_routers(app: FastAPI) -> None:
    """
    Register all API routers to the FastAPI application.

    Health endpoints are always registered.
    OpenAI-compatible API endpoints are conditional on OPENAI_ENABLED.

    Args:
        app: FastAPI application instance
    """
    from src.core.config import settings

    # Register version information
    register_versions()

    # Health check endpoints (always registered, no versioning)
    app.include_router(health_router)

    # Common API routers (auth, user management) — always registered
    app.include_router(v1_router, prefix="/api")

    # OpenAI-compatible API routers — conditional
    if settings.OPENAI_ENABLED:
        from src.openai_api import get_openai_v1_router

        app.include_router(get_openai_v1_router(), prefix="/api")


__all__ = ["register_routers"]
