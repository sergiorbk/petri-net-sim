"""Pass-through cipher for tests and dev-only environments."""

from src.services.crypto.cipher import CredentialsCipher


class NoOpCipher(CredentialsCipher):
    """
    Stores plaintext UTF-8 bytes verbatim. NEVER use in stage or production —
    the API key is stored unencrypted at rest. Provided so tests can run
    without a master key and so a developer can opt-out for local debugging.
    """

    _VERSION = 0

    @property
    def version(self) -> int:
        return self._VERSION

    def encrypt(self, plaintext: str) -> bytes:
        return plaintext.encode("utf-8")

    def decrypt(self, ciphertext: bytes) -> str:
        return ciphertext.decode("utf-8")
