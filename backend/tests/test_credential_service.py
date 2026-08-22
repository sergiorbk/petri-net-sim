"""Tests for CredentialService — mask, CRUD, error branches."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.models.user_llm_credential import UserLLMCredential
from src.services.crypto import DecryptionError
from src.services.crypto.noop_cipher import NoOpCipher
from src.services.llm.credential_service import (
    CredentialAlreadyExistsError,
    CredentialDecryptionError,
    CredentialNotFoundError,
    CredentialService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(session: AsyncSession) -> CredentialService:
    return CredentialService(session, cipher=NoOpCipher())


async def _make_user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"u{uuid.uuid4().hex[:6]}@test.local",
        is_active=True,
        metadata_={},
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# mask
# ---------------------------------------------------------------------------


class TestMask:
    def test_empty_string_returns_empty(self):
        assert CredentialService.mask("") == ""

    def test_none_returns_empty(self):
        assert CredentialService.mask(None) == ""

    def test_short_key_returns_stars(self):
        assert CredentialService.mask("abcde") == "***"

    def test_long_key_shows_preview(self):
        key = "sk-abcdefghijklmnopqrstuvwxyz1234"
        result = CredentialService.mask(key)
        assert result.startswith("sk-abc")
        assert result.endswith("1234")
        assert "..." in result


# ---------------------------------------------------------------------------
# to_credentials
# ---------------------------------------------------------------------------


class TestToCredentials:
    @pytest.mark.anyio
    async def test_converts_row_to_credentials(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = UserLLMCredential(
            id=uuid.uuid4(),
            user_id=user.id,
            name="test",
            provider="openai",
            encrypted_api_key=b"sk-mykey",
            cipher_version=1,
            model="gpt-4o",
        )
        creds = svc.to_credentials(row)
        assert creds.provider.value == "openai"
        assert creds.model == "gpt-4o"

    @pytest.mark.anyio
    async def test_null_api_key_remains_none(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = UserLLMCredential(
            id=uuid.uuid4(),
            user_id=user.id,
            name="ollama",
            provider="ollama",
            encrypted_api_key=None,
            cipher_version=1,
            model="llama3",
        )
        creds = svc.to_credentials(row)
        assert creds.api_key is None

    @pytest.mark.anyio
    async def test_decryption_error_raises(self, session):
        bad_cipher = MagicMock()
        bad_cipher.decrypt.side_effect = DecryptionError("bad")
        svc = CredentialService(session, cipher=bad_cipher)
        user = await _make_user(session)
        row = UserLLMCredential(
            id=uuid.uuid4(),
            user_id=user.id,
            name="x",
            provider="openai",
            encrypted_api_key=b"corrupted",
            cipher_version=1,
            model="gpt-4o",
        )
        with pytest.raises(CredentialDecryptionError):
            svc.to_credentials(row)

    @pytest.mark.anyio
    async def test_unknown_provider_raises(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = UserLLMCredential(
            id=uuid.uuid4(),
            user_id=user.id,
            name="x",
            provider="badprovider",
            encrypted_api_key=None,
            cipher_version=1,
            model="gpt-4",
        )
        with pytest.raises(CredentialDecryptionError, match="unknown provider"):
            svc.to_credentials(row)


# ---------------------------------------------------------------------------
# to_response_dict
# ---------------------------------------------------------------------------


class TestToResponseDict:
    @pytest.mark.anyio
    async def test_returns_masked_key(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        key = "sk-abcdefghijklmnopqrstuvwxyz1234"
        row = UserLLMCredential(
            id=uuid.uuid4(),
            user_id=user.id,
            name="n",
            provider="openai",
            encrypted_api_key=key.encode(),
            cipher_version=1,
            model="gpt-4o",
        )
        d = svc.to_response_dict(row)
        assert "api_key_preview" in d
        assert d["api_key_preview"] != key

    @pytest.mark.anyio
    async def test_decryption_error_shows_question_marks(self, session):
        bad_cipher = MagicMock()
        bad_cipher.decrypt.side_effect = DecryptionError("bad")
        svc = CredentialService(session, cipher=bad_cipher)
        user = await _make_user(session)
        row = UserLLMCredential(
            id=uuid.uuid4(),
            user_id=user.id,
            name="n",
            provider="openai",
            encrypted_api_key=b"corrupted",
            cipher_version=1,
            model="gpt-4o",
        )
        d = svc.to_response_dict(row)
        assert d["api_key_preview"] == "???"

    @pytest.mark.anyio
    async def test_null_key_shows_empty_preview(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = UserLLMCredential(
            id=uuid.uuid4(),
            user_id=user.id,
            name="n",
            provider="ollama",
            encrypted_api_key=None,
            cipher_version=1,
            model="llama3",
        )
        d = svc.to_response_dict(row)
        assert d["api_key_preview"] == ""


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.anyio
    async def test_creates_credential(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = await svc.create(user.id, "MyKey", "openai", "gpt-4o", "sk-test", None)
        assert row.name == "MyKey"
        assert row.provider == "openai"

    @pytest.mark.anyio
    async def test_creates_without_api_key(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = await svc.create(user.id, "Ollama", "ollama", "llama3", None, None)
        assert row.encrypted_api_key is None

    @pytest.mark.anyio
    async def test_duplicate_name_raises(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        await svc.create(user.id, "Dup", "openai", "gpt-4o", "sk-1", None)
        with pytest.raises(CredentialAlreadyExistsError):
            await svc.create(user.id, "Dup", "openai", "gpt-4o", "sk-2", None)


# ---------------------------------------------------------------------------
# list_for_user / get_for_user
# ---------------------------------------------------------------------------


class TestListAndGet:
    @pytest.mark.anyio
    async def test_list_returns_owned(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        await svc.create(user.id, "K1", "openai", "gpt-4o", "sk-1", None)
        await svc.create(user.id, "K2", "openai", "gpt-4o", "sk-2", None)
        items = await svc.list_for_user(user.id)
        assert len(items) == 2

    @pytest.mark.anyio
    async def test_get_for_user_returns_row(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = await svc.create(user.id, "K", "openai", "gpt-4o", "sk-k", None)
        found = await svc.get_for_user(row.id, user.id)
        assert found.id == row.id

    @pytest.mark.anyio
    async def test_get_for_user_raises_not_found(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        with pytest.raises(CredentialNotFoundError):
            await svc.get_for_user(uuid.uuid4(), user.id)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    @pytest.mark.anyio
    async def test_update_name(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = await svc.create(user.id, "Old", "openai", "gpt-4o", "sk-x", None)
        updated = await svc.update(row.id, user.id, name="New")
        assert updated.name == "New"

    @pytest.mark.anyio
    async def test_no_fields_returns_existing(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = await svc.create(user.id, "Same", "openai", "gpt-4o", "sk-x", None)
        result = await svc.update(row.id, user.id)
        assert result.id == row.id

    @pytest.mark.anyio
    async def test_update_not_found_raises(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        with pytest.raises(CredentialNotFoundError):
            await svc.update(uuid.uuid4(), user.id, name="X")

    @pytest.mark.anyio
    async def test_update_api_key_triggers_eviction(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = await svc.create(user.id, "Evict", "openai", "gpt-4o", "sk-old", None)

        mock_factory = AsyncMock()
        mock_factory.evict = AsyncMock()
        with patch("src.services.llm.credential_service.get_llm_factory", return_value=mock_factory):
            await svc.update(row.id, user.id, api_key="sk-new")
        mock_factory.evict.assert_called_once()

    @pytest.mark.anyio
    async def test_update_duplicate_name_raises(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        await svc.create(user.id, "First", "openai", "gpt-4o", "sk-1", None)
        row2 = await svc.create(user.id, "Second", "openai", "gpt-4o", "sk-2", None)
        with pytest.raises(CredentialAlreadyExistsError):
            await svc.update(row2.id, user.id, name="First")

    @pytest.mark.anyio
    async def test_update_model_and_base_url(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = await svc.create(user.id, "M", "openai", "gpt-4o", "sk-x", None)
        updated = await svc.update(row.id, user.id, model="gpt-4", base_url="https://proxy.example.com")
        assert updated.model == "gpt-4"
        assert updated.base_url == "https://proxy.example.com"


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    @pytest.mark.anyio
    async def test_deletes_credential(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = await svc.create(user.id, "Del", "openai", "gpt-4o", "sk-d", None)
        await svc.delete(row.id, user.id)
        with pytest.raises(CredentialNotFoundError):
            await svc.get_for_user(row.id, user.id)

    @pytest.mark.anyio
    async def test_delete_not_found_raises(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        with pytest.raises(CredentialNotFoundError):
            await svc.delete(uuid.uuid4(), user.id)

    @pytest.mark.anyio
    async def test_delete_evicts_cache(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = await svc.create(user.id, "EvictDel", "openai", "gpt-4o", "sk-e", None)

        mock_factory = AsyncMock()
        mock_factory.evict = AsyncMock()
        with patch("src.services.llm.credential_service.get_llm_factory", return_value=mock_factory):
            await svc.delete(row.id, user.id)
        mock_factory.evict.assert_called_once()


# ---------------------------------------------------------------------------
# test (ping LLM)
# ---------------------------------------------------------------------------


class TestTestMethod:
    @pytest.mark.anyio
    async def test_returns_success_with_mock_provider(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = await svc.create(user.id, "Ping", "openai", "gpt-4o", "sk-ping", None)

        mock_response = MagicMock()
        mock_response.content = "pong"
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value=mock_response)

        mock_factory = AsyncMock()
        mock_factory.for_credentials = AsyncMock(return_value=mock_provider)

        with patch("src.services.llm.credential_service.get_llm_factory", return_value=mock_factory):
            success, latency_ms, preview, error = await svc.test(row.id, user.id)

        assert success is True
        assert latency_ms is not None
        assert preview == "pong"
        assert error is None

    @pytest.mark.anyio
    async def test_returns_failure_on_provider_error(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = await svc.create(user.id, "Fail", "openai", "gpt-4o", "sk-fail", None)

        mock_factory = AsyncMock()
        mock_factory.for_credentials = AsyncMock(side_effect=Exception("connection refused"))

        with patch("src.services.llm.credential_service.get_llm_factory", return_value=mock_factory):
            success, latency_ms, preview, error = await svc.test(row.id, user.id)

        assert success is False
        assert latency_ms is None
        assert preview is None
        assert "connection refused" in error

    @pytest.mark.anyio
    async def test_returns_list_content_preview(self, session):
        svc = _make_service(session)
        user = await _make_user(session)
        row = await svc.create(user.id, "Blocks", "anthropic", "claude-3", "sk-b", None)

        mock_response = MagicMock()
        mock_response.content = [{"type": "text", "text": "hello from anthropic"}]
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value=mock_response)

        mock_factory = AsyncMock()
        mock_factory.for_credentials = AsyncMock(return_value=mock_provider)

        with patch("src.services.llm.credential_service.get_llm_factory", return_value=mock_factory):
            success, latency_ms, preview, error = await svc.test(row.id, user.id)

        assert success is True
        assert "hello from anthropic" in preview
