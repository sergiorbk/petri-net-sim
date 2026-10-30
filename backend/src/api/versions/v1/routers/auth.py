"""Authentication API endpoints - V1."""

import secrets
from urllib.parse import urlencode
from uuid import UUID as _UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.shared.rate_limit import rate_limit
from src.core.auth_config import auth_settings
from src.core.config import settings
from src.core.security_config import security_settings

from src.api.shared.exceptions import (
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
    ValidationException,
)
from src.api.shared.responses import ApiSuccessResponse
from src.api.shared.utils import success_response
from src.api.versions.v1.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListItem,
    LoginRequest,
    OAuthAuthorizeResponse,
    RefreshTokenRequest,
    SignupRequest,
    TokenPairResponse,
    UpdateProfileRequest,
    UserResponse,
)
from src.core.dependencies import get_current_user, get_postgres_session
from src.core.oauth_config import oauth_settings
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories import UserRepository
from src.services.auth.api_key_service import ApiKeyService
from src.services.auth.auth_service import AuthService
from src.services.auth.integrations import HTTP_API, MCP, apply_integration
from src.services.auth.jwt_service import get_jwt_service
from src.services.auth.local_user import LOCAL_USER_EMAIL
from src.services.auth.oauth_manager import OAuthManager
from src.services.auth.oauth_service import GoogleOAuthProvider

router = APIRouter(prefix="/auth", tags=["auth"])

# Rate-limit dependencies. Unauthenticated endpoints are keyed per-IP (with the
# trusted-proxy policy applied); authenticated ones per-credential.
_signup_rate_limit = rate_limit(
    "auth_signup",
    settings.AUTH_RATE_LIMIT_SIGNUP_MAX,
    settings.AUTH_RATE_LIMIT_SIGNUP_WINDOW,
    by="ip",
)
_login_rate_limit = rate_limit(
    "auth_login",
    settings.AUTH_RATE_LIMIT_LOGIN_MAX,
    settings.AUTH_RATE_LIMIT_LOGIN_WINDOW,
    by="ip",
)
_refresh_rate_limit = rate_limit(
    "auth_refresh",
    security_settings.RATE_LIMIT_REFRESH_MAX,
    security_settings.RATE_LIMIT_REFRESH_WINDOW,
    by="ip",
)
_oauth_rate_limit = rate_limit(
    "auth_oauth",
    security_settings.RATE_LIMIT_OAUTH_MAX,
    security_settings.RATE_LIMIT_OAUTH_WINDOW,
    by="ip",
)
_api_keys_rate_limit = rate_limit(
    "auth_api_keys",
    security_settings.RATE_LIMIT_API_KEYS_MAX,
    security_settings.RATE_LIMIT_API_KEYS_WINDOW,
    by="token",
)


_SINGLE_USER_MODE_MSG = (
    "Account creation and login are disabled in single-user mode: this "
    "server has no accounts, every request already runs as the local user."
)

_RESERVED_EMAIL_MSG = (
    "This email address is reserved for the built-in local account and "
    "cannot be used to sign up."
)


def _reject_reserved_email(email: str) -> None:
    """Refuse signup at the fixed single-user-mode email, in every auth mode.

    A deployment that only ever expects to run in single_user mode is
    still reachable in multi mode up until the switch is made -- so
    without this check, anyone could register LOCAL_USER_EMAIL ahead of
    time and have ensure_local_user() (services/auth/local_user.py) treat
    that row as the trusted local account later. Checked unconditionally,
    before the multi-user-mode gate, so the email stays unavailable
    regardless of which mode is active when the attempt is made.
    """
    if email.strip().lower() == LOCAL_USER_EMAIL.lower():
        raise ValidationException(message=_RESERVED_EMAIL_MSG)


def _require_multi_user_mode() -> None:
    """Reject account-creation/login endpoints when AUTH_MODE=single_user.

    Single-user mode has exactly one, non-login account (see
    src/services/auth/local_user.py); minting new accounts or issuing
    password/OAuth sessions for it would just be a confusing way to reach
    the same user every unauthenticated request already gets.
    """
    if auth_settings.AUTH_MODE == "single_user":
        raise ForbiddenException(message=_SINGLE_USER_MODE_MSG)


def _token_pair_response(access: str, refresh: str) -> TokenPairResponse:
    jwt_service = get_jwt_service()
    return TokenPairResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=jwt_service._access_token_expire_minutes * 60,
    )


# --- Password Auth ---


@router.post(
    "/signup",
    response_model=ApiSuccessResponse[TokenPairResponse],
    summary="Register a new user with email and password",
    dependencies=[Depends(_signup_rate_limit)],
)
async def signup(
    data: SignupRequest,
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[TokenPairResponse]:
    """Create a new account with email + password and return a JWT token pair."""
    _reject_reserved_email(data.email)
    _require_multi_user_mode()
    service = AuthService(session)
    try:
        _user, access, refresh = await service.register_with_password(
            email=data.email,
            password=data.password,
            name=data.name,
        )
    except ValueError as e:
        raise ValidationException(message=str(e))

    return success_response(data=_token_pair_response(access, refresh), request=request)


@router.post(
    "/login",
    response_model=ApiSuccessResponse[TokenPairResponse],
    summary="Log in with email and password",
    dependencies=[Depends(_login_rate_limit)],
)
async def login(
    data: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[TokenPairResponse]:
    """Exchange email + password for a JWT token pair."""
    _require_multi_user_mode()
    service = AuthService(session)
    result = await service.authenticate_credentials(data.email, data.password)
    if not result:
        raise UnauthorizedException(message="Invalid credentials")

    _user, access, refresh = result
    return success_response(data=_token_pair_response(access, refresh), request=request)


# --- User Endpoints ---


@router.get(
    "/me",
    response_model=ApiSuccessResponse[UserResponse],
    summary="Get current user info",
)
async def get_me(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[UserResponse]:
    """Get current authenticated user info.

    Requires Bearer token (API key or JWT) in Authorization header.
    """
    from src.core.dependencies import get_current_user_from_request

    user = await get_current_user_from_request(request, session)
    return success_response(data=UserResponse.from_user(user), request=request)


@router.patch(
    "/me",
    response_model=ApiSuccessResponse[UserResponse],
    summary="Update current user profile",
)
async def update_me(
    data: UpdateProfileRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[UserResponse]:
    """Update the authenticated user's profile fields."""
    user_repo = UserRepository(session)

    meta = dict(user.metadata_ or {})
    fields_set = data.model_fields_set
    if data.contributor is not None:
        meta["contributor"] = {**meta.get("contributor", {}), **{k: v.strip() for k, v in data.contributor.items()}}

    if "display_name" in fields_set:
        if data.display_name:
            meta["display_name"] = data.display_name
        else:
            meta.pop("display_name", None)

    if "work_type" in fields_set:
        if data.work_type:
            meta["work_type"] = data.work_type
        else:
            meta.pop("work_type", None)

    if "custom_instructions" in fields_set:
        if data.custom_instructions:
            meta["custom_instructions"] = data.custom_instructions
        else:
            meta.pop("custom_instructions", None)

    # Integration switches are tri-state on the wire (absent = leave alone),
    # boolean in storage -- unlike the text fields above, False is a value to
    # write and not an instruction to clear the key.
    if "mcp_enabled" in fields_set and data.mcp_enabled is not None:
        apply_integration(meta, MCP, data.mcp_enabled)

    if "http_api_enabled" in fields_set and data.http_api_enabled is not None:
        apply_integration(meta, HTTP_API, data.http_api_enabled)

    updated = await user_repo.update(
        user,
        name=data.name if "name" in fields_set else None,
        metadata=meta,
    )
    # UserRepository.update only flushes, and the session dependency does not
    # commit on the way out (see infrastructure/postgres/database.py), so
    # without this the reply describes a change that is rolled back the moment
    # the request ends -- which is how display_name, work_type and
    # custom_instructions came to report success and then not persist.
    await session.commit()
    return success_response(data=UserResponse.from_user(updated), request=request)


# --- API Key Endpoints ---


@router.post(
    "/api-keys",
    response_model=ApiSuccessResponse[ApiKeyCreateResponse],
    summary="Create a new API key",
    dependencies=[Depends(_api_keys_rate_limit)],
)
async def create_api_key(
    data: ApiKeyCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[ApiKeyCreateResponse]:
    """Create a new API key for the authenticated user.

    The raw key is returned only once — store it securely.
    """
    service = ApiKeyService(session)
    try:
        raw_key, key_id = await service.create_key(
            user.id,
            name=data.name,
            llm_credential_id=data.llm_credential_id,
        )
    except ValueError as e:
        raise ValidationException(message=str(e))

    return success_response(
        data=ApiKeyCreateResponse(
            id=key_id,
            key=raw_key,
            name=data.name,
            llm_credential_id=data.llm_credential_id,
        ),
        request=request,
    )


@router.get(
    "/api-keys",
    response_model=ApiSuccessResponse[list[ApiKeyListItem]],
    summary="List API keys",
)
async def list_api_keys(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[list[ApiKeyListItem]]:
    """List all API keys for the authenticated user."""
    service = ApiKeyService(session)
    keys = await service.list_keys(user.id)
    items = [ApiKeyListItem(**k) for k in keys]
    return success_response(data=items, request=request)


@router.delete(
    "/api-keys/{key_id}",
    response_model=ApiSuccessResponse[dict],
    summary="Revoke an API key",
)
async def revoke_api_key(
    key_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[dict]:
    """Revoke (deactivate) an API key."""
    try:
        parsed_id = _UUID(key_id)
    except ValueError:
        raise ValidationException(message="Invalid key ID format")

    service = ApiKeyService(session)
    revoked = await service.revoke_key(parsed_id, user.id)

    if not revoked:
        raise NotFoundException(resource="API key", identifier=key_id)

    return success_response(data={"revoked": True}, request=request)


# --- OAuth Endpoints ---


@router.get(
    "/oauth/google/authorize",
    response_model=ApiSuccessResponse[OAuthAuthorizeResponse],
    summary="Get Google OAuth authorization URL",
    dependencies=[Depends(_oauth_rate_limit)],
)
async def google_authorize(
    request: Request,
) -> ApiSuccessResponse[OAuthAuthorizeResponse]:
    """Generate a Google OAuth authorization URL for the frontend to redirect to."""
    _require_multi_user_mode()
    if not oauth_settings.google_enabled:
        raise ValidationException(message="Google OAuth is not configured")

    jwt_service = get_jwt_service()
    state = jwt_service.create_access_token(
        user_id=_UUID(int=0),
        email="oauth-state",
        additional_claims={"type": "oauth_state", "nonce": secrets.token_urlsafe(16)},
    )

    provider = GoogleOAuthProvider()
    url = provider.get_authorization_url(state)

    return success_response(data=OAuthAuthorizeResponse(url=url), request=request)


@router.get(
    "/oauth/google/callback",
    summary="Google OAuth callback",
    response_class=RedirectResponse,
    dependencies=[Depends(_oauth_rate_limit)],
)
async def google_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="CSRF state parameter"),
    session: AsyncSession = Depends(get_postgres_session),
) -> RedirectResponse:
    """Handle the Google OAuth callback, exchange code for tokens, and redirect to frontend."""
    frontend_url = oauth_settings.OAUTH_FRONTEND_CALLBACK_URL

    if auth_settings.AUTH_MODE == "single_user":
        return RedirectResponse(
            url=f"{frontend_url}#error=disabled_in_single_user_mode",
            status_code=302,
        )

    # Validate state
    jwt_service = get_jwt_service()
    state_payload = jwt_service.verify_token(state)
    if not state_payload or state_payload.get("type") != "oauth_state":
        return RedirectResponse(
            url=f"{frontend_url}#error=invalid_state",
            status_code=302,
        )

    try:
        provider = GoogleOAuthProvider()
        user_info = await provider.exchange_code(code)

        manager = OAuthManager(session)
        _user, access_token, refresh_token = await manager.authenticate(user_info)

        params = urlencode({
            "access_token": access_token,
            "refresh_token": refresh_token,
        })
        return RedirectResponse(
            url=f"{frontend_url}#{params}",
            status_code=302,
        )
    except PermissionError as e:
        return RedirectResponse(
            url=f"{frontend_url}#error={str(e)}",
            status_code=302,
        )
    except Exception:
        return RedirectResponse(
            url=f"{frontend_url}#error=authentication_failed",
            status_code=302,
        )


# --- Token Refresh ---


@router.post(
    "/refresh",
    response_model=ApiSuccessResponse[TokenPairResponse],
    summary="Refresh access token",
    dependencies=[Depends(_refresh_rate_limit)],
)
async def refresh_token(
    data: RefreshTokenRequest,
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[TokenPairResponse]:
    """Exchange a valid refresh token for a new token pair."""
    _require_multi_user_mode()
    jwt_service = get_jwt_service()
    payload = jwt_service.verify_refresh_token(data.refresh_token)

    if not payload:
        raise UnauthorizedException(message="Invalid or expired refresh token")

    try:
        user_id = _UUID(payload["sub"])
    except (KeyError, ValueError):
        raise UnauthorizedException(message="Invalid refresh token payload")

    from src.infrastructure.postgres.repositories import UserRepository

    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)

    if not user or not user.is_active:
        raise UnauthorizedException(message="User not found or inactive")

    access_token, new_refresh_token = jwt_service.create_token_pair(
        user_id=user.id,
        email=user.email,
    )

    return success_response(
        data=TokenPairResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=jwt_service._access_token_expire_minutes * 60,
        ),
        request=request,
    )
