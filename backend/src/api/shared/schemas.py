"""Shared Pydantic schemas for all API versions"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TimestampSchema(BaseModel):
    """Base schema with timestamps"""

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginationParams(BaseModel):
    """Common pagination parameters"""

    limit: int = 100
    offset: int = 0

    model_config = ConfigDict(frozen=True)


class PaginatedResponse(BaseModel):
    """Common paginated response structure"""

    total: int
    limit: int
    offset: int
