"""Tests for api/shared/handlers.py — exception and validation handlers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError

from src.api.shared.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from src.api.shared.handlers import (
    _is_openai_endpoint,
    _openai_error_response,
    api_exception_handler,
    error_code_from_status,
    get_request_id,
    unhandled_exception_handler,
    validation_exception_handler,
)
from src.api.shared.responses import ErrorCode


# ---------------------------------------------------------------------------
# Helper: minimal mock Request
# ---------------------------------------------------------------------------


def _make_request(path: str = "/api/v1/test", state_request_id: str | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [],
    }
    req = Request(scope)
    if state_request_id:
        req.state.request_id = state_request_id
    return req


# ---------------------------------------------------------------------------
# _is_openai_endpoint
# ---------------------------------------------------------------------------


class TestIsOpenAIEndpoint:
    def test_chat_endpoint(self):
        req = _make_request("/api/v1/chat/completions")
        assert _is_openai_endpoint(req) is True

    def test_models_endpoint(self):
        req = _make_request("/api/v1/models")
        assert _is_openai_endpoint(req) is True

    def test_files_endpoint(self):
        req = _make_request("/api/v1/files/abc123")
        assert _is_openai_endpoint(req) is True

    def test_regular_endpoint(self):
        req = _make_request("/api/v1/sessions")
        assert _is_openai_endpoint(req) is False

    def test_auth_endpoint(self):
        req = _make_request("/api/v1/auth/login")
        assert _is_openai_endpoint(req) is False


# ---------------------------------------------------------------------------
# _openai_error_response
# ---------------------------------------------------------------------------


class TestOpenAIErrorResponse:
    def test_400_type(self):
        resp = _openai_error_response(400, "bad input")
        assert resp.status_code == 400
        body = resp.body
        import json
        data = json.loads(body)
        assert data["error"]["type"] == "invalid_request_error"
        assert data["error"]["message"] == "bad input"

    def test_401_type(self):
        resp = _openai_error_response(401, "no auth")
        import json
        data = json.loads(resp.body)
        assert data["error"]["type"] == "authentication_error"

    def test_unknown_status_is_server_error(self):
        resp = _openai_error_response(599, "weird")
        import json
        data = json.loads(resp.body)
        assert data["error"]["type"] == "server_error"


# ---------------------------------------------------------------------------
# error_code_from_status
# ---------------------------------------------------------------------------


class TestErrorCodeFromStatus:
    def test_400(self):
        assert error_code_from_status(400) == ErrorCode.VALIDATION_ERROR

    def test_401(self):
        assert error_code_from_status(401) == ErrorCode.UNAUTHORIZED

    def test_403(self):
        assert error_code_from_status(403) == ErrorCode.FORBIDDEN

    def test_404(self):
        assert error_code_from_status(404) == ErrorCode.NOT_FOUND

    def test_409(self):
        assert error_code_from_status(409) == ErrorCode.CONFLICT

    def test_429(self):
        assert error_code_from_status(429) == ErrorCode.RATE_LIMIT_EXCEEDED

    def test_500(self):
        assert error_code_from_status(500) == ErrorCode.INTERNAL_ERROR

    def test_unknown_maps_to_internal(self):
        assert error_code_from_status(599) == ErrorCode.INTERNAL_ERROR


# ---------------------------------------------------------------------------
# get_request_id
# ---------------------------------------------------------------------------


class TestGetRequestId:
    def test_returns_state_request_id(self):
        req = _make_request(state_request_id="my-request-id")
        assert get_request_id(req) == "my-request-id"

    def test_generates_uuid_when_missing(self):
        req = _make_request()
        rid = get_request_id(req)
        import uuid
        # Should be a valid UUID string
        uuid.UUID(rid)


# ---------------------------------------------------------------------------
# api_exception_handler
# ---------------------------------------------------------------------------


class TestApiExceptionHandler:
    @pytest.mark.anyio
    async def test_returns_json_with_error_code(self):
        req = _make_request("/api/v1/sessions")
        exc = NotFoundException(resource="Session", identifier="abc")

        resp = await api_exception_handler(req, exc)

        assert resp.status_code == 404
        import json
        data = json.loads(resp.body)
        assert data["error"]["code"] == ErrorCode.NOT_FOUND.value

    @pytest.mark.anyio
    async def test_openai_endpoint_returns_openai_format(self):
        req = _make_request("/api/v1/chat/completions")
        exc = UnauthorizedException()

        resp = await api_exception_handler(req, exc)

        import json
        data = json.loads(resp.body)
        assert "error" in data
        assert "type" in data["error"]

    @pytest.mark.anyio
    async def test_bad_request_returns_400(self):
        req = _make_request("/api/v1/sessions")
        exc = BadRequestException("invalid input")

        resp = await api_exception_handler(req, exc)

        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_conflict_returns_409(self):
        req = _make_request("/api/v1/sessions")
        exc = ConflictException("Session already exists")

        resp = await api_exception_handler(req, exc)

        assert resp.status_code == 409

    @pytest.mark.anyio
    async def test_forbidden_returns_403(self):
        req = _make_request("/api/v1/sessions")
        exc = ForbiddenException()

        resp = await api_exception_handler(req, exc)

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# unhandled_exception_handler
# ---------------------------------------------------------------------------


class TestUnhandledExceptionHandler:
    @pytest.mark.anyio
    async def test_returns_500(self):
        req = _make_request("/api/v1/sessions")

        resp = await unhandled_exception_handler(req, RuntimeError("boom"))

        assert resp.status_code == 500
        import json
        data = json.loads(resp.body)
        assert data["error"]["code"] == ErrorCode.INTERNAL_ERROR.value

    @pytest.mark.anyio
    async def test_openai_endpoint_returns_openai_format(self):
        req = _make_request("/api/v1/chat/completions")

        resp = await unhandled_exception_handler(req, RuntimeError("crash"))

        import json
        data = json.loads(resp.body)
        assert "error" in data
        assert data["error"]["type"] == "server_error"


# ---------------------------------------------------------------------------
# validation_exception_handler
# ---------------------------------------------------------------------------


class TestValidationExceptionHandler:
    @pytest.mark.anyio
    async def test_returns_422_for_pydantic_error(self):
        from pydantic import BaseModel

        class M(BaseModel):
            x: int

        try:
            M(x="not_an_int")
        except PydanticValidationError as e:
            # Wrap in RequestValidationError as FastAPI would
            exc = RequestValidationError(e.errors())

        req = _make_request("/api/v1/sessions")
        resp = await validation_exception_handler(req, exc)

        assert resp.status_code == 422
        import json
        data = json.loads(resp.body)
        assert data["error"]["code"] == ErrorCode.VALIDATION_ERROR.value

    @pytest.mark.anyio
    async def test_openai_endpoint_returns_openai_format(self):
        from pydantic import BaseModel

        class M(BaseModel):
            x: int

        try:
            M(x="bad")
        except PydanticValidationError as e:
            exc = RequestValidationError(e.errors())

        req = _make_request("/api/v1/chat/completions")
        resp = await validation_exception_handler(req, exc)

        import json
        data = json.loads(resp.body)
        assert "error" in data
        assert "Validation failed" in data["error"]["message"]
