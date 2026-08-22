"""Repository-level tests for user_llm_credentials."""

from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError

from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.user_llm_credential_repository import (
    UserLLMCredentialRepository,
)
from src.services.crypto.fernet_cipher import FernetCipher


@pytest.fixture
def cipher() -> FernetCipher:
    return FernetCipher(Fernet.generate_key().decode("utf-8"))


async def test_create_and_get(session, password_user: User, cipher: FernetCipher):
    repo = UserLLMCredentialRepository(session)
    encrypted = cipher.encrypt("sk-real-secret-key")

    cred = await repo.create(
        user_id=password_user.id,
        name="My OpenAI",
        provider="openai",
        model="gpt-4o",
        encrypted_api_key=encrypted,
        cipher_version=cipher.version,
        base_url=None,
    )
    assert cred.id is not None
    assert cred.deleted_at is None
    assert cred.cipher_version == cipher.version
    assert isinstance(cred.encrypted_api_key, bytes)

    fetched = await repo.get_active(cred.id, password_user.id)
    assert fetched is not None
    assert cipher.decrypt(fetched.encrypted_api_key) == "sk-real-secret-key"


async def test_get_active_returns_none_for_other_user(
    session, password_user: User, regular_user: User, cipher: FernetCipher
):
    repo = UserLLMCredentialRepository(session)
    cred = await repo.create(
        user_id=password_user.id,
        name="Mine",
        provider="openai",
        model="gpt-4o",
        encrypted_api_key=cipher.encrypt("sk-x"),
        cipher_version=cipher.version,
    )

    assert await repo.get_active(cred.id, regular_user.id) is None


async def test_list_excludes_soft_deleted(
    session, password_user: User, cipher: FernetCipher
):
    repo = UserLLMCredentialRepository(session)
    a = await repo.create(
        user_id=password_user.id,
        name="A",
        provider="openai",
        model="gpt-4o",
        encrypted_api_key=cipher.encrypt("sk-a"),
        cipher_version=cipher.version,
    )
    b = await repo.create(
        user_id=password_user.id,
        name="B",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        encrypted_api_key=cipher.encrypt("sk-b"),
        cipher_version=cipher.version,
    )

    await repo.soft_delete(a.id, password_user.id)
    listed = await repo.list_by_user(password_user.id)
    assert {c.id for c in listed} == {b.id}


async def test_unique_active_name_allows_recreation_after_delete(
    session, password_user: User, cipher: FernetCipher
):
    repo = UserLLMCredentialRepository(session)

    first = await repo.create(
        user_id=password_user.id,
        name="dup",
        provider="openai",
        model="gpt-4o",
        encrypted_api_key=cipher.encrypt("sk-1"),
        cipher_version=cipher.version,
    )
    await repo.soft_delete(first.id, password_user.id)

    # Same name should now be reusable.
    second = await repo.create(
        user_id=password_user.id,
        name="dup",
        provider="openai",
        model="gpt-4o",
        encrypted_api_key=cipher.encrypt("sk-2"),
        cipher_version=cipher.version,
    )
    assert second.id != first.id


async def test_unique_active_name_collision(
    session, password_user: User, cipher: FernetCipher
):
    repo = UserLLMCredentialRepository(session)
    await repo.create(
        user_id=password_user.id,
        name="taken",
        provider="openai",
        model="gpt-4o",
        encrypted_api_key=cipher.encrypt("sk-1"),
        cipher_version=cipher.version,
    )

    with pytest.raises(IntegrityError):
        await repo.create(
            user_id=password_user.id,
            name="taken",
            provider="openai",
            model="gpt-4o",
            encrypted_api_key=cipher.encrypt("sk-2"),
            cipher_version=cipher.version,
        )


async def test_update_fields(
    session, password_user: User, cipher: FernetCipher
):
    repo = UserLLMCredentialRepository(session)
    cred = await repo.create(
        user_id=password_user.id,
        name="orig",
        provider="openai",
        model="gpt-4o",
        encrypted_api_key=cipher.encrypt("sk-old"),
        cipher_version=cipher.version,
    )

    new_encrypted = cipher.encrypt("sk-new")
    updated = await repo.update_fields(
        cred.id,
        password_user.id,
        name="renamed",
        model="gpt-4o-mini",
        encrypted_api_key=new_encrypted,
    )
    assert updated is not None
    assert updated.name == "renamed"
    assert updated.model == "gpt-4o-mini"
    assert cipher.decrypt(updated.encrypted_api_key) == "sk-new"


async def test_update_fields_returns_none_for_unknown(
    session, password_user: User, cipher: FernetCipher
):
    import uuid

    repo = UserLLMCredentialRepository(session)
    assert (
        await repo.update_fields(uuid.uuid4(), password_user.id, model="gpt-4o-mini")
        is None
    )


async def test_soft_delete_returns_false_when_not_owned(
    session, password_user: User, regular_user: User, cipher: FernetCipher
):
    repo = UserLLMCredentialRepository(session)
    cred = await repo.create(
        user_id=password_user.id,
        name="x",
        provider="openai",
        model="gpt-4o",
        encrypted_api_key=cipher.encrypt("sk-x"),
        cipher_version=cipher.version,
    )

    deleted = await repo.soft_delete(cred.id, regular_user.id)
    assert deleted is False
    # Still active for the real owner
    assert await repo.get_active(cred.id, password_user.id) is not None


async def test_touch_validated(session, password_user: User, cipher: FernetCipher):
    repo = UserLLMCredentialRepository(session)
    cred = await repo.create(
        user_id=password_user.id,
        name="t",
        provider="openai",
        model="gpt-4o",
        encrypted_api_key=cipher.encrypt("sk-x"),
        cipher_version=cipher.version,
    )
    assert cred.last_validated_at is None

    before = datetime.now(UTC)
    await repo.touch_validated(cred.id)
    refreshed = await repo.get_active(cred.id, password_user.id)
    assert refreshed.last_validated_at is not None
    assert refreshed.last_validated_at >= before


async def test_ollama_allows_null_key(
    session, password_user: User
):
    repo = UserLLMCredentialRepository(session)
    cred = await repo.create(
        user_id=password_user.id,
        name="local-ollama",
        provider="ollama",
        model="llama3.2",
        encrypted_api_key=None,
        cipher_version=0,
        base_url="http://localhost:11434",
    )
    assert cred.encrypted_api_key is None
    assert cred.base_url == "http://localhost:11434"
