"""Utility functions for API responses"""

from datetime import UTC, datetime
from typing import Any, TypeVar

from fastapi import Request

from src.api.shared.responses import (
    ApiSuccessResponse,
    PaginationMeta,
    ResponseMeta,
)

T = TypeVar("T")


def get_request_id(request: Request) -> str:
    """Get request ID from request state"""
    return getattr(request.state, "request_id", "unknown")


def success_response(
    data: T,
    request: Request,
    pagination: PaginationMeta | None = None,
) -> ApiSuccessResponse[T]:
    """Create standardized success response"""
    return ApiSuccessResponse(
        success=True,
        data=data,
        meta=ResponseMeta(
            timestamp=datetime.now(UTC),
            request_id=get_request_id(request),
            version="v1",
            pagination=pagination,
        ),
    )


def paginated_response(
    items: list[Any],
    total: int,
    page: int,
    per_page: int,
    request: Request,
) -> ApiSuccessResponse[list[Any]]:
    """Create paginated success response"""
    total_pages = (total + per_page - 1) // per_page if per_page > 0 else 0

    pagination = PaginationMeta(
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )

    return success_response(
        data=items,
        request=request,
        pagination=pagination,
    )
