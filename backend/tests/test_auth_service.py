"""Tests for authentication services: password hashing, JWT, API keys, AuthService."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.auth.auth_service import AuthService, hash_password, verify_password
from src.services.auth.jwt_service import JWTService
from src.services.auth.api_key_service import ApiKeyService, API_KEY_PREFIX


# -- Password hashing --


class TestPasswordHashing:
    def test_hash_password_returns_bcrypt_string(self):
        hashed = hash_password("secret123")
        assert hashed.startswith("$2b$")

    def test_hash_password_different_salts(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # different salts

    def test_verify_password_correct(self):
        hashed = hash_password("mypassword")
        assert verify_password("mypassword", hashed) is True

    def test_verify_password_incorrect(self):
        hashed = hash_password("mypassword")
        assert verify_password("wrongpassword", hashed) is False

    def test_verify_password_empty(self):
        hashed = hash_password("notempty")
        assert verify_password("", hashed) is False


# -- JWT Service --


class TestJWTService:
    @pytest.fixture
    def jwt_service(self):
        return JWTService(
            secret_key="test-secret-key-for-tests",
            algorithm="HS256",
            access_token_expire_minutes=30,
            refresh_token_expire_days=7,
        )

    def test_create_access_token(self, jwt_service: JWTService):
        user_id = uuid4()
        token = jwt_service.create_access_token(user_id, "test@example.com")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_access_token(self, jwt_service: JWTService):
        user_id = uuid4()
        token = jwt_service.create_access_token(user_id, "test@example.com")
        payload = jwt_service.verify_access_token(token)
        assert payload is not None
        assert payload["sub"] == str(user_id)
        assert payload["email"] == "test@example.com"
        assert payload["type"] == "access"

    def test_verify_access_token_rejects_refresh(self, jwt_service: JWTService):
        user_id = uuid4()
        token = jwt_service.create_refresh_token(user_id)
        payload = jwt_service.verify_access_token(token)
        assert payload is None

    def test_create_refresh_token(self, jwt_service: JWTService):
        user_id = uuid4()
        token = jwt_service.create_refresh_token(user_id)
        assert isinstance(token, str)

    def test_verify_refresh_token(self, jwt_service: JWTService):
        user_id = uuid4()
        token = jwt_service.create_refresh_token(user_id)
        payload = jwt_service.verify_refresh_token(token)
        assert payload is not None
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "refresh"

    def test_verify_refresh_token_rejects_access(self, jwt_service: JWTService):
        user_id = uuid4()
        token = jwt_service.create_access_token(user_id, "test@example.com")
        payload = jwt_service.verify_refresh_token(token)
        assert payload is None

    def test_create_token_pair(self, jwt_service: JWTService):
        user_id = uuid4()
        access, refresh = jwt_service.create_token_pair(user_id, "test@example.com")
        assert jwt_service.verify_access_token(access) is not None
        assert jwt_service.verify_refresh_token(refresh) is not None

    def test_verify_invalid_token(self, jwt_service: JWTService):
        assert jwt_service.verify_token("not.a.valid.token") is None

    def test_verify_wrong_secret(self, jwt_service: JWTService):
        user_id = uuid4()
        token = jwt_service.create_access_token(user_id, "test@example.com")

        other_service = JWTService(secret_key="different-secret")
        assert other_service.verify_token(token) is None

    def test_get_user_id_from_token(self, jwt_service: JWTService):
        user_id = uuid4()
        token = jwt_service.create_access_token(user_id, "test@example.com")
        extracted = jwt_service.get_user_id_from_token(token)
        assert extracted == user_id

    def test_get_user_id_invalid_token(self, jwt_service: JWTService):
        assert jwt_service.get_user_id_from_token("garbage") is None

    def test_additional_claims(self, jwt_service: JWTService):
        user_id = uuid4()
        token = jwt_service.create_access_token(
            user_id, "test@example.com", additional_claims={"role": "admin"}
        )
        payload = jwt_service.verify_access_token(token)
        assert payload["role"] == "admin"

    def test_expired_token(self):
        service = JWTService(
            secret_key="test-secret",
            access_token_expire_minutes=-1,  # already expired
        )
        user_id = uuid4()
        token = service.create_access_token(user_id, "test@example.com")
        assert service.verify_access_token(token) is None


# -- API Key Service --


class TestApiKeyService:
    @pytest.fixture
    def api_key_service(self, session: AsyncSession):
        return ApiKeyService(session)

    async def test_create_key_format(self, api_key_service: ApiKeyService, regular_user):
        raw_key, key_id = await api_key_service.create_key(regular_user.id, "test-key")
        assert raw_key.startswith(API_KEY_PREFIX)
        assert len(raw_key) > len(API_KEY_PREFIX)
        assert key_id is not None

    async def test_authenticate_valid_key(self, api_key_service: ApiKeyService, regular_user):
        raw_key, _ = await api_key_service.create_key(regular_user.id, "test-key")
        result = await api_key_service.authenticate(raw_key)
        assert result is not None
        assert result.user.id == regular_user.id
        assert result.key_hash == ApiKeyService.hash_key(raw_key)

    async def test_authenticate_invalid_key(self, api_key_service: ApiKeyService):
        result = await api_key_service.authenticate("sk-nonexistentkey12345")
        assert result is None

    async def test_authenticate_inactive_user(
        self, api_key_service: ApiKeyService, inactive_user
    ):
        raw_key, _ = await api_key_service.create_key(inactive_user.id, "test")
        # User is inactive — authentication should fail
        result = await api_key_service.authenticate(raw_key)
        assert result is None

    async def test_list_keys(self, api_key_service: ApiKeyService, regular_user):
        await api_key_service.create_key(regular_user.id, "key-1")
        await api_key_service.create_key(regular_user.id, "key-2")
        keys = await api_key_service.list_keys(regular_user.id)
        assert len(keys) == 2
        names = {k["name"] for k in keys}
        assert names == {"key-1", "key-2"}
        # Must not expose hashes
        for k in keys:
            assert "key_hash" not in k
            assert "prefix" in k
            assert k["prefix"].startswith("sk-")

    async def test_revoke_key(self, api_key_service: ApiKeyService, regular_user):
        raw_key, key_id = await api_key_service.create_key(regular_user.id, "to-revoke")
        revoked = await api_key_service.revoke_key(key_id, regular_user.id)
        assert revoked is True
        # Should not authenticate after revocation
        result = await api_key_service.authenticate(raw_key)
        assert result is None

    async def test_revoke_nonexistent_key(self, api_key_service: ApiKeyService, regular_user):
        revoked = await api_key_service.revoke_key(uuid4(), regular_user.id)
        assert revoked is False

    async def test_revoke_wrong_owner(self, api_key_service: ApiKeyService, regular_user, password_user):
        raw_key, key_id = await api_key_service.create_key(regular_user.id, "owned")
        # different user tries to revoke via service (ownership check)
        revoked = await api_key_service.revoke_key(key_id, password_user.id)
        assert revoked is False

    async def test_hash_key_deterministic(self):
        h1 = ApiKeyService.hash_key("sk-abc123")
        h2 = ApiKeyService.hash_key("sk-abc123")
        assert h1 == h2

    async def test_hash_key_different_for_different_keys(self):
        h1 = ApiKeyService.hash_key("sk-abc123")
        h2 = ApiKeyService.hash_key("sk-def456")
        assert h1 != h2

    # -- last_used_at throttling --

    def test_should_record_last_used_when_never_used(self):
        # A key that has never been used must always record on first auth.
        assert ApiKeyService._should_record_last_used(None) is True

    def test_should_record_last_used_stale_timestamp(self):
        from datetime import UTC, datetime, timedelta

        from src.core.auth_config import auth_settings

        stale = datetime.now(UTC) - timedelta(
            seconds=auth_settings.API_KEY_LAST_USED_THROTTLE_SECONDS + 60
        )
        assert ApiKeyService._should_record_last_used(stale) is True

    def test_should_record_last_used_fresh_timestamp(self):
        from datetime import UTC, datetime, timedelta

        # Well within the throttle window — no write should be performed.
        recent = datetime.now(UTC) - timedelta(seconds=1)
        assert ApiKeyService._should_record_last_used(recent) is False

    def test_should_record_last_used_naive_timestamp(self):
        from datetime import UTC, datetime, timedelta

        # Legacy/SQLite naive timestamps are treated as UTC, not crashed on.
        recent_naive = (datetime.now(UTC) - timedelta(seconds=1)).replace(tzinfo=None)
        assert ApiKeyService._should_record_last_used(recent_naive) is False

    async def test_authenticate_skips_write_within_throttle_window(
        self, api_key_service: ApiKeyService, regular_user, monkeypatch
    ):
        raw_key, _ = await api_key_service.create_key(regular_user.id, "throttle")

        # First auth records last_used_at (was None).
        first = await api_key_service.authenticate(raw_key)
        assert first is not None

        # Second auth, immediately after, is within the window: it must NOT issue
        # another last_used_at write.
        write_calls = 0
        original = api_key_service._api_key_repo.update_last_used

        async def _spy(key_id, throttle_seconds=0):
            nonlocal write_calls
            write_calls += 1
            return await original(key_id, throttle_seconds=throttle_seconds)

        monkeypatch.setattr(api_key_service._api_key_repo, "update_last_used", _spy)

        second = await api_key_service.authenticate(raw_key)
        assert second is not None
        assert write_calls == 0

    async def test_authenticate_writes_when_throttle_disabled(
        self, api_key_service: ApiKeyService, regular_user, monkeypatch
    ):
        from src.core.auth_config import auth_settings

        # Threshold <= 0 disables the throttle: every auth records last_used_at.
        monkeypatch.setattr(auth_settings, "API_KEY_LAST_USED_THROTTLE_SECONDS", 0)

        raw_key, _ = await api_key_service.create_key(regular_user.id, "no-throttle")
        await api_key_service.authenticate(raw_key)

        write_calls = 0
        original = api_key_service._api_key_repo.update_last_used

        async def _spy(key_id, throttle_seconds=0):
            nonlocal write_calls
            write_calls += 1
            return await original(key_id, throttle_seconds=throttle_seconds)

        monkeypatch.setattr(api_key_service._api_key_repo, "update_last_used", _spy)

        await api_key_service.authenticate(raw_key)
        assert write_calls == 1


# -- AuthService --


class TestAuthService:
    async def test_register_with_password_creates_user(self, session: AsyncSession):
        service = AuthService(session)
        user, access, refresh = await service.register_with_password(
            "new@test.local", "password123", name="New"
        )
        assert user.email == "new@test.local"
        assert user.name == "New"
        assert user.password_hash is not None
        assert isinstance(access, str) and isinstance(refresh, str)

    async def test_register_with_password_duplicate_email(self, session: AsyncSession, password_user):
        service = AuthService(session)
        with pytest.raises(ValueError):
            await service.register_with_password("user@test.local", "password123")

    async def test_authenticate_credentials_valid(self, session: AsyncSession, password_user):
        service = AuthService(session)
        result = await service.authenticate_credentials("user@test.local", "password123")
        assert result is not None
        user, access, refresh = result
        assert user.id == password_user.id
        assert isinstance(access, str)
        assert isinstance(refresh, str)

    async def test_authenticate_credentials_wrong_password(self, session: AsyncSession, password_user):
        service = AuthService(session)
        result = await service.authenticate_credentials("user@test.local", "wrongpass")
        assert result is None

    async def test_authenticate_credentials_nonexistent_email(self, session: AsyncSession):
        service = AuthService(session)
        result = await service.authenticate_credentials("nobody@test.local", "password123")
        assert result is None

    async def test_authenticate_credentials_inactive_user(self, session: AsyncSession, inactive_user):
        service = AuthService(session)
        result = await service.authenticate_credentials("inactive@test.local", "pass12345")
        assert result is None

    async def test_authenticate_credentials_no_password_hash(self, session: AsyncSession, regular_user):
        """OAuth-only user without password_hash cannot login via password."""
        service = AuthService(session)
        result = await service.authenticate_credentials("oauth@test.local", "anything")
        assert result is None

    async def test_get_current_user_valid_token(self, session: AsyncSession, password_user):
        service = AuthService(session)
        result = await service.authenticate_credentials("user@test.local", "password123")
        assert result is not None
        _, access, _ = result
        user = await service.get_current_user(access)
        assert user is not None
        assert user.id == password_user.id

    async def test_get_current_user_invalid_token(self, session: AsyncSession):
        service = AuthService(session)
        user = await service.get_current_user("invalid-token")
        assert user is None

    async def test_get_user_by_id(self, session: AsyncSession, password_user):
        service = AuthService(session)
        user = await service.get_user_by_id(password_user.id)
        assert user is not None
        assert user.email == "user@test.local"

    async def test_get_user_by_id_nonexistent(self, session: AsyncSession):
        service = AuthService(session)
        user = await service.get_user_by_id(uuid4())
        assert user is None
