"""Abstract symmetric cipher interface for credential storage at rest."""

from abc import ABC, abstractmethod


class DecryptionError(Exception):
    """Raised when ciphertext cannot be decrypted (wrong key, corrupted, tampered)."""


class CredentialsCipher(ABC):
    """
    Symmetric cipher that encrypts and decrypts secret strings.

    Implementations are expected to authenticate ciphertext (AEAD-style) so that
    tampering or wrong-key decryption raises DecryptionError instead of returning
    silently corrupt plaintext.

    The ``version`` field is stored on the row alongside the ciphertext so that
    future master-key rotations or algorithm migrations can decrypt existing
    rows with the previous cipher and re-encrypt them with the new one.
    """

    @property
    @abstractmethod
    def version(self) -> int:
        """Cipher version. Stored on each encrypted record for rotation."""

    @abstractmethod
    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt a UTF-8 string into authenticated ciphertext bytes."""

    @abstractmethod
    def decrypt(self, ciphertext: bytes) -> str:
        """Decrypt authenticated ciphertext, raising DecryptionError on failure."""
