"""OpenAI-compatible API endpoints."""

import time
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.openai_api.v1.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelListResponse,
    ModelObject,
    OpenAIErrorDetail,
    OpenAIErrorResponse,
)
from src.api.shared.rate_limit import rate_limit
from src.core.config import settings
from src.core.dependencies import AuthContext, get_http_api_context, get_postgres_session
from src.core.logger import get_logger
from src.core.security_config import security_settings
from src.services.agent.nodes.chat_node import DEFAULT_NET_STYLE
from src.services.chat.file_service import FileService
from src.services.chat.openai_chat_service import MODEL_ID, OpenAIChatService
from src.services.llm.credential_service import CredentialService
from src.services.llm.credentials_resolver import (
    ByokRequiredError,
    CredentialsResolver,
    InvalidCredentialError,
)

logger = get_logger()

router = APIRouter(tags=["OpenAI Compatible"])

# Per-credential rate limit on the (expensive) chat completion endpoint.
_chat_rate_limit = rate_limit(
    "chat",
    security_settings.RATE_LIMIT_CHAT_MAX,
    security_settings.RATE_LIMIT_CHAT_WINDOW,
    by="token",
)


# ------------------------------------------------------------------
# POST /chat/completions
# ------------------------------------------------------------------


def _build_resolver(session: AsyncSession) -> CredentialsResolver:
    """Build a resolver scoped to this request's DB session."""
    return CredentialsResolver(CredentialService(session))


_VALID_NET_STYLES = {"object", "classical"}


def _resolve_net_style(metadata: dict[str, str] | None) -> str:
    """Petri Net Sim extension: which net style this turn asked the agent
    to build in, from the chat workbench's NetStyleToggle (metadata.net_style)
    -- see chat_node.DEFAULT_NET_STYLE/_NET_STYLE_NOTES for how it changes
    the system prompt. Falls back to the default for a missing or unknown
    value rather than rejecting the request outright, matching how
    metadata.llm_credential_id degrades (a generic OpenAI-compatible
    client sending neither key must still get a normal, working response."""
    if not metadata:
        return DEFAULT_NET_STYLE
    value = metadata.get("net_style")
    return value if value in _VALID_NET_STYLES else DEFAULT_NET_STYLE


DEFAULT_AGENT_EFFORT = "standard"
_AGENT_EFFORT_RECURSION_LIMITS = {
    "standard": lambda: settings.AGENT_RECURSION_LIMIT,
    "thorough": lambda: settings.AGENT_RECURSION_LIMIT_THOROUGH,
    # What the chat workbench sends when its iteration limit is switched
    # off, which is the default there.
    "uncapped": lambda: settings.AGENT_RECURSION_LIMIT_UNCAPPED,
}


def _resolve_recursion_limit(metadata: dict[str, str] | None) -> int:
    """Petri Net Sim extension: how much agent tool-call budget this turn
    gets, from the chat workbench's EffortToggle (metadata.agent_effort) --
    "Standard" (AGENT_RECURSION_LIMIT), "Thorough"
    (AGENT_RECURSION_LIMIT_THOROUGH, a larger budget for bigger composed
    builds), or "uncapped" (AGENT_RECURSION_LIMIT_UNCAPPED, the backstop
    used when the workbench's iteration limit is off).

    Falls back to Standard for a MISSING value rather than to uncapped:
    a plain OpenAI-compatible client that sends no metadata at all has not
    asked for an unbounded run, and should not get one. Read fresh via the
    settings object (not captured at import time) so both tiers stay
    live-configurable by an operator without a restart-triggering code
    change.
    """
    value = (metadata or {}).get("agent_effort")
    resolver = _AGENT_EFFORT_RECURSION_LIMITS.get(value, _AGENT_EFFORT_RECURSION_LIMITS[DEFAULT_AGENT_EFFORT])
    return resolver()


DEFAULT_LAYOUT_DIRECTION = "LR"
_VALID_LAYOUT_DIRECTIONS = {"LR", "TB"}


def _resolve_layout_direction(metadata: dict[str, str] | None) -> str:
    """Petri Net Sim extension: which way the net this turn builds should
    flow, from the chat workbench's DirectionToggle
    (metadata.layout_direction). "LR" grows the net left to right with
    parallel steps stacked underneath each other; "TB" is the same layout
    turned a quarter turn.

    These are the domain layout engine's own tokens (domain/layout/sugiyama
    takes direction="LR"|"TB"), passed straight through. The value never
    reaches the LLM: tool_node applies it to the session's builders, which
    re-run Sugiyama, so coordinates stay computed rather than invented --
    see catalog.py, which strips x/y from every pattern tool's schema.

    Falls back to the default for a missing or unknown value, same
    degrade-gracefully rule as _resolve_net_style.
    """
    if not metadata:
        return DEFAULT_LAYOUT_DIRECTION
    value = metadata.get("layout_direction")
    return value if value in _VALID_LAYOUT_DIRECTIONS else DEFAULT_LAYOUT_DIRECTION


@router.post(
    "/chat/completions",
    response_model=ChatCompletionResponse,
    response_model_exclude_none=True,
    dependencies=[Depends(_chat_rate_limit)],
)
async def chat_completions(
    body: ChatCompletionRequest,
    auth: AuthContext = Depends(get_http_api_context),
    session: AsyncSession = Depends(get_postgres_session),
):
    """
    OpenAI-compatible chat completion endpoint.

    Supports both streaming (stream=true) and non-streaming modes.

    Credentials are resolved before any agent invocation (BYOK-only):
      - ``metadata.llm_credential_id`` → BYOK using the user's profile.
      - missing → 402 byok_required.
    """
    resolver = _build_resolver(session)
    try:
        resolved = await resolver.resolve(
            auth.user,
            body.metadata,
            api_key_credential_id=auth.api_key_credential_id,
        )
    except ByokRequiredError as e:
        return _byok_required_error(str(e))
    except InvalidCredentialError as e:
        return _openai_error(400, str(e), "invalid_credential")
    except Exception as e:
        logger.error(f"Credential resolution failed: {e}", exc_info=True)
        return _openai_error(500, "Credential resolution failed", "server_error")

    service = OpenAIChatService(session)
    net_style = _resolve_net_style(body.metadata)
    recursion_limit = _resolve_recursion_limit(body.metadata)
    layout_direction = _resolve_layout_direction(body.metadata)

    try:
        if body.stream:
            include_usage = (
                body.stream_options.include_usage
                if body.stream_options
                else False
            )
            generator = service.complete_stream(
                messages=body.messages,
                user_id=auth.user.id,
                resolved=resolved,
                api_key_hash=auth.api_key_hash,
                max_tokens=body.max_tokens,
                include_usage=include_usage,
                net_style=net_style,
                layout_direction=layout_direction,
                recursion_limit=recursion_limit,
            )
            return StreamingResponse(
                generator,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        response = await service.complete(
            messages=body.messages,
            user_id=auth.user.id,
            resolved=resolved,
            api_key_hash=auth.api_key_hash,
            max_tokens=body.max_tokens,
            net_style=net_style,
            layout_direction=layout_direction,
            recursion_limit=recursion_limit,
        )
        return response

    except Exception as e:
        logger.error(f"Chat completion error: {e}", exc_info=True)
        return _openai_error(500, "An internal error occurred", "server_error")


# ------------------------------------------------------------------
# GET /models
# ------------------------------------------------------------------


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    auth: AuthContext = Depends(get_http_api_context),
):
    """List available models."""
    return ModelListResponse(
        data=[
            ModelObject(
                id=MODEL_ID,
                created=int(time.time()),
                owned_by="petri-net-sim",
            )
        ]
    )


# ------------------------------------------------------------------
# GET /files/{file_id}
# ------------------------------------------------------------------


@router.get("/files/{file_id}")
async def download_file(
    file_id: str,
    token: str | None = Query(
        None,
        description="Signed download token (emitted in chat download links).",
    ),
    session: AsyncSession = Depends(get_postgres_session),
):
    """
    Download a generated PNML file.

    Authorization is performed via a signed ?token query parameter so that
    download links can be opened directly in a browser (where the Authorization
    header is not available). The token is single-purpose (type=download),
    short-lived, and bound to the specific file_id and user_id.
    """
    try:
        parsed_id = UUID(file_id)
    except ValueError:
        return _openai_error(400, "Invalid file ID format", "invalid_request_error")

    if not token:
        return _openai_error(401, "Missing download token", "authentication_error")

    from src.services.auth.jwt_service import get_jwt_service

    claims = get_jwt_service().verify_download_token(token)
    if not claims:
        return _openai_error(401, "Invalid or expired download token", "authentication_error")

    token_file_id, token_user_id = claims
    if token_file_id != parsed_id:
        return _openai_error(403, "Token does not match this file", "permission_error")

    file_service = FileService(session)
    generated_file = await file_service.get_file(parsed_id, token_user_id)

    if not generated_file:
        return _openai_error(404, "File not found or expired", "not_found")

    if generated_file.content_type in {"image/png", "application/zip"}:
        from src.services.training_export import attachment
        return attachment(FileService.download_bytes(generated_file), generated_file.filename, generated_file.content_type)
    return Response(
        content=generated_file.content,
        media_type=generated_file.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{generated_file.filename}"',
        },
    )


# ------------------------------------------------------------------
# Error helpers
# ------------------------------------------------------------------


def _openai_error(
    status_code: int,
    message: str,
    error_type: str = "invalid_request_error",
    code: str | None = None,
    extra: dict | None = None,
) -> JSONResponse:
    body = OpenAIErrorResponse(
        error=OpenAIErrorDetail(
            message=message,
            type=error_type,
            code=code,
        )
    )
    payload = body.model_dump()
    if extra:
        payload["error"].update(extra)
    return JSONResponse(status_code=status_code, content=payload)


def _byok_required_error(message: str) -> JSONResponse:
    return _openai_error(
        status_code=402,
        message=message,
        error_type="byok_required",
        code="byok_required",
    )
