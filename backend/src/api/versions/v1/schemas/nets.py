"""Pydantic schemas for the /nets endpoints."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SortBy = Literal["updated_at", "created_at"]


class NetThumbnailNode(BaseModel):
    """Minimal node descriptor for gallery previews — position only, no names."""

    id: str
    type: Literal["place", "transition"]
    x: float
    y: float


class NetThumbnailArc(BaseModel):
    """Minimal arc descriptor for gallery previews."""

    source_id: str
    target_id: str


class UserNetSummary(BaseModel):
    """Minimal net descriptor used in the list endpoint."""

    id: uuid.UUID
    name: str
    created_at: str
    updated_at: str
    thumbnail: list[NetThumbnailNode] = Field(default_factory=list)
    thumbnail_arcs: list[NetThumbnailArc] = Field(default_factory=list)
    share_token: str = Field(default="")
    visibility: str = Field(default="private")

    model_config = ConfigDict(from_attributes=True)


class UserNetListResponse(BaseModel):
    """Paginated list of net summaries."""

    items: list[UserNetSummary]
    has_more: bool


class UserNetDetail(UserNetSummary):
    """Full net payload including serialized net_data."""

    net_data: dict[str, Any]
    origin_snapshot_id: uuid.UUID | None = None


class UserNetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    net_data: dict[str, Any]
    origin_snapshot_id: uuid.UUID | None = None


class UserNetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    net_data: dict[str, Any] | None = None


class NetShareRequest(BaseModel):
    visibility: Literal["private", "link_only"]


class NetShareResponse(BaseModel):
    share_token: str
    visibility: str


class SharedNetView(BaseModel):
    """Public read-only view of a net via its share token."""

    id: str
    name: str
    share_token: str
    visibility: str
    net_data: dict[str, Any]
    created_at: str
    updated_at: str
    thumbnail: list[NetThumbnailNode] = Field(default_factory=list)
    thumbnail_arcs: list[NetThumbnailArc] = Field(default_factory=list)
