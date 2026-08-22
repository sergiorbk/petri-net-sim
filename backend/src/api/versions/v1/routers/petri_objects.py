"""Petri object catalog API endpoints - V1."""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.shared.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from src.api.shared.responses import ApiSuccessResponse
from src.api.shared.utils import success_response
from src.api.versions.v1.schemas.petri_objects import (
    PetriObjectCreateRequest,
    PetriObjectDetail,
    PetriObjectSummary,
    PetriObjectUpdateRequest,
)
from src.core.dependencies import get_current_user_optional, get_postgres_session
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.petri_object_repository import (
    PetriObjectRepository,
)

router = APIRouter(prefix="/petri-objects", tags=["petri-objects"])


def _to_summary(obj) -> PetriObjectSummary:
    return PetriObjectSummary(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        is_builtin=obj.is_builtin,
        updated_at=obj.updated_at.isoformat(),
    )


def _to_detail(obj) -> PetriObjectDetail:
    return PetriObjectDetail(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        is_builtin=obj.is_builtin,
        template_data=obj.template_data,
        preview_svg=obj.preview_svg,
        created_at=obj.created_at.isoformat(),
        updated_at=obj.updated_at.isoformat(),
    )


def _require_user(user: User | None) -> User:
    if user is None:
        raise UnauthorizedException(message="Authentication required")
    return user


@router.get(
    "",
    response_model=ApiSuccessResponse[list[PetriObjectSummary]],
    summary="List visible Petri objects",
)
async def list_petri_objects(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[list[PetriObjectSummary]]:
    repo = PetriObjectRepository(session)
    user_id = user.id if user is not None else None
    objects = await repo.list_visible(user_id)
    return success_response(data=[_to_summary(o) for o in objects], request=request)


@router.get(
    "/{object_id}",
    response_model=ApiSuccessResponse[PetriObjectDetail],
    summary="Get a Petri object",
)
async def get_petri_object(
    object_id: uuid.UUID,
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[PetriObjectDetail]:
    repo = PetriObjectRepository(session)
    user_id = user.id if user is not None else None
    obj = await repo.get_visible(object_id, user_id)
    if obj is None:
        raise NotFoundException(resource="PetriObject", identifier=str(object_id))
    return success_response(data=_to_detail(obj), request=request)


@router.post(
    "",
    response_model=ApiSuccessResponse[PetriObjectDetail],
    summary="Create a user-custom Petri object",
    status_code=201,
)
async def create_petri_object(
    body: PetriObjectCreateRequest,
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[PetriObjectDetail]:
    owner = _require_user(user)
    repo = PetriObjectRepository(session)

    existing = await repo.get_by_user_and_name(owner.id, body.name)
    if existing is not None:
        raise ConflictException(
            message=f"A Petri object named '{body.name}' already exists in your catalog."
        )

    obj = await repo.create_custom(
        user_id=owner.id,
        name=body.name,
        description=body.description,
        template_data=body.template_data,
        preview_svg=body.preview_svg,
    )
    await session.commit()
    await session.refresh(obj)
    return success_response(data=_to_detail(obj), request=request)


@router.put(
    "/{object_id}",
    response_model=ApiSuccessResponse[PetriObjectDetail],
    summary="Update a user-custom Petri object",
)
async def update_petri_object(
    object_id: uuid.UUID,
    body: PetriObjectUpdateRequest,
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[PetriObjectDetail]:
    owner = _require_user(user)
    repo = PetriObjectRepository(session)

    raw = await repo.get_raw(object_id)
    if raw is None:
        raise NotFoundException(resource="PetriObject", identifier=str(object_id))
    if raw.is_builtin:
        raise ForbiddenException(message="Built-in Petri objects are read-only.")
    if raw.user_id != owner.id:
        raise ForbiddenException(message="You do not own this Petri object.")

    if body.name is not None and body.name.lower() != raw.name.lower():
        conflict = await repo.get_by_user_and_name(owner.id, body.name)
        if conflict is not None and conflict.id != object_id:
            raise ConflictException(
                message=f"A Petri object named '{body.name}' already exists in your catalog."
            )

    updated = await repo.update_owned(
        object_id,
        owner.id,
        name=body.name,
        description=body.description,
        template_data=body.template_data,
        preview_svg=body.preview_svg,
    )
    if updated is None:
        raise NotFoundException(resource="PetriObject", identifier=str(object_id))
    await session.commit()
    await session.refresh(updated)
    return success_response(data=_to_detail(updated), request=request)


@router.delete(
    "/{object_id}",
    response_model=ApiSuccessResponse[dict],
    summary="Delete a user-custom Petri object",
)
async def delete_petri_object(
    object_id: uuid.UUID,
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[dict]:
    owner = _require_user(user)
    repo = PetriObjectRepository(session)

    raw = await repo.get_raw(object_id)
    if raw is None:
        raise NotFoundException(resource="PetriObject", identifier=str(object_id))
    if raw.is_builtin:
        raise ForbiddenException(message="Built-in Petri objects cannot be deleted.")
    if raw.user_id != owner.id:
        raise ForbiddenException(message="You do not own this Petri object.")

    deleted = await repo.delete_owned(object_id, owner.id)
    if not deleted:
        raise NotFoundException(resource="PetriObject", identifier=str(object_id))
    await session.commit()
    return success_response(data={"deleted": True}, request=request)
