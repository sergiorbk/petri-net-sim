"""Resolver tests for the BYOK-only credential pipeline."""

from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from src.core.agent_config import LLMProvider
from src.infrastructure.postgres.models.user import User
from src.services.crypto.factory import reset_cipher
from src.services.crypto.fernet_cipher import FernetCipher
from src.services.llm.credential_service import CredentialService
from src.services.llm.credentials_resolver import (
    ByokRequiredError,
    CredentialsResolver,
    InvalidCredentialError,
)


@pytest.fixture(autouse=True)
def _reset_cipher():
    reset_cipher()
    yield
    reset_cipher()


@pytest.fixture
def cipher() -> FernetCipher:
    return FernetCipher(Fernet.generate_key().decode("utf-8"))


@pytest.fixture
def credential_service(session, cipher: FernetCipher) -> CredentialService:
    return CredentialService(session, cipher)


# --- BYOK happy path ---


async def test_resolves_byok_credential(password_user: User, credential_service):
    cred = await credential_service.create(
        user_id=password_user.id,
        name="My OpenAI",
        provider="openai",
        model="gpt-4o",
        api_key="sk-proj-real-1234567890",
        base_url=None,
    )

    resolver = CredentialsResolver(credential_service)
    resolved = await resolver.resolve(
        password_user, {"llm_credential_id": str(cred.id)}
    )

    assert resolved.source == "byok"
    assert resolved.profile_id == cred.id
    assert resolved.profile_name == "My OpenAI"
    assert resolved.credentials.provider == LLMProvider.OPENAI
    assert resolved.credentials.api_key == "sk-proj-real-1234567890"
    assert resolved.credentials.model == "gpt-4o"


# --- BYOK error paths (no credential => 402 byok_required) ---


async def test_missing_metadata_raises(password_user: User, credential_service):
    resolver = CredentialsResolver(credential_service)
    with pytest.raises(ByokRequiredError):
        await resolver.resolve(password_user, None)


async def test_empty_metadata_raises(password_user: User, credential_service):
    resolver = CredentialsResolver(credential_service)
    with pytest.raises(ByokRequiredError):
        await resolver.resolve(password_user, {})


async def test_unknown_credential_id_raises(password_user: User, credential_service):
    resolver = CredentialsResolver(credential_service)
    with pytest.raises(InvalidCredentialError):
        await resolver.resolve(
            password_user, {"llm_credential_id": str(uuid4())}
        )


async def test_other_users_credential_rejected(
    password_user: User, regular_user: User, credential_service
):
    cred = await credential_service.create(
        user_id=password_user.id,
        name="alice-only",
        provider="openai",
        model="gpt-4o",
        api_key="sk-1234567890",
        base_url=None,
    )
    resolver = CredentialsResolver(credential_service)
    with pytest.raises(InvalidCredentialError):
        await resolver.resolve(
            regular_user, {"llm_credential_id": str(cred.id)}
        )


async def test_malformed_uuid_raises(password_user: User, credential_service):
    resolver = CredentialsResolver(credential_service)
    with pytest.raises(InvalidCredentialError):
        await resolver.resolve(
            password_user, {"llm_credential_id": "not-a-uuid"}
        )


# --- API key credential binding ---


async def test_resolver_uses_api_key_binding(password_user: User, credential_service):
    """When no metadata is present but the API key has a bound credential, use it."""
    cred = await credential_service.create(
        user_id=password_user.id,
        name="Bound Credential",
        provider="openai",
        model="gpt-4o-mini",
        api_key="sk-bound-key",
        base_url=None,
    )

    resolver = CredentialsResolver(credential_service)
    resolved = await resolver.resolve(
        password_user,
        metadata=None,
        api_key_credential_id=cred.id,
    )

    assert resolved.source == "byok"
    assert resolved.profile_id == cred.id
    assert resolved.profile_name == "Bound Credential"
    assert resolved.credentials.api_key == "sk-bound-key"


async def test_metadata_takes_priority_over_key_binding(
    password_user: User, credential_service
):
    """metadata.llm_credential_id wins over api_key_credential_id."""
    cred_meta = await credential_service.create(
        user_id=password_user.id,
        name="Metadata Cred",
        provider="openai",
        model="gpt-4o",
        api_key="sk-from-metadata",
        base_url=None,
    )
    cred_key = await credential_service.create(
        user_id=password_user.id,
        name="Key Binding Cred",
        provider="openai",
        model="gpt-4o-mini",
        api_key="sk-from-key-binding",
        base_url=None,
    )

    resolver = CredentialsResolver(credential_service)
    resolved = await resolver.resolve(
        password_user,
        metadata={"llm_credential_id": str(cred_meta.id)},
        api_key_credential_id=cred_key.id,
    )

    assert resolved.profile_id == cred_meta.id
    assert resolved.credentials.api_key == "sk-from-metadata"


async def test_resolver_falls_through_without_binding(
    password_user: User, credential_service
):
    """No metadata, no key binding → ByokRequiredError."""
    resolver = CredentialsResolver(credential_service)
    with pytest.raises(ByokRequiredError):
        await resolver.resolve(
            password_user,
            metadata=None,
            api_key_credential_id=None,
        )
