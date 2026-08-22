"""Core application dependencies"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.shared.exceptions import ForbiddenException, UnauthorizedException
from src.core.auth_config import auth_settings
from src.infrastructure.postgres.database import get_postgres_session
from src.infrastructure.postgres.models.user import User
from src.services.auth import AuthService
from src.services.auth.api_key_service import ApiKeyService
from src.services.auth.integrations import HTTP_API, integration_enabled
from src.services.auth.jwt_service import get_jwt_service
from src.services.auth.local_user import ensure_local_user
from src.services.llm.llm_factory import LLMFactory, get_llm_factory

# Security scheme for Swagger UI
bearer_scheme = HTTPBearer(auto_error=False)

_INVALID_TOKEN_MSG = "Invalid or expired token"


@dataclass(frozen=True)
class AuthContext:
    """Authentication context carrying the user and optional API key hash."""

    user: User
    api_key_hash: str | None = None
    api_key_credential_id: UUID | None = None


def get_llm_provider() -> LLMFactory:
    """Get LLM factory instance."""
    return get_llm_factory()


async def get_auth_service(
    session: AsyncSession = Depends(get_postgres_session),
) -> AuthService:
    """Get auth service instance."""
    return AuthService(session)


async def get_current_user_from_request(
    request: Request,
    session: AsyncSession,
) -> User:
    """
    Extract and validate current user from request.

    Used internally by endpoints.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        if auth_settings.AUTH_MODE == "single_user":
            return await ensure_local_user(session)
        raise UnauthorizedException(message="Missing or invalid authorization header")

    token = auth_header.split(" ", 1)[1]

    auth_service = AuthService(session)
    user = await auth_service.get_current_user(token)

    if not user:
        if auth_settings.AUTH_MODE == "single_user":
            return await ensure_local_user(session)
        raise UnauthorizedException(message=_INVALID_TOKEN_MSG)

    return user


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: AsyncSession = Depends(get_postgres_session),
) -> User:
    """
    FastAPI dependency to get current authenticated user.

    Usage:
        @router.get("/protected")
        async def protected_endpoint(user: User = Depends(get_current_user)):
            ...
    """
    if not credentials:
        if auth_settings.AUTH_MODE == "single_user":
            return await ensure_local_user(session)
        raise UnauthorizedException(message="Missing authorization header")

    auth_service = AuthService(session)
    user = await auth_service.get_current_user(credentials.credentials)

    if not user:
        if auth_settings.AUTH_MODE == "single_user":
            return await ensure_local_user(session)
        raise UnauthorizedException(message=_INVALID_TOKEN_MSG)

    return user


async def get_current_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: AsyncSession = Depends(get_postgres_session),
) -> User | None:
    """
    FastAPI dependency to get current user if authenticated, None otherwise.

    Usage:
        @router.get("/optional-auth")
        async def endpoint(user: User | None = Depends(get_current_user_optional)):
            if user:
                # authenticated
            else:
                # anonymous
    """
    if not credentials:
        if auth_settings.AUTH_MODE == "single_user":
            return await ensure_local_user(session)
        return None

    auth_service = AuthService(session)
    user = await auth_service.get_current_user(credentials.credentials)
    if user:
        return user

    if auth_settings.AUTH_MODE == "single_user":
        return await ensure_local_user(session)
    return None


def get_current_user_id(user: User = Depends(get_current_user)) -> UUID:
    """
    FastAPI dependency to get current user ID.

    Usage:
        @router.get("/my-stuff")
        async def endpoint(user_id: UUID = Depends(get_current_user_id)):
            ...
    """
    return user.id


async def get_authenticated_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: AsyncSession = Depends(get_postgres_session),
) -> AuthContext:
    """
    FastAPI dependency supporting both JWT and API key authentication.

    - Tokens starting with 'sk-' are treated as API keys.
    - All other tokens are treated as JWT access tokens.

    Returns an AuthContext with the authenticated user and optional key hash.
    """
    if not credentials:
        if auth_settings.AUTH_MODE == "single_user":
            return AuthContext(user=await ensure_local_user(session), api_key_hash=None)
        raise UnauthorizedException(message="Missing authorization header")

    token = credentials.credentials

    if token.startswith("sk-"):
        api_key_service = ApiKeyService(session)
        result = await api_key_service.authenticate(token)
        if not result:
            if auth_settings.AUTH_MODE == "single_user":
                return AuthContext(user=await ensure_local_user(session), api_key_hash=None)
            raise UnauthorizedException(message="Invalid API key")
        return AuthContext(
            user=result.user,
            api_key_hash=result.key_hash,
            api_key_credential_id=result.llm_credential_id,
        )

    auth_service = AuthService(session)
    user = await auth_service.get_current_user(token)
    if not user:
        if auth_settings.AUTH_MODE == "single_user":
            return AuthContext(user=await ensure_local_user(session), api_key_hash=None)
        raise UnauthorizedException(message=_INVALID_TOKEN_MSG)

    return AuthContext(user=user, api_key_hash=None)


async def get_http_api_context(
    auth: AuthContext = Depends(get_authenticated_context),
) -> AuthContext:
    """Authentication for the OpenAI-compatible API, honouring the owner's switch.

    Only API-key callers are gated. The browser reaches the very same
    endpoints with a JWT, so gating every caller would make "stop programs
    from using my keys" also mean "stop my own chat from answering" --
    api_key_hash is what tells the two apart.
    """
    if auth.api_key_hash and not integration_enabled(auth.user, HTTP_API):
        raise ForbiddenException(
            message="API access is disabled for this account. Enable it in Settings > API."
        )
    return auth


__all__ = [
    "AuthContext",
    "get_postgres_session",
    "get_llm_provider",
    "get_auth_service",
    "get_current_user",
    "get_current_user_optional",
    "get_current_user_id",
    "get_current_user_from_request",
    "get_authenticated_context",
    "get_http_api_context",
]
