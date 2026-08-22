"""Fernet-backed implementation of CredentialsCipher.

Fernet (cryptography library) provides AES-128-CBC + HMAC-SHA256 with a
versioned token format and built-in authentication, so tampering or wrong-key
attempts raise instead of silently returning garbage.
"""

from cryptography.fernet import Fernet, InvalidToken

from src.services.crypto.cipher import CredentialsCipher, DecryptionError


class FernetCipher(CredentialsCipher):
    """Symmetric AEAD cipher backed by Fernet."""

    _VERSION = 1

    def __init__(self, master_key: str | bytes):
        if not master_key:
            raise ValueError(
                "FernetCipher requires a 32-byte URL-safe base64 master key. "
                "Generate one with: "
                "python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )

        key_bytes = master_key.encode("utf-8") if isinstance(master_key, str) else master_key
        try:
            self._fernet = Fernet(key_bytes)
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Invalid Fernet master key: {e}. "
                "Expected a 32-byte URL-safe base64-encoded value."
            ) from e

    @property
    def version(self) -> int:
        return self._VERSION

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as e:
            raise DecryptionError(
                "Failed to decrypt credential — token invalid, tampered, "
                "or encrypted with a different master key."
            ) from e
