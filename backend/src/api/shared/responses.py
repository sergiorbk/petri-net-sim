"""Standardized API response models"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorCode(str, Enum):
    """Standard error codes"""

    # Client errors (4xx)
    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    TOKEN_LIMIT_EXCEEDED = "TOKEN_LIMIT_EXCEEDED"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"

    # Server errors (5xx)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    DATABASE_ERROR = "DATABASE_ERROR"
    LLM_ERROR = "LLM_ERROR"


class ValidationError(BaseModel):
    """Validation error detail"""

    field: str = Field(description="Field name that failed validation")
    message: str = Field(description="Validation error message")
    value: Any = Field(default=None, description="Invalid value")


class ErrorDetail(BaseModel):
    """Error detail structure"""

    code: ErrorCode = Field(description="Machine-readable error code")
    message: str = Field(description="Human-readable error message")
    details: list[ValidationError] | None = Field(
        default=None, description="Validation errors if applicable"
    )
    trace_id: str | None = Field(default=None, description="Error trace ID for logging")


class PaginationMeta(BaseModel):
    """Pagination metadata"""

    total: int = Field(description="Total number of items")
    page: int = Field(description="Current page number")
    per_page: int = Field(description="Items per page")
    total_pages: int = Field(description="Total number of pages")


class ResponseMeta(BaseModel):
    """Response metadata"""

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Response timestamp",
    )
    request_id: str = Field(description="Unique request identifier")
    version: str = Field(default="v1", description="API version")
    pagination: PaginationMeta | None = Field(
        default=None, description="Pagination metadata if applicable"
    )


class ApiResponse(BaseModel, Generic[T]):
    """Standard API response wrapper"""

    success: bool = Field(description="Whether request was successful")
    data: T | None = Field(default=None, description="Response data")
    meta: ResponseMeta = Field(description="Response metadata")
    error: ErrorDetail | None = Field(default=None, description="Error details if failed")


class ApiSuccessResponse(ApiResponse[T], Generic[T]):
    """Success response wrapper"""

    success: bool = Field(default=True)
    data: T
    error: None = Field(default=None)


class ApiErrorResponse(ApiResponse[None]):
    """Error response wrapper"""

    success: bool = Field(default=False)
    data: None = Field(default=None)
    error: ErrorDetail
