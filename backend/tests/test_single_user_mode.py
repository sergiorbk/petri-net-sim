"""Tests for AUTH_MODE=single_user (no-login local mode).

Covers the auth dependencies' fallback behavior, the disabled account
endpoints, the idempotent local-user bootstrap, and the public /config
endpoint. Default (multi) mode is exercised by the existing auth test
suites (test_auth_api.py, test_auth_service.py) which run unchanged and
prove backward compatibility -- this file only adds single-user coverage.
"""

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.shared.exceptions import UnauthorizedException
from src.core.auth_config import auth_settings
from src.core.dependencies import (
    get_authenticated_context,
    get_current_user,
    get_current_user_from_request,
    get_current_user_optional,
)
from src.infrastructure.postgres.models.user import User
from src.services.auth.auth_service import hash_password, verify_password
from src.services.auth.jwt_service import get_jwt_service
from src.services.auth.local_user import (
    LOCAL_USER_EMAIL,
    LOCAL_USER_NAME,
    LocalUserBootstrapError,
    ensure_local_user,
)


@pytest.fixture(autouse=True)
def _reset_auth_mode():
    """Every test starts from the default (multi) mode and restores it after,
    since AUTH_MODE lives on a module-level settings singleton."""
    original = auth_settings.AUTH_MODE
    yield
    auth_settings.AUTH_MODE = original


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# -- ensure_local_user bootstrap --


class TestEnsureLocalUser:
    async def test_creates_user_on_first_call(self, session: AsyncSession):
        user = await ensure_local_user(session)
        assert user.email == LOCAL_USER_EMAIL
        assert user.name == LOCAL_USER_NAME
        assert user.is_active is True

    async def test_idempotent_on_repeat_calls(self, session: AsyncSession):
        first = await ensure_local_user(session)
        second = await ensure_local_user(session)
        assert first.id == second.id

    async def test_password_hash_is_set_but_unusable(self, session: AsyncSession):
        """A hash exists (so the row satisfies normal user invariants) but no
        one can know the random password it was derived from."""
        user = await ensure_local_user(session)
        assert user.password_hash is not None
        assert not verify_password("", user.password_hash)
        assert not verify_password("password", user.password_hash)
        assert not verify_password(LOCAL_USER_EMAIL, user.password_hash)


# -- ensure_local_user refuses a pre-existing, non-bootstrap row (email squatting) --


class TestEnsureLocalUserSquattingGuard:
    async def test_refuses_row_signup_could_have_created(self, session: AsyncSession):
        """A row already sitting at LOCAL_USER_EMAIL that was NOT created by
        ensure_local_user (no bootstrap marker in metadata_ -- exactly what
        the ordinary signup path produces) must never be silently adopted,
        since that would hand whoever registered it first permanent control
        of the local account once single_user mode is switched on."""
        squatter = User(
            email=LOCAL_USER_EMAIL,
            name="Whoever signed up first",
            password_hash=hash_password("attacker-chosen-password"),
            is_active=True,
            metadata_={},  # exactly what signup's create() path stores
        )
        session.add(squatter)
        await session.commit()

        with pytest.raises(LocalUserBootstrapError):
            await ensure_local_user(session)

    async def test_refuses_row_with_unrelated_metadata(self, session: AsyncSession):
        """Also refuses a row whose metadata_ is non-empty but doesn't carry
        the exact marker -- e.g. one that later had display_name set via
        PATCH /auth/me, which never touches the marker key."""
        squatter = User(
            email=LOCAL_USER_EMAIL,
            name="Whoever signed up first",
            password_hash=hash_password("attacker-chosen-password"),
            is_active=True,
            metadata_={"display_name": "Totally Legit"},
        )
        session.add(squatter)
        await session.commit()

        with pytest.raises(LocalUserBootstrapError):
            await ensure_local_user(session)

    async def test_accepts_its_own_row_across_a_fresh_session(
        self, session: AsyncSession, session_factory
    ):
        """Idempotent across what stands in for a process restart: a brand
        new session looking at the same persisted row recognizes it as its
        own (via the bootstrap marker) instead of refusing it."""
        created = await ensure_local_user(session)

        async with session_factory() as fresh_session:
            again = await ensure_local_user(fresh_session)
            assert again.id == created.id


# -- get_current_user --


class TestGetCurrentUser:
    async def test_no_token_returns_local_user_in_single_mode(self, session: AsyncSession):
        auth_settings.AUTH_MODE = "single_user"
        user = await get_current_user(credentials=None, session=session)
        assert user.email == LOCAL_USER_EMAIL

    async def test_no_token_401s_in_multi_mode(self, session: AsyncSession):
        auth_settings.AUTH_MODE = "multi"
        with pytest.raises(UnauthorizedException):
            await get_current_user(credentials=None, session=session)

    async def test_valid_token_still_authenticates_in_single_mode(
        self, session: AsyncSession, password_user
    ):
        auth_settings.AUTH_MODE = "single_user"
        jwt_svc = get_jwt_service()
        token = jwt_svc.create_access_token(password_user.id, password_user.email)
        user = await get_current_user(credentials=_bearer(token), session=session)
        assert user.id == password_user.id
        assert user.email != LOCAL_USER_EMAIL

    async def test_invalid_token_falls_back_to_local_user_in_single_mode(
        self, session: AsyncSession
    ):
        auth_settings.AUTH_MODE = "single_user"
        user = await get_current_user(credentials=_bearer("garbage-token"), session=session)
        assert user.email == LOCAL_USER_EMAIL

    async def test_invalid_token_401s_in_multi_mode(self, session: AsyncSession):
        auth_settings.AUTH_MODE = "multi"
        with pytest.raises(UnauthorizedException):
            await get_current_user(credentials=_bearer("garbage-token"), session=session)


# -- get_current_user_optional --


class TestGetCurrentUserOptional:
    async def test_no_token_returns_none_in_multi_mode(self, session: AsyncSession):
        auth_settings.AUTH_MODE = "multi"
        user = await get_current_user_optional(credentials=None, session=session)
        assert user is None

    async def test_no_token_returns_local_user_in_single_mode(self, session: AsyncSession):
        auth_settings.AUTH_MODE = "single_user"
        user = await get_current_user_optional(credentials=None, session=session)
        assert user is not None
        assert user.email == LOCAL_USER_EMAIL

    async def test_valid_token_still_authenticates_in_single_mode(
        self, session: AsyncSession, password_user
    ):
        auth_settings.AUTH_MODE = "single_user"
        jwt_svc = get_jwt_service()
        token = jwt_svc.create_access_token(password_user.id, password_user.email)
        user = await get_current_user_optional(credentials=_bearer(token), session=session)
        assert user is not None
        assert user.id == password_user.id


# -- get_authenticated_context --


class TestGetAuthenticatedContext:
    async def test_no_token_returns_local_user_context_in_single_mode(
        self, session: AsyncSession
    ):
        auth_settings.AUTH_MODE = "single_user"
        ctx = await get_authenticated_context(credentials=None, session=session)
        assert ctx.user.email == LOCAL_USER_EMAIL
        assert ctx.api_key_hash is None

    async def test_no_token_401s_in_multi_mode(self, session: AsyncSession):
        auth_settings.AUTH_MODE = "multi"
        with pytest.raises(UnauthorizedException):
            await get_authenticated_context(credentials=None, session=session)

    async def test_api_key_still_works_in_single_mode(
        self, session: AsyncSession, regular_user
    ):
        auth_settings.AUTH_MODE = "single_user"
        from src.services.auth.api_key_service import ApiKeyService

        svc = ApiKeyService(session)
        raw_key, _ = await svc.create_key(regular_user.id, "test-key")

        ctx = await get_authenticated_context(credentials=_bearer(raw_key), session=session)
        assert ctx.user.id == regular_user.id
        assert ctx.api_key_hash is not None

    async def test_invalid_api_key_falls_back_to_local_user_in_single_mode(
        self, session: AsyncSession
    ):
        auth_settings.AUTH_MODE = "single_user"
        ctx = await get_authenticated_context(credentials=_bearer("sk-bogus"), session=session)
        assert ctx.user.email == LOCAL_USER_EMAIL

    async def test_invalid_api_key_401s_in_multi_mode(self, session: AsyncSession):
        auth_settings.AUTH_MODE = "multi"
        with pytest.raises(UnauthorizedException):
            await get_authenticated_context(credentials=_bearer("sk-bogus"), session=session)


# -- get_current_user_from_request (used by GET /auth/me) --


class TestGetCurrentUserFromRequest:
    async def test_no_header_returns_local_user_in_single_mode(self, session: AsyncSession):
        from starlette.requests import Request

        auth_settings.AUTH_MODE = "single_user"
        scope = {"type": "http", "headers": []}
        request = Request(scope)
        user = await get_current_user_from_request(request, session)
        assert user.email == LOCAL_USER_EMAIL

    async def test_no_header_401s_in_multi_mode(self, session: AsyncSession):
        from starlette.requests import Request

        auth_settings.AUTH_MODE = "multi"
        scope = {"type": "http", "headers": []}
        request = Request(scope)
        with pytest.raises(UnauthorizedException):
            await get_current_user_from_request(request, session)


# -- /api/v1/auth/{signup,login,oauth} disabled in single-user mode --


def _create_auth_test_app() -> FastAPI:
    """Minimal FastAPI app carrying only the auth router (no lifespan)."""
    from src.api.shared.exceptions import ApiException
    from src.api.shared.handlers import api_exception_handler

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = FastAPI(lifespan=noop_lifespan)
    app.add_exception_handler(ApiException, api_exception_handler)

    from src.api.versions.v1.routers.auth import router as auth_router

    app.include_router(auth_router, prefix="/api/v1")
    return app


@pytest.fixture
def auth_app():
    return _create_auth_test_app()


@pytest.fixture
def auth_client(auth_app, session_factory):
    from src.core.dependencies import get_postgres_session

    async def _override_session():
        async with session_factory() as sess:
            yield sess

    auth_app.dependency_overrides[get_postgres_session] = _override_session
    with TestClient(auth_app, raise_server_exceptions=False) as c:
        yield c
    auth_app.dependency_overrides.clear()


class TestAccountEndpointsDisabledInSingleUserMode:
    def test_signup_returns_403(self, auth_client):
        auth_settings.AUTH_MODE = "single_user"
        response = auth_client.post(
            "/api/v1/auth/signup",
            json={"email": "new@example.com", "password": "password123"},
        )
        assert response.status_code == 403

    def test_login_returns_403(self, auth_client):
        auth_settings.AUTH_MODE = "single_user"
        response = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "password123"},
        )
        assert response.status_code == 403

    def test_google_authorize_returns_403(self, auth_client):
        auth_settings.AUTH_MODE = "single_user"
        response = auth_client.get("/api/v1/auth/oauth/google/authorize")
        assert response.status_code == 403

    def test_signup_still_works_in_multi_mode(self, auth_client):
        auth_settings.AUTH_MODE = "multi"
        response = auth_client.post(
            "/api/v1/auth/signup",
            json={"email": "multimode@example.com", "password": "password123"},
        )
        assert response.status_code == 200

    def test_login_still_works_in_multi_mode(self, auth_client):
        auth_settings.AUTH_MODE = "multi"
        signup = auth_client.post(
            "/api/v1/auth/signup",
            json={"email": "multimode2@example.com", "password": "password123"},
        )
        assert signup.status_code == 200

        response = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "multimode2@example.com", "password": "password123"},
        )
        assert response.status_code == 200


# -- GET /api/v1/auth/me over HTTP, unauthenticated, in single-user mode --
#
# The dependency-level tests above (TestGetCurrentUserFromRequest etc.) only
# check the User ORM object the dependency returns -- they never go through
# UserResponse's own pydantic validation, which is exactly where this broke:
# UserResponse.email used to be EmailStr, and LOCAL_USER_EMAIL sits on the
# .local special-use TLD that email_validator rejects even with
# check_deliverability=False, so building the response 500'd on every
# single-user-mode request to /me.


class TestGetMeOverHttpInSingleUserMode:
    def test_no_auth_header_returns_local_user(self, auth_client):
        auth_settings.AUTH_MODE = "single_user"
        response = auth_client.get("/api/v1/auth/me")
        assert response.status_code == 200
        assert response.json()["data"]["email"] == LOCAL_USER_EMAIL


# -- POST /api/v1/auth/signup rejects LOCAL_USER_EMAIL unconditionally --


class TestSignupRejectsReservedEmail:
    def test_rejected_in_multi_mode(self, auth_client):
        auth_settings.AUTH_MODE = "multi"
        response = auth_client.post(
            "/api/v1/auth/signup",
            json={"email": LOCAL_USER_EMAIL, "password": "password123"},
        )
        assert response.status_code == 400
        assert "reserved" in response.json()["error"]["message"].lower()

    def test_rejected_in_single_user_mode(self, auth_client):
        # single_user mode already 403s all signups (see above); this proves
        # the reserved-email check itself also fires unconditionally, ahead
        # of that gate, rather than depending on it.
        auth_settings.AUTH_MODE = "single_user"
        response = auth_client.post(
            "/api/v1/auth/signup",
            json={"email": LOCAL_USER_EMAIL, "password": "password123"},
        )
        assert response.status_code == 400
        assert "reserved" in response.json()["error"]["message"].lower()

    def test_rejected_case_insensitively(self, auth_client):
        auth_settings.AUTH_MODE = "multi"
        response = auth_client.post(
            "/api/v1/auth/signup",
            json={"email": LOCAL_USER_EMAIL.upper(), "password": "password123"},
        )
        assert response.status_code == 400

    def test_other_emails_still_accepted_in_multi_mode(self, auth_client):
        auth_settings.AUTH_MODE = "multi"
        response = auth_client.post(
            "/api/v1/auth/signup",
            json={"email": "genuinely-new@example.com", "password": "password123"},
        )
        assert response.status_code == 200


# -- POST /api/v1/auth/refresh gated by AUTH_MODE=single_user --


class TestRefreshDisabledInSingleUserMode:
    def test_refresh_403s_in_single_user_mode_with_previously_valid_token(
        self, auth_client
    ):
        # Mint a token pair the way multi mode normally would, while still
        # in multi mode -- i.e. a token that was genuinely valid before the
        # switch (or before the reserved-email squatting path above was
        # closed).
        auth_settings.AUTH_MODE = "multi"
        signup = auth_client.post(
            "/api/v1/auth/signup",
            json={"email": "refresh-user@example.com", "password": "password123"},
        )
        assert signup.status_code == 200
        refresh_token = signup.json()["data"]["refresh_token"]

        # Confirm the token actually works before flipping modes, so the
        # 403 below is attributable to the mode gate, not an invalid token.
        works = auth_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert works.status_code == 200
        refresh_token = works.json()["data"]["refresh_token"]

        auth_settings.AUTH_MODE = "single_user"
        response = auth_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert response.status_code == 403

    def test_refresh_still_works_in_multi_mode(self, auth_client):
        auth_settings.AUTH_MODE = "multi"
        signup = auth_client.post(
            "/api/v1/auth/signup",
            json={"email": "refresh-user2@example.com", "password": "password123"},
        )
        refresh_token = signup.json()["data"]["refresh_token"]

        response = auth_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert response.status_code == 200


# -- GET /api/v1/config --


def _create_config_test_app() -> FastAPI:
    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = FastAPI(lifespan=noop_lifespan)

    from src.api.versions.v1.routers.config import router as config_router

    app.include_router(config_router, prefix="/api/v1")
    return app


class TestConfigEndpoint:
    def test_reports_multi_by_default(self):
        auth_settings.AUTH_MODE = "multi"
        app = _create_config_test_app()
        with TestClient(app) as c:
            response = c.get("/api/v1/config")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["auth_mode"] == "multi"

    def test_reports_single_user_when_set(self):
        auth_settings.AUTH_MODE = "single_user"
        app = _create_config_test_app()
        with TestClient(app) as c:
            response = c.get("/api/v1/config")
        assert response.status_code == 200
        assert response.json()["data"]["auth_mode"] == "single_user"

    def test_offers_no_oauth_provider_without_credentials(self):
        """An unconfigured provider is not advertised.

        Its authorize endpoint answers with an error, so a login screen that
        showed the button would be offering a dead end.
        """
        from src.core.oauth_config import oauth_settings

        original = (
            oauth_settings.OAUTH_GOOGLE_CLIENT_ID,
            oauth_settings.OAUTH_GOOGLE_CLIENT_SECRET,
        )
        auth_settings.AUTH_MODE = "multi"
        app = _create_config_test_app()
        try:
            oauth_settings.OAUTH_GOOGLE_CLIENT_ID = ""
            oauth_settings.OAUTH_GOOGLE_CLIENT_SECRET = ""
            with TestClient(app) as c:
                assert c.get("/api/v1/config").json()["data"]["oauth_providers"] == []

            oauth_settings.OAUTH_GOOGLE_CLIENT_ID = "id"
            oauth_settings.OAUTH_GOOGLE_CLIENT_SECRET = "secret"
            with TestClient(app) as c:
                assert c.get("/api/v1/config").json()["data"]["oauth_providers"] == [
                    "google"
                ]
        finally:
            (
                oauth_settings.OAUTH_GOOGLE_CLIENT_ID,
                oauth_settings.OAUTH_GOOGLE_CLIENT_SECRET,
            ) = original

    def test_no_secrets_in_response(self):
        """The payload is an exact whitelist, deliberately.

        This endpoint answers before authentication, so anything added to it
        is public. Asserting the whole key set means a new field has to be
        looked at here before it can ship.
        """
        auth_settings.AUTH_MODE = "multi"
        app = _create_config_test_app()
        with TestClient(app) as c:
            response = c.get("/api/v1/config")
        keys = set(response.json()["data"].keys())
        assert keys == {
            "auth_mode",
            # Which external sign-ins are configured, by name. No client ids,
            # no secrets: the login screen only needs to know what to offer.
            "oauth_providers",
            # Which machine-facing entry points this deployment serves, and
            # where -- paths and flags, no credentials.
            "mcp_enabled",
            "mcp_path",
            "http_api_enabled",
            "http_api_path",
            "openapi_url",
            "docs_url",
        }
