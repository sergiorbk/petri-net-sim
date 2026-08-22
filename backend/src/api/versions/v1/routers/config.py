"""Public runtime configuration endpoint - V1.

Exposes non-secret settings the frontend needs before any authentication
happens: whether the server is running in single-user, no-login mode, so
the auth store can decide whether to bother reading stored tokens at all,
and which machine-facing entry points this deployment actually serves, so
Settings can print connection details that are true of this server rather
than of the defaults.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from src.api.shared.responses import ApiSuccessResponse
from src.api.shared.utils import success_response
from src.core.auth_config import auth_settings
from src.core.config import settings
from src.core.oauth_config import oauth_settings

router = APIRouter(tags=["config"])

# Where the OpenAI-compatible router lands: "/api" (router_registry) plus the
# router's own "/v1" prefix (src.openai_api.get_openai_v1_router). Spelled out
# here because the frontend has to print the base URL a client should be
# pointed at, and neither prefix is reachable from settings.
HTTP_API_BASE_PATH = "/api/v1"


def _configured_oauth_providers() -> list[str]:
    """Which external sign-ins actually have credentials behind them.

    A provider without a client id and secret answers every authorize call
    with an error, so offering its button is offering a dead end. The names
    are the ones in the route paths (/auth/oauth/<name>/authorize), which is
    what the frontend needs to build the request.
    """
    providers = []
    if oauth_settings.google_enabled:
        providers.append("google")
    return providers


class PublicConfigResponse(BaseModel):
    """Public, secret-free runtime configuration."""

    auth_mode: str = Field(
        description='"multi" (accounts required) or "single_user" (no login, one local account)'
    )
    oauth_providers: list[str] = Field(
        description="External sign-in providers this deployment has credentials for. "
        "Empty when none are configured, and the login screen then offers none."
    )
    mcp_enabled: bool = Field(
        description="Whether this deployment serves the MCP endpoint at all"
    )
    mcp_path: str = Field(description="Path the MCP endpoint is mounted at, e.g. /mcp")
    http_api_enabled: bool = Field(
        description="Whether this deployment serves the OpenAI-compatible HTTP API"
    )
    http_api_path: str = Field(
        description="Base path of the OpenAI-compatible HTTP API, e.g. /api/v1"
    )
    openapi_url: str | None = Field(
        description="Path to the OpenAPI schema, or null where docs are switched off"
    )
    docs_url: str | None = Field(
        description="Path to the interactive API docs, or null where docs are switched off"
    )


@router.get(
    "/config",
    response_model=ApiSuccessResponse[PublicConfigResponse],
    summary="Get public runtime configuration",
)
async def get_config(request: Request) -> ApiSuccessResponse[PublicConfigResponse]:
    """Return non-secret runtime configuration. Unauthenticated by design --
    the frontend needs this before it knows whether it has (or needs) a
    session at all."""
    return success_response(
        data=PublicConfigResponse(
            auth_mode=auth_settings.AUTH_MODE,
            oauth_providers=_configured_oauth_providers(),
            mcp_enabled=settings.MCP_ENABLED,
            mcp_path=settings.MCP_PATH,
            http_api_enabled=settings.OPENAI_ENABLED,
            http_api_path=HTTP_API_BASE_PATH,
            openapi_url="/openapi.json" if settings.docs_enabled else None,
            docs_url="/docs" if settings.docs_enabled else None,
        ),
        request=request,
    )
