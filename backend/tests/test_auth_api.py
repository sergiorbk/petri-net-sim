"""Tests for /v1/auth/* API endpoints."""

from contextlib import asynccontextmanager
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.user import User
from src.services.auth.api_key_service import ApiKeyService
from src.services.auth.auth_service import hash_password
from src.services.auth.jwt_service import get_jwt_service


# -- Helpers --

DB_MODULE = "src.infrastructure.postgres.database"


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app with only auth API routes (no lifespan)."""
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


# -- Fixtures --


@pytest.fixture
def app():
    return _create_test_app()


@pytest.fixture
def client(app, session_factory):
    """TestClient with DB patched."""
    with patch(f"{DB_MODULE}.AsyncSessionLocal", new=session_factory), \
         patch("src.infrastructure.postgres.database.get_postgres_session") as mock_get_session:

        async def _get_session():
            async with session_factory() as sess:
                yield sess

        mock_get_session.side_effect = _get_session

        # Also patch the dependency directly in the FastAPI dependency overrides
        from src.core.dependencies import get_postgres_session

        async def _override_session():
            async with session_factory() as sess:
                yield sess

        app.dependency_overrides[get_postgres_session] = _override_session

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

        app.dependency_overrides.clear()


# -- /v1/auth/signup & /v1/auth/login --


class TestSignup:
    def test_signup_creates_user_and_returns_tokens(self, client):
        response = client.post(
            "/api/v1/auth/signup",
            json={"email": "signup@example.com", "password": "password123", "name": "Signup"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["access_token"]
        assert data["data"]["refresh_token"]
        assert data["data"]["token_type"] == "bearer"
        assert data["data"]["expires_in"] > 0

        # Token should work for /auth/me
        access = data["data"]["access_token"]
        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert me.status_code == 200
        assert me.json()["data"]["email"] == "signup@example.com"

    def test_signup_rejects_duplicate_email(self, client):
        first = client.post(
            "/api/v1/auth/signup",
            json={"email": "dup@example.com", "password": "password123"},
        )
        assert first.status_code == 200

        dup = client.post(
            "/api/v1/auth/signup",
            json={"email": "dup@example.com", "password": "password123"},
        )
        assert dup.status_code in (400, 422)

    def test_signup_requires_min_password_length(self, client):
        response = client.post(
            "/api/v1/auth/signup",
            json={"email": "short@example.com", "password": "abc"},
        )
        assert response.status_code == 422


class TestLogin:
    def _signup(self, client, email: str, password: str):
        response = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": password},
        )
        assert response.status_code == 200

    def test_login_valid(self, client):
        self._signup(client, "login@example.com", "password123")

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "password123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["access_token"]
        assert data["data"]["refresh_token"]

    def test_login_wrong_password(self, client):
        self._signup(client, "wrongpw@example.com", "password123")

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "wrongpw@example.com", "password": "badpass123"},
        )
        assert response.status_code == 401

    def test_login_nonexistent_user(self, client):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@example.com", "password": "password123"},
        )
        assert response.status_code == 401


# -- /v1/auth/me --


class TestAuthMe:
    def test_me_with_jwt_auth(self, client, session_factory):
        """GET /auth/me returns user info when authenticated with JWT."""
        import asyncio
        from src.infrastructure.postgres.repositories.user_repository import UserRepository

        user_data = {}

        async def _seed():
            async with session_factory() as sess:
                repo = UserRepository(sess)
                u = await repo.create(
                    email="me-jwt@example.com",
                    name="JWT User",
                    password_hash=hash_password("pass12345"),
                )
                await sess.commit()
                user_data["id"] = u.id
                user_data["email"] = u.email

        asyncio.get_event_loop().run_until_complete(_seed())

        jwt_svc = get_jwt_service()
        token = jwt_svc.create_access_token(user_data["id"], user_data["email"])

        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["email"] == "me-jwt@example.com"
        assert "role" not in data["data"]

    def test_me_without_auth(self, client):
        """GET /auth/me without auth returns 401."""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401

    def test_me_invalid_token(self, client):
        """GET /auth/me with invalid token returns 401."""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token-xxx"},
        )
        assert response.status_code == 401

    def test_profile_edits_outlive_the_request(self, client, session_factory):
        """PATCH /auth/me persists rather than echoing back a rolled-back value.

        The repository only flushes and the session dependency does not
        commit, so this asserts on a second request: the response body alone
        looked correct even while every edit was being discarded.
        """
        import asyncio
        from src.infrastructure.postgres.repositories.user_repository import UserRepository

        user_data = {}

        async def _seed():
            async with session_factory() as sess:
                repo = UserRepository(sess)
                u = await repo.create(email="persist@example.com", name="Persist")
                await sess.commit()
                user_data["id"] = u.id
                user_data["email"] = u.email

        asyncio.get_event_loop().run_until_complete(_seed())

        token = get_jwt_service().create_access_token(
            user_data["id"], user_data["email"]
        )
        headers = {"Authorization": f"Bearer {token}"}

        patched = client.patch(
            "/api/v1/auth/me",
            json={"display_name": "Ada", "custom_instructions": "Be brief"},
            headers=headers,
        )
        assert patched.status_code == 200

        reread = client.get("/api/v1/auth/me", headers=headers).json()["data"]
        assert reread["display_name"] == "Ada"
        assert reread["custom_instructions"] == "Be brief"


# -- /v1/auth/api-keys --


class TestAuthApiKeys:
    def test_create_api_key(self, client, session_factory):
        """POST /auth/api-keys creates a new key for the authenticated user."""
        import asyncio
        from src.infrastructure.postgres.repositories.user_repository import UserRepository

        user_data = {}

        async def _seed():
            async with session_factory() as sess:
                repo = UserRepository(sess)
                u = await repo.create(
                    email="keymaker@example.com",
                    name="Key Maker",
                    password_hash=hash_password("pass12345"),
                )
                await sess.commit()
                user_data["id"] = u.id
                user_data["email"] = u.email

        asyncio.get_event_loop().run_until_complete(_seed())

        jwt_svc = get_jwt_service()
        token = jwt_svc.create_access_token(user_data["id"], user_data["email"])

        response = client.post(
            "/api/v1/auth/api-keys",
            json={"name": "my-key"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["key"].startswith("sk-")
        assert data["data"]["name"] == "my-key"

    def test_list_api_keys(self, client, session_factory):
        """GET /auth/api-keys lists the user's keys."""
        import asyncio
        from src.infrastructure.postgres.repositories.user_repository import UserRepository

        user_data = {}

        async def _seed():
            async with session_factory() as sess:
                repo = UserRepository(sess)
                u = await repo.create(
                    email="lister@example.com",
                    name="Lister",
                    password_hash=hash_password("pass12345"),
                )
                svc = ApiKeyService(sess)
                await svc.create_key(u.id, "key-1")
                await svc.create_key(u.id, "key-2")
                await sess.commit()
                user_data["id"] = u.id
                user_data["email"] = u.email

        asyncio.get_event_loop().run_until_complete(_seed())

        jwt_svc = get_jwt_service()
        token = jwt_svc.create_access_token(user_data["id"], user_data["email"])

        response = client.get(
            "/api/v1/auth/api-keys",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 2
        names = {k["name"] for k in data["data"]}
        assert names == {"key-1", "key-2"}

    def test_revoke_api_key(self, client, session_factory):
        """DELETE /auth/api-keys/{id} revokes a key."""
        import asyncio
        from src.infrastructure.postgres.repositories.user_repository import UserRepository

        user_data = {}

        async def _seed():
            async with session_factory() as sess:
                repo = UserRepository(sess)
                u = await repo.create(
                    email="revoker@example.com",
                    name="Revoker",
                    password_hash=hash_password("pass12345"),
                )
                svc = ApiKeyService(sess)
                _, key_id = await svc.create_key(u.id, "to-revoke")
                await sess.commit()
                user_data["id"] = u.id
                user_data["email"] = u.email
                user_data["key_id"] = key_id

        asyncio.get_event_loop().run_until_complete(_seed())

        jwt_svc = get_jwt_service()
        token = jwt_svc.create_access_token(user_data["id"], user_data["email"])

        response = client.delete(
            f"/api/v1/auth/api-keys/{user_data['key_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["revoked"] is True

    def test_create_api_key_without_auth(self, client):
        response = client.post("/api/v1/auth/api-keys", json={"name": "test"})
        assert response.status_code == 401

    def test_list_api_keys_without_auth(self, client):
        response = client.get("/api/v1/auth/api-keys")
        assert response.status_code == 401

    def test_revoke_api_key_without_auth(self, client):
        response = client.delete(f"/api/v1/auth/api-keys/{uuid4()}")
        assert response.status_code == 401

    def test_revoke_nonexistent_key(self, client, session_factory):
        """DELETE /auth/api-keys/{id} with nonexistent key returns 404."""
        import asyncio
        from src.infrastructure.postgres.repositories.user_repository import UserRepository

        user_data = {}

        async def _seed():
            async with session_factory() as sess:
                repo = UserRepository(sess)
                u = await repo.create(
                    email="nonfound@example.com",
                    name="Not Found",
                    password_hash=hash_password("pass12345"),
                )
                await sess.commit()
                user_data["id"] = u.id
                user_data["email"] = u.email

        asyncio.get_event_loop().run_until_complete(_seed())

        jwt_svc = get_jwt_service()
        token = jwt_svc.create_access_token(user_data["id"], user_data["email"])

        response = client.delete(
            f"/api/v1/auth/api-keys/{uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


# -- API Key authentication flow (unit-level) --


class TestApiKeyAuthFlow:
    async def test_full_api_key_lifecycle(self, session: AsyncSession, regular_user):
        """Create key, authenticate, list, revoke, verify revoked."""
        svc = ApiKeyService(session)

        raw_key, key_id = await svc.create_key(regular_user.id, "lifecycle-test")
        assert raw_key.startswith("sk-")

        result = await svc.authenticate(raw_key)
        assert result is not None
        assert result.user.id == regular_user.id

        keys = await svc.list_keys(regular_user.id)
        assert any(k["id"] == key_id for k in keys)

        revoked = await svc.revoke_key(key_id, regular_user.id)
        assert revoked is True

        result = await svc.authenticate(raw_key)
        assert result is None

    async def test_multiple_keys_per_user(self, session: AsyncSession, regular_user):
        svc = ApiKeyService(session)
        key1, _ = await svc.create_key(regular_user.id, "key-1")
        key2, _ = await svc.create_key(regular_user.id, "key-2")

        r1 = await svc.authenticate(key1)
        r2 = await svc.authenticate(key2)
        assert r1 is not None
        assert r2 is not None
        assert r1.key_hash != r2.key_hash


# -- API Key ↔ LLM Credential binding --


class TestApiKeyCredentialBinding:
    """Tests for binding an API key to a specific LLM credential profile."""

    def _seed_user_with_credential(self, session_factory) -> dict:
        """Create a user and an LLM credential, return their IDs and a JWT."""
        import asyncio
        from cryptography.fernet import Fernet

        from src.infrastructure.postgres.repositories.user_repository import UserRepository
        from src.services.crypto.fernet_cipher import FernetCipher
        from src.services.llm.credential_service import CredentialService

        result = {}

        async def _seed():
            async with session_factory() as sess:
                repo = UserRepository(sess)
                u = await repo.create(
                    email=f"binding-{uuid4().hex[:6]}@example.com",
                    name="Binding User",
                    password_hash=hash_password("pass12345"),
                )
                cipher = FernetCipher(Fernet.generate_key().decode("utf-8"))
                cred_svc = CredentialService(sess, cipher)
                cred = await cred_svc.create(
                    user_id=u.id,
                    name="My OpenAI",
                    provider="openai",
                    model="gpt-4o",
                    api_key="sk-test-binding",
                    base_url=None,
                )
                await sess.commit()
                result["user_id"] = u.id
                result["user_email"] = u.email
                result["cred_id"] = cred.id

        asyncio.get_event_loop().run_until_complete(_seed())

        jwt_svc = get_jwt_service()
        result["token"] = jwt_svc.create_access_token(result["user_id"], result["user_email"])
        return result

    def test_create_key_with_credential_binding(self, client, session_factory):
        """POST /auth/api-keys with llm_credential_id → key is bound, response shows id."""
        ctx = self._seed_user_with_credential(session_factory)

        response = client.post(
            "/api/v1/auth/api-keys",
            json={"name": "bound-key", "llm_credential_id": str(ctx["cred_id"])},
            headers={"Authorization": f"Bearer {ctx['token']}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["llm_credential_id"] == str(ctx["cred_id"])
        assert data["data"]["key"].startswith("sk-")

    def test_create_key_without_binding(self, client, session_factory):
        """POST /auth/api-keys without llm_credential_id → unbound key, backward compat."""
        ctx = self._seed_user_with_credential(session_factory)

        response = client.post(
            "/api/v1/auth/api-keys",
            json={"name": "unbound-key"},
            headers={"Authorization": f"Bearer {ctx['token']}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["llm_credential_id"] is None

    def test_create_key_wrong_user_credential(self, client, session_factory):
        """Binding to another user's credential returns 400."""
        import asyncio
        from cryptography.fernet import Fernet

        from src.infrastructure.postgres.repositories.user_repository import UserRepository
        from src.services.crypto.fernet_cipher import FernetCipher
        from src.services.llm.credential_service import CredentialService

        other_cred_id = None

        async def _seed_other():
            nonlocal other_cred_id
            async with session_factory() as sess:
                repo = UserRepository(sess)
                other = await repo.create(
                    email=f"other-{uuid4().hex[:6]}@example.com",
                    name="Other User",
                    password_hash=hash_password("pass12345"),
                )
                cipher = FernetCipher(Fernet.generate_key().decode("utf-8"))
                cred_svc = CredentialService(sess, cipher)
                cred = await cred_svc.create(
                    user_id=other.id,
                    name="Other Cred",
                    provider="openai",
                    model="gpt-4o",
                    api_key="sk-other",
                    base_url=None,
                )
                await sess.commit()
                other_cred_id = cred.id

        asyncio.get_event_loop().run_until_complete(_seed_other())
        ctx = self._seed_user_with_credential(session_factory)

        response = client.post(
            "/api/v1/auth/api-keys",
            json={"name": "stolen-binding", "llm_credential_id": str(other_cred_id)},
            headers={"Authorization": f"Bearer {ctx['token']}"},
        )
        assert response.status_code == 400

    def test_list_keys_shows_credential_name(self, client, session_factory):
        """GET /auth/api-keys returns llm_credential_id and llm_credential_name."""
        import asyncio

        from src.infrastructure.postgres.repositories.user_repository import UserRepository

        ctx = self._seed_user_with_credential(session_factory)

        async def _bind():
            async with session_factory() as sess:
                svc = ApiKeyService(sess)
                await svc.create_key(
                    ctx["user_id"],
                    name="bound",
                    llm_credential_id=ctx["cred_id"],
                )

        asyncio.get_event_loop().run_until_complete(_bind())

        response = client.get(
            "/api/v1/auth/api-keys",
            headers={"Authorization": f"Bearer {ctx['token']}"},
        )
        assert response.status_code == 200
        items = response.json()["data"]
        bound = next(k for k in items if k["name"] == "bound")
        assert bound["llm_credential_id"] == str(ctx["cred_id"])
        assert bound["llm_credential_name"] == "My OpenAI"
