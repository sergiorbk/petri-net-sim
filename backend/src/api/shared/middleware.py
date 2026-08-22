"""API middleware"""

import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from src.core import get_logger

logger = get_logger("api.middleware")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware to add unique request ID to each request"""

    async def dispatch(self, request: Request, call_next):
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Add to response headers
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all requests"""

    async def dispatch(self, request: Request, call_next):
        request_id = getattr(request.state, "request_id", "unknown")
        start_time = time.time()

        # Log request
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host if request.client else None,
            },
        )

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration = time.time() - start_time

        # Log response
        logger.info(
            f"Request completed: {request.method} {request.url.path} - "
            f"Status: {response.status_code} - Duration: {duration:.3f}s",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration": duration,
            },
        )

        # Add duration to response headers
        response.headers["X-Response-Time"] = f"{duration:.3f}"

        return response


class ApiVersionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add API version information to responses.

    Adds deprecation warnings and version lifecycle headers.
    """

    async def dispatch(self, request: Request, call_next):
        # Import here to avoid circular dependency
        from src.api.version_manager import version_manager

        # Extract version from path
        path = request.url.path
        api_version = None

        if "/api/v" in path:
            # Extract version from path like /api/v1/...
            parts = path.split("/api/v")
            if len(parts) > 1:
                version_num = parts[1].split("/")[0]
                api_version = f"v{version_num}"

        # Process request
        response = await call_next(request)

        # Add version headers
        if api_version:
            response.headers["X-API-Version"] = api_version

            # Add deprecation headers if applicable
            deprecation_headers = version_manager.get_deprecation_headers(api_version)
            for header_name, header_value in deprecation_headers.items():
                response.headers[header_name] = header_value

        # Always add latest stable version info
        latest_stable = version_manager.get_latest_stable_version()
        if latest_stable:
            response.headers["X-API-Latest-Version"] = latest_stable

        return response
