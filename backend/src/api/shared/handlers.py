"""Exception handlers for FastAPI"""

import uuid
from datetime import UTC, datetime

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.shared.exceptions import ApiException, RateLimitException
from src.api.shared.responses import (
    ApiErrorResponse,
    ErrorCode,
    ErrorDetail,
    ResponseMeta,
    ValidationError,
)
from src.core import get_logger

logger = get_logger("api.handlers")

_OPENAI_PATH_PREFIXES = ("/api/v1/chat/", "/api/v1/models", "/api/v1/files/")


def _is_openai_endpoint(request: Request) -> bool:
    """Check if the request targets an OpenAI-compatible endpoint."""
    path = request.url.path
    return any(path.startswith(prefix) for prefix in _OPENAI_PATH_PREFIXES)


def _openai_error_response(status_code: int, message: str) -> JSONResponse:
    """Return an error in OpenAI format: {"error": {"message", "type", "code"}}."""
    type_map = {
        400: "invalid_request_error",
        401: "authentication_error",
        403: "permission_error",
        404: "not_found",
        422: "invalid_request_error",
        429: "rate_limit_error",
    }
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": type_map.get(status_code, "server_error"),
                "code": None,
            }
        },
    )


def get_request_id(request: Request) -> str:
    """Get or generate request ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def error_code_from_status(status_code: int) -> ErrorCode:
    """Map HTTP status code to error code"""
    mapping = {
        400: ErrorCode.VALIDATION_ERROR,
        401: ErrorCode.UNAUTHORIZED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        409: ErrorCode.CONFLICT,
        429: ErrorCode.RATE_LIMIT_EXCEEDED,
        500: ErrorCode.INTERNAL_ERROR,
        503: ErrorCode.SERVICE_UNAVAILABLE,
    }
    return mapping.get(status_code, ErrorCode.INTERNAL_ERROR)


def _coerce_details(details: list[dict]) -> list[ValidationError] | None:
    """Shape raise-site detail dicts into the response's ValidationError.

    An exception handler must never raise: a detail dict that does not match
    the {field, message} contract used to crash this handler with a pydantic
    error, turning an actionable 400 into a bare 500. Tolerate the shapes
    raise sites have actually used and drop anything unrecognizable.
    """
    coerced: list[ValidationError] = []
    for d in details:
        if not isinstance(d, dict):
            continue
        if "message" in d:
            coerced.append(
                ValidationError(
                    field=str(d.get("field", "model")),
                    message=str(d["message"]),
                    value=d.get("value"),
                )
            )
        elif "error" in d:
            coerced.append(ValidationError(field="model", message=str(d["error"])))
    return coerced or None


async def api_exception_handler(request: Request, exc: ApiException) -> JSONResponse:
    """Handle custom API exceptions"""
    request_id = get_request_id(request)

    logger.warning(
        f"API Exception: {exc.code} - {exc.message}",
        extra={
            "request_id": request_id,
            "status_code": exc.status_code,
            "path": request.url.path,
        },
    )

    extra_headers = (
        exc.rate_limit_headers() if isinstance(exc, RateLimitException) else {}
    )

    if _is_openai_endpoint(request):
        resp = _openai_error_response(exc.status_code, exc.message)
        for name, value in extra_headers.items():
            resp.headers[name] = value
        return resp

    response = ApiErrorResponse(
        error=ErrorDetail(
            code=exc.code,
            message=exc.message,
            details=_coerce_details(exc.details) if exc.details else None,
            trace_id=request_id,
        ),
        meta=ResponseMeta(
            timestamp=datetime.now(UTC),
            request_id=request_id,
            version="v1",
        ),
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump(mode="json", exclude_none=True),
        headers=extra_headers or None,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors"""
    request_id = get_request_id(request)

    if _is_openai_endpoint(request):
        messages = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc'][1:])}: {e['msg']}"
            for e in exc.errors()
        )
        return _openai_error_response(422, f"Validation failed: {messages}")

    # Extract validation errors
    validation_errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"][1:])
        validation_errors.append(
            ValidationError(
                field=field or "unknown",
                message=error["msg"],
                value=error.get("input"),
            )
        )

    logger.warning(
        f"Validation error: {len(validation_errors)} fields failed",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "errors": validation_errors,
        },
    )

    response = ApiErrorResponse(
        error=ErrorDetail(
            code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed",
            details=validation_errors,
            trace_id=request_id,
        ),
        meta=ResponseMeta(
            timestamp=datetime.now(UTC),
            request_id=request_id,
            version="v1",
        ),
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=response.model_dump(mode="json", exclude_none=True),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle all unhandled exceptions"""
    request_id = get_request_id(request)

    if _is_openai_endpoint(request):
        logger.exception(
            f"Unhandled exception on OpenAI endpoint: {type(exc).__name__}",
            extra={"request_id": request_id, "path": request.url.path},
            exc_info=exc,
        )
        return _openai_error_response(500, "An unexpected error occurred")

    logger.exception(
        f"Unhandled exception: {type(exc).__name__}",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
        exc_info=exc,
    )

    response = ApiErrorResponse(
        error=ErrorDetail(
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred",
            trace_id=request_id,
        ),
        meta=ResponseMeta(
            timestamp=datetime.now(UTC),
            request_id=request_id,
            version="v1",
        ),
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response.model_dump(mode="json", exclude_none=True),
    )
