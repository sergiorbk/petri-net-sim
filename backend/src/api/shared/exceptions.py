"""Custom API exceptions"""

from typing import Any

from src.api.shared.responses import ErrorCode


class ApiException(Exception):
    """Base exception for API errors"""

    def __init__(
        self,
        message: str,
        code: ErrorCode,
        status_code: int = 400,
        details: list[dict[str, Any]] | None = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or []
        super().__init__(message)


class BadRequestException(ApiException):
    """Raised when request is malformed or invalid"""

    def __init__(
        self,
        message: str = "Bad request",
        details: list[dict[str, Any]] | None = None,
    ):
        super().__init__(
            message=message,
            code=ErrorCode.BAD_REQUEST,
            status_code=400,
            details=details,
        )


class ValidationException(ApiException):
    """Raised when request validation fails"""

    def __init__(
        self,
        message: str = "Validation failed",
        details: list[dict[str, Any]] | None = None,
    ):
        super().__init__(
            message=message,
            code=ErrorCode.VALIDATION_ERROR,
            status_code=400,
            details=details,
        )


class UnauthorizedException(ApiException):
    """Raised when user is not authenticated"""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            message=message,
            code=ErrorCode.UNAUTHORIZED,
            status_code=401,
        )


class ForbiddenException(ApiException):
    """Raised when user lacks required permissions"""

    def __init__(self, message: str = "Access forbidden"):
        super().__init__(
            message=message,
            code=ErrorCode.FORBIDDEN,
            status_code=403,
        )


class NotFoundException(ApiException):
    """Raised when resource is not found"""

    def __init__(self, resource: str, identifier: Any):
        super().__init__(
            message=f"{resource} with identifier '{identifier}' not found",
            code=ErrorCode.NOT_FOUND,
            status_code=404,
        )


class ConflictException(ApiException):
    """Raised when resource already exists or conflicts"""

    def __init__(self, message: str, details: list[dict[str, Any]] | None = None):
        super().__init__(
            message=message,
            code=ErrorCode.CONFLICT,
            status_code=409,
            details=details,
        )


class RateLimitException(ApiException):
    """Raised when rate limit is exceeded.

    Carries optional rate-limit metadata so the exception handler can emit
    standard ``Retry-After`` and ``X-RateLimit-*`` response headers.
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: int | None = None,
        limit: int | None = None,
        window: int | None = None,
    ):
        super().__init__(
            message=message,
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            status_code=429,
        )
        self.retry_after = retry_after
        self.limit = limit
        self.window = window

    def rate_limit_headers(self) -> dict[str, str]:
        """Standard rate-limit response headers for this exception."""
        headers: dict[str, str] = {}
        if self.retry_after is not None:
            headers["Retry-After"] = str(self.retry_after)
        if self.limit is not None:
            headers["X-RateLimit-Limit"] = str(self.limit)
            headers["X-RateLimit-Remaining"] = "0"
        if self.retry_after is not None:
            headers["X-RateLimit-Reset"] = str(self.retry_after)
        return headers


class InternalServerException(ApiException):
    """Raised for internal server errors"""

    def __init__(self, message: str = "Internal server error"):
        super().__init__(
            message=message,
            code=ErrorCode.INTERNAL_ERROR,
            status_code=500,
        )


class DatabaseException(ApiException):
    """Raised when database operation fails"""

    def __init__(self, message: str = "Database operation failed"):
        super().__init__(
            message=message,
            code=ErrorCode.DATABASE_ERROR,
            status_code=500,
        )


class ServiceUnavailableException(ApiException):
    """Raised when service is temporarily unavailable"""

    def __init__(self, message: str = "Service temporarily unavailable"):
        super().__init__(
            message=message,
            code=ErrorCode.SERVICE_UNAVAILABLE,
            status_code=503,
        )


class LLMException(ApiException):
    """Raised when LLM operation fails"""

    def __init__(self, message: str = "LLM operation failed"):
        super().__init__(
            message=message,
            code=ErrorCode.LLM_ERROR,
            status_code=500,
        )


class TokenLimitException(ApiException):
    """Raised when token limit is exceeded"""

    def __init__(self, message: str = "Token limit exceeded"):
        super().__init__(
            message=message,
            code=ErrorCode.TOKEN_LIMIT_EXCEEDED,
            status_code=400,
        )


class ConversationNotFoundException(ApiException):
    """Raised when conversation is not found"""

    def __init__(self, conversation_id: Any):
        super().__init__(
            message=f"Conversation '{conversation_id}' not found",
            code=ErrorCode.CONVERSATION_NOT_FOUND,
            status_code=404,
        )
