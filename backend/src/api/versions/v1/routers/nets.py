"""User Petri net (workspace) API endpoints - V1."""

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.shared.exceptions import NotFoundException
from src.api.shared.pnml_export import net_data_pnml_response
from src.api.shared.responses import ApiSuccessResponse
from src.api.shared.utils import success_response
from src.api.versions.v1.schemas.nets import (
    NetShareRequest,
    NetShareResponse,
    NetThumbnailArc,
    NetThumbnailNode,
    SharedNetView,
    SortBy,
    UserNetCreateRequest,
    UserNetDetail,
    UserNetListResponse,
    UserNetSummary,
    UserNetUpdateRequest,
)
from src.core.dependencies import get_current_user, get_postgres_session
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.user_net_repository import (
    UserNetRepository,
)

router = APIRouter(prefix="/nets", tags=["user-nets"])


def _thumbnail(
    net_data: dict,
) -> tuple[list[NetThumbnailNode], list[NetThumbnailArc]]:
    """Extract node positions and arcs for gallery preview — O(n), no heavy processing."""
    nodes: list[NetThumbnailNode] = []
    for p in (net_data or {}).get("places", []):
        g = p.get("graphics", {})
        nodes.append(NetThumbnailNode(id=p["id"], type="place", x=g.get("x", 0), y=g.get("y", 0)))
    for t in (net_data or {}).get("transitions", []):
        g = t.get("graphics", {})
        nodes.append(NetThumbnailNode(id=t["id"], type="transition", x=g.get("x", 0), y=g.get("y", 0)))
    arcs = [
        NetThumbnailArc(source_id=a["source_id"], target_id=a["target_id"])
        for a in (net_data or {}).get("arcs", [])
    ]
    return nodes, arcs


def _to_summary(net) -> UserNetSummary:
    nodes, arcs = _thumbnail(net.net_data)
    return UserNetSummary(
        id=net.id,
        name=net.name,
        created_at=net.created_at.isoformat(),
        updated_at=net.updated_at.isoformat(),
        thumbnail=nodes,
        thumbnail_arcs=arcs,
        share_token=str(net.share_token),
        visibility=net.visibility,
    )


def _to_detail(net) -> UserNetDetail:
    nodes, arcs = _thumbnail(net.net_data)
    return UserNetDetail(
        id=net.id,
        name=net.name,
        net_data=net.net_data,
        origin_snapshot_id=net.origin_snapshot_id,
        created_at=net.created_at.isoformat(),
        updated_at=net.updated_at.isoformat(),
        thumbnail=nodes,
        thumbnail_arcs=arcs,
        share_token=str(net.share_token),
        visibility=net.visibility,
    )


def _to_shared_view(net) -> SharedNetView:
    nodes, arcs = _thumbnail(net.net_data)
    return SharedNetView(
        id=str(net.id),
        name=net.name,
        share_token=str(net.share_token),
        visibility=net.visibility,
        net_data=net.net_data,
        created_at=net.created_at.isoformat(),
        updated_at=net.updated_at.isoformat(),
        thumbnail=nodes,
        thumbnail_arcs=arcs,
    )



@router.get(
    "",
    response_model=ApiSuccessResponse[UserNetListResponse],
    summary="List user Petri nets",
)
async def list_user_nets(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: SortBy = Query(default="updated_at"),
) -> ApiSuccessResponse[UserNetListResponse]:
    repo = UserNetRepository(session)
    nets, has_more = await repo.list_by_user(user.id, limit=limit, offset=offset, sort_by=sort_by)
    return success_response(
        data=UserNetListResponse(items=[_to_summary(n) for n in nets], has_more=has_more),
        request=request,
    )


@router.get(
    "/shared/{share_token}",
    response_model=ApiSuccessResponse[SharedNetView],
    summary="Get a shared Petri net by share token (no auth required)",
)
async def get_shared_net(
    share_token: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[SharedNetView]:
    """Public read-only view of a net via its share token. Returns 404 for private nets."""
    repo = UserNetRepository(session)
    net = await repo.get_by_share_token(share_token)
    if net is None or net.visibility == "private":
        raise NotFoundException(resource="UserNet", identifier=str(share_token))
    return success_response(data=_to_shared_view(net), request=request)


@router.patch(
    "/{net_id}/share",
    response_model=ApiSuccessResponse[NetShareResponse],
    summary="Update sharing settings for a user Petri net",
)
async def share_user_net(
    net_id: uuid.UUID,
    body: NetShareRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[NetShareResponse]:
    repo = UserNetRepository(session)
    net = await repo.update_visibility(net_id, user.id, body.visibility)
    if net is None:
        raise NotFoundException(resource="UserNet", identifier=str(net_id))
    await session.commit()
    return success_response(
        data=NetShareResponse(share_token=str(net.share_token), visibility=net.visibility),
        request=request,
    )


@router.get(
    "/{net_id}",
    response_model=ApiSuccessResponse[UserNetDetail],
    summary="Get a user Petri net",
)
async def get_user_net(
    net_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[UserNetDetail]:
    repo = UserNetRepository(session)
    net = await repo.get_owned(net_id, user.id)
    if net is None:
        raise NotFoundException(resource="UserNet", identifier=str(net_id))
    return success_response(data=_to_detail(net), request=request)


@router.get(
    "/{net_id}/pnml",
    summary="Export a user Petri net as PNML",
)
async def get_user_net_pnml(
    net_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> Response:
    """Export the net as a downloadable PNML XML file -- composed dialect
    automatically when the net uses Petri-objects, same as the session
    route's own dialect selection."""
    repo = UserNetRepository(session)
    net = await repo.get_owned(net_id, user.id)
    if net is None:
        raise NotFoundException(resource="UserNet", identifier=str(net_id))
    return net_data_pnml_response(net.net_data or {}, net.name or str(net_id))


@router.post(
    "",
    response_model=ApiSuccessResponse[UserNetDetail],
    summary="Create a user Petri net",
    status_code=201,
)
async def create_user_net(
    body: UserNetCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[UserNetDetail]:
    repo = UserNetRepository(session)
    net = await repo.create_for_user(
        user_id=user.id,
        name=body.name,
        net_data=body.net_data,
        origin_snapshot_id=body.origin_snapshot_id,
    )
    await session.commit()
    await session.refresh(net)
    return success_response(data=_to_detail(net), request=request)


@router.put(
    "/{net_id}",
    response_model=ApiSuccessResponse[UserNetDetail],
    summary="Update a user Petri net",
)
async def update_user_net(
    net_id: uuid.UUID,
    body: UserNetUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[UserNetDetail]:
    repo = UserNetRepository(session)
    net = await repo.update_owned(
        net_id,
        user.id,
        name=body.name,
        net_data=body.net_data,
    )
    if net is None:
        raise NotFoundException(resource="UserNet", identifier=str(net_id))
    await session.commit()
    await session.refresh(net)
    return success_response(data=_to_detail(net), request=request)


@router.delete(
    "/{net_id}",
    response_model=ApiSuccessResponse[dict],
    summary="Delete a user Petri net",
)
async def delete_user_net(
    net_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[dict]:
    repo = UserNetRepository(session)
    deleted = await repo.delete_owned(net_id, user.id)
    if not deleted:
        raise NotFoundException(resource="UserNet", identifier=str(net_id))
    await session.commit()
    return success_response(data={"deleted": True}, request=request)
