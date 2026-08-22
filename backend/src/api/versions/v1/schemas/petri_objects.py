"""Pydantic schemas for the /petri-objects endpoints."""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PetriObjectSummary(BaseModel):
    """Minimal descriptor used in the list endpoint."""

    id: uuid.UUID
    name: str
    description: str | None = None
    is_builtin: bool
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class PetriObjectDetail(PetriObjectSummary):
    """Full template payload (served when a user drops the object on the canvas)."""

    template_data: dict[str, Any]
    preview_svg: str | None = None
    created_at: str


class PetriObjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    template_data: dict[str, Any]
    preview_svg: str | None = None


class PetriObjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    template_data: dict[str, Any] | None = None
    preview_svg: str | None = None
