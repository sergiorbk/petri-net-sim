"""Factory selecting the active CredentialsCipher implementation."""

from src.core.agent_config import agent_settings
from src.core.logger import get_logger
from src.services.crypto.cipher import CredentialsCipher
from src.services.crypto.fernet_cipher import FernetCipher
from src.services.crypto.noop_cipher import NoOpCipher

logger = get_logger()

_cipher: CredentialsCipher | None = None


def get_cipher() -> CredentialsCipher:
    """
    Return the configured cipher instance, building it on first access.

    Selection is driven by ``CREDENTIALS_CIPHER``:
      - ``fernet`` (default): requires ``CREDENTIALS_MASTER_KEY`` to be set.
      - ``noop``: passthrough, dev/test only.

    The cipher is cached process-wide because Fernet construction validates and
    decodes the master key once; reuse is cheap and the key never rotates inside
    a single process lifetime.
    """
    global _cipher
    if _cipher is not None:
        return _cipher

    kind = agent_settings.CREDENTIALS_CIPHER
    if kind == "noop":
        logger.warning(
            "CREDENTIALS_CIPHER=noop — credentials will be stored UNENCRYPTED. "
            "This must NEVER be used outside local development."
        )
        _cipher = NoOpCipher()
    elif kind == "fernet":
        if not agent_settings.CREDENTIALS_MASTER_KEY:
            raise RuntimeError(
                "CREDENTIALS_CIPHER=fernet requires CREDENTIALS_MASTER_KEY to be set. "
                "Generate one with: "
                "python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )
        _cipher = FernetCipher(agent_settings.CREDENTIALS_MASTER_KEY)
    else:
        raise ValueError(f"Unknown CREDENTIALS_CIPHER: {kind!r}")

    return _cipher


def reset_cipher() -> None:
    """Drop the cached cipher. Used by tests that swap configuration mid-run."""
    global _cipher
    _cipher = None
