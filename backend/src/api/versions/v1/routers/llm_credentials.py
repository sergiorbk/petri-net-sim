"""CRUD endpoints for user-owned BYOK LLM credential profiles."""

from uuid import UUID as _UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.shared.exceptions import (
    ConflictException,
    NotFoundException,
    ValidationException,
)
from src.api.shared.responses import ApiSuccessResponse
from src.api.shared.utils import success_response
from src.api.versions.v1.schemas.llm_credentials import (
    CreateLLMCredentialRequest,
    LLMCredentialResponse,
    TestLLMCredentialResponse,
    UpdateLLMCredentialRequest,
)
from src.api.shared.rate_limit import rate_limit
from src.core.dependencies import get_current_user, get_postgres_session
from src.core.security_config import security_settings
from src.infrastructure.postgres.models.user import User
from src.services.llm.credential_service import (
    CredentialAlreadyExistsError,
    CredentialNotFoundError,
    CredentialService,
)

router = APIRouter(prefix="/llm-credentials", tags=["llm-credentials"])

_RESOURCE_NAME = "LLM credential"

# Per-credential rate limit for mutating / LLM-invoking endpoints (create, test).
_credentials_rate_limit = rate_limit(
    "llm_credentials",
    security_settings.RATE_LIMIT_CREDENTIALS_MAX,
    security_settings.RATE_LIMIT_CREDENTIALS_WINDOW,
    by="token",
)


def _service(session: AsyncSession) -> CredentialService:
    return CredentialService(session)


@router.post(
    "",
    response_model=ApiSuccessResponse[LLMCredentialResponse],
    summary="Create a new BYOK credential profile",
    dependencies=[Depends(_credentials_rate_limit)],
)
async def create_credential(
    data: CreateLLMCredentialRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[LLMCredentialResponse]:
    """Persist a credential profile. The raw API key is encrypted at rest."""
    try:
        data.require_key_for_provider()
    except ValueError as e:
        raise ValidationException(message=str(e))

    service = _service(session)
    try:
        row = await service.create(
            user_id=user.id,
            name=data.name,
            provider=data.provider,
            model=data.model,
            api_key=data.api_key,
            base_url=str(data.base_url) if data.base_url else None,
        )
    except CredentialAlreadyExistsError as e:
        raise ConflictException(message=str(e))

    return success_response(
        data=LLMCredentialResponse(**service.to_response_dict(row)),
        request=request,
    )


@router.get(
    "",
    response_model=ApiSuccessResponse[list[LLMCredentialResponse]],
    summary="List the current user's credential profiles",
)
async def list_credentials(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[list[LLMCredentialResponse]]:
    service = _service(session)
    rows = await service.list_for_user(user.id)
    items = [LLMCredentialResponse(**service.to_response_dict(r)) for r in rows]
    return success_response(data=items, request=request)


@router.get(
    "/{credential_id}",
    response_model=ApiSuccessResponse[LLMCredentialResponse],
    summary="Fetch a single credential profile",
)
async def get_credential(
    credential_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[LLMCredentialResponse]:
    parsed_id = _parse_uuid(credential_id)
    service = _service(session)
    try:
        row = await service.get_for_user(parsed_id, user.id)
    except CredentialNotFoundError:
        raise NotFoundException(resource=_RESOURCE_NAME, identifier=credential_id)

    return success_response(
        data=LLMCredentialResponse(**service.to_response_dict(row)),
        request=request,
    )


@router.patch(
    "/{credential_id}",
    response_model=ApiSuccessResponse[LLMCredentialResponse],
    summary="Update a credential profile (partial)",
)
async def update_credential(
    credential_id: str,
    data: UpdateLLMCredentialRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[LLMCredentialResponse]:
    parsed_id = _parse_uuid(credential_id)
    service = _service(session)
    try:
        row = await service.update(
            parsed_id,
            user.id,
            name=data.name,
            api_key=data.api_key,
            base_url=str(data.base_url) if data.base_url else None,
            model=data.model,
        )
    except CredentialNotFoundError:
        raise NotFoundException(resource=_RESOURCE_NAME, identifier=credential_id)
    except CredentialAlreadyExistsError as e:
        raise ConflictException(message=str(e))

    return success_response(
        data=LLMCredentialResponse(**service.to_response_dict(row)),
        request=request,
    )


@router.delete(
    "/{credential_id}",
    response_model=ApiSuccessResponse[dict],
    summary="Soft-delete a credential profile",
)
async def delete_credential(
    credential_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[dict]:
    parsed_id = _parse_uuid(credential_id)
    service = _service(session)
    try:
        await service.delete(parsed_id, user.id)
    except CredentialNotFoundError:
        raise NotFoundException(resource=_RESOURCE_NAME, identifier=credential_id)

    return success_response(data={"deleted": True}, request=request)


@router.post(
    "/{credential_id}/test",
    response_model=ApiSuccessResponse[TestLLMCredentialResponse],
    summary="Send a ping completion to verify the credential",
    dependencies=[Depends(_credentials_rate_limit)],
)
async def test_credential(
    credential_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[TestLLMCredentialResponse]:
    parsed_id = _parse_uuid(credential_id)
    service = _service(session)
    try:
        success, latency_ms, preview, error = await service.test(parsed_id, user.id)
    except CredentialNotFoundError:
        raise NotFoundException(resource=_RESOURCE_NAME, identifier=credential_id)

    return success_response(
        data=TestLLMCredentialResponse(
            success=success,
            latency_ms=latency_ms,
            model_response_preview=preview,
            error=error,
        ),
        request=request,
    )


def _parse_uuid(raw: str) -> _UUID:
    try:
        return _UUID(raw)
    except ValueError:
        raise ValidationException(message=f"Invalid credential ID: {raw!r}")
