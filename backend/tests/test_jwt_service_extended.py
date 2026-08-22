"""Tests for JWTService — refresh token, download token, user ID extraction."""

from __future__ import annotations

import uuid

import pytest

from src.services.auth.jwt_service import get_jwt_service


@pytest.fixture
def jwt():
    return get_jwt_service()


@pytest.fixture
def user_id():
    return uuid.uuid4()


@pytest.fixture
def access_token(jwt, user_id):
    return jwt.create_access_token(user_id, "user@test.local")


@pytest.fixture
def refresh_token(jwt, user_id):
    return jwt.create_refresh_token(user_id)


# ---------------------------------------------------------------------------
# Refresh token
# ---------------------------------------------------------------------------


class TestRefreshToken:
    def test_verify_refresh_token_returns_payload(self, jwt, refresh_token):
        payload = jwt.verify_refresh_token(refresh_token)
        assert payload is not None
        assert payload["type"] == "refresh"

    def test_verify_refresh_token_rejects_access_token(self, jwt, access_token):
        # Access tokens must not be accepted as refresh tokens
        result = jwt.verify_refresh_token(access_token)
        assert result is None

    def test_verify_refresh_token_rejects_garbage(self, jwt):
        assert jwt.verify_refresh_token("not.a.token") is None


# ---------------------------------------------------------------------------
# Download token
# ---------------------------------------------------------------------------


class TestDownloadToken:
    def test_create_and_verify_download_token(self, jwt, user_id):
        file_id = uuid.uuid4()
        token = jwt.create_download_token(file_id, user_id)

        result = jwt.verify_download_token(token)

        assert result is not None
        assert result == (file_id, user_id)

    def test_verify_download_token_rejects_access_token(self, jwt, access_token):
        assert jwt.verify_download_token(access_token) is None

    def test_verify_download_token_rejects_garbage(self, jwt):
        assert jwt.verify_download_token("garbage") is None


# ---------------------------------------------------------------------------
# get_user_id_from_token
# ---------------------------------------------------------------------------


class TestGetUserIdFromToken:
    def test_extracts_user_id_from_access_token(self, jwt, user_id, access_token):
        extracted = jwt.get_user_id_from_token(access_token)
        assert extracted == user_id

    def test_extracts_user_id_from_refresh_token(self, jwt, user_id, refresh_token):
        extracted = jwt.get_user_id_from_token(refresh_token)
        assert extracted == user_id

    def test_returns_none_for_invalid_token(self, jwt):
        assert jwt.get_user_id_from_token("bad_token") is None

    def test_returns_none_for_token_without_sub(self, jwt):
        import jwt as pyjwt
        from src.core.auth_config import auth_settings
        # Craft token with no 'sub' claim
        token = pyjwt.encode({"type": "access"}, auth_settings.AUTH_JWT_SECRET_KEY, algorithm="HS256")
        assert jwt.get_user_id_from_token(token) is None

    def test_returns_none_for_invalid_sub_uuid(self, jwt):
        import jwt as pyjwt
        from src.core.auth_config import auth_settings
        # Craft token with sub that is not a valid UUID
        token = pyjwt.encode(
            {"type": "access", "sub": "not-a-uuid"},
            auth_settings.AUTH_JWT_SECRET_KEY,
            algorithm="HS256",
        )
        assert jwt.get_user_id_from_token(token) is None


class TestDownloadTokenEdgeCases:
    def test_verify_download_token_missing_fid_key(self, jwt, user_id):
        import jwt as pyjwt
        from src.core.auth_config import auth_settings
        # Token with type=download but no fid key
        token = pyjwt.encode(
            {"type": "download", "sub": str(user_id)},
            auth_settings.AUTH_JWT_SECRET_KEY,
            algorithm="HS256",
        )
        result = jwt.verify_download_token(token)
        assert result is None
