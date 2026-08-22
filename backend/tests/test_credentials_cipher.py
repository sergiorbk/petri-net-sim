"""Tests for the credential encryption layer."""

import os

import pytest
from cryptography.fernet import Fernet

from src.services.crypto import (
    DecryptionError,
    FernetCipher,
    NoOpCipher,
    get_cipher,
    reset_cipher,
)


@pytest.fixture
def fernet_key() -> str:
    return Fernet.generate_key().decode("utf-8")


# --- FernetCipher ---


def test_fernet_round_trip(fernet_key: str):
    cipher = FernetCipher(fernet_key)
    secret = "sk-proj-abc123-some-real-looking-openai-key"

    ciphertext = cipher.encrypt(secret)
    assert isinstance(ciphertext, bytes)
    assert ciphertext != secret.encode("utf-8")

    plaintext = cipher.decrypt(ciphertext)
    assert plaintext == secret


def test_fernet_handles_unicode(fernet_key: str):
    cipher = FernetCipher(fernet_key)
    secret = "sk-キー-😀-with-unicode-数据"
    assert cipher.decrypt(cipher.encrypt(secret)) == secret


def test_fernet_wrong_key_raises_decryption_error(fernet_key: str):
    cipher_a = FernetCipher(fernet_key)
    cipher_b = FernetCipher(Fernet.generate_key().decode("utf-8"))

    ciphertext = cipher_a.encrypt("sk-secret")
    with pytest.raises(DecryptionError):
        cipher_b.decrypt(ciphertext)


def test_fernet_tampered_ciphertext_raises(fernet_key: str):
    cipher = FernetCipher(fernet_key)
    ciphertext = cipher.encrypt("sk-secret")
    # Flip the last byte to simulate tampering
    tampered = bytearray(ciphertext)
    tampered[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        cipher.decrypt(bytes(tampered))


def test_fernet_missing_key_raises():
    with pytest.raises(ValueError, match="32-byte URL-safe base64"):
        FernetCipher("")


def test_fernet_invalid_key_raises():
    with pytest.raises(ValueError, match="Invalid Fernet master key"):
        FernetCipher("definitely-not-a-base64-fernet-key")


def test_fernet_version_is_one(fernet_key: str):
    assert FernetCipher(fernet_key).version == 1


def test_fernet_two_encryptions_differ(fernet_key: str):
    """Fernet uses random IVs — same plaintext encrypted twice yields different bytes."""
    cipher = FernetCipher(fernet_key)
    a = cipher.encrypt("sk-same")
    b = cipher.encrypt("sk-same")
    assert a != b
    assert cipher.decrypt(a) == cipher.decrypt(b) == "sk-same"


# --- NoOpCipher ---


def test_noop_round_trip():
    cipher = NoOpCipher()
    assert cipher.decrypt(cipher.encrypt("sk-plain")) == "sk-plain"


def test_noop_version_is_zero():
    assert NoOpCipher().version == 0


def test_noop_unicode():
    cipher = NoOpCipher()
    assert cipher.decrypt(cipher.encrypt("ключ-🔑")) == "ключ-🔑"


# --- Factory ---


@pytest.fixture(autouse=True)
def _reset_cipher_factory():
    reset_cipher()
    yield
    reset_cipher()


def test_factory_returns_fernet_when_configured(monkeypatch, fernet_key: str):
    monkeypatch.setattr("src.services.crypto.factory.agent_settings.CREDENTIALS_CIPHER", "fernet")
    monkeypatch.setattr(
        "src.services.crypto.factory.agent_settings.CREDENTIALS_MASTER_KEY", fernet_key
    )
    cipher = get_cipher()
    assert isinstance(cipher, FernetCipher)


def test_factory_returns_noop_when_configured(monkeypatch):
    monkeypatch.setattr("src.services.crypto.factory.agent_settings.CREDENTIALS_CIPHER", "noop")
    cipher = get_cipher()
    assert isinstance(cipher, NoOpCipher)


def test_factory_caches_instance(monkeypatch):
    monkeypatch.setattr("src.services.crypto.factory.agent_settings.CREDENTIALS_CIPHER", "noop")
    assert get_cipher() is get_cipher()


def test_factory_fernet_without_key_raises(monkeypatch):
    monkeypatch.setattr("src.services.crypto.factory.agent_settings.CREDENTIALS_CIPHER", "fernet")
    monkeypatch.setattr(
        "src.services.crypto.factory.agent_settings.CREDENTIALS_MASTER_KEY", None
    )
    with pytest.raises(RuntimeError, match="CREDENTIALS_MASTER_KEY"):
        get_cipher()


def test_factory_unknown_kind_raises(monkeypatch):
    monkeypatch.setattr(
        "src.services.crypto.factory.agent_settings.CREDENTIALS_CIPHER", "rot13"
    )
    with pytest.raises(ValueError, match="Unknown CREDENTIALS_CIPHER"):
        get_cipher()
