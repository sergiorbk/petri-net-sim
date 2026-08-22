"""JWT token service for authentication."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from src.core.auth_config import auth_settings
from src.core.logger import get_logger

logger = get_logger()


class JWTService:
    """Service for JWT token generation and validation."""

    def __init__(
        self,
        secret_key: str | None = None,
        algorithm: str | None = None,
        access_token_expire_minutes: int | None = None,
        refresh_token_expire_days: int | None = None,
    ):
        self._secret_key = secret_key or auth_settings.AUTH_JWT_SECRET_KEY
        self._algorithm = algorithm or auth_settings.AUTH_JWT_ALGORITHM
        self._access_token_expire_minutes = (
            access_token_expire_minutes or auth_settings.AUTH_JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
        self._refresh_token_expire_days = (
            refresh_token_expire_days or auth_settings.AUTH_JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )

    def create_access_token(
        self,
        user_id: UUID,
        email: str,
        additional_claims: dict[str, Any] | None = None,
    ) -> str:
        """
        Create access token.

        Args:
            user_id: User UUID
            email: User email
            additional_claims: Optional additional JWT claims

        Returns:
            Encoded JWT access token
        """
        expire = datetime.now(UTC) + timedelta(minutes=self._access_token_expire_minutes)

        payload = {
            "sub": str(user_id),
            "email": email,
            "type": "access",
            "exp": expire,
            "iat": datetime.now(UTC),
        }

        if additional_claims:
            payload.update(additional_claims)

        token = jwt.encode(payload, self._secret_key, algorithm=self._algorithm)
        logger.debug(f"Created access token for user {user_id}")
        return token

    def create_refresh_token(self, user_id: UUID) -> str:
        """
        Create refresh token.

        Args:
            user_id: User UUID

        Returns:
            Encoded JWT refresh token
        """
        expire = datetime.now(UTC) + timedelta(days=self._refresh_token_expire_days)

        payload = {
            "sub": str(user_id),
            "type": "refresh",
            "exp": expire,
            "iat": datetime.now(UTC),
        }

        token = jwt.encode(payload, self._secret_key, algorithm=self._algorithm)
        logger.debug(f"Created refresh token for user {user_id}")
        return token

    def create_token_pair(
        self,
        user_id: UUID,
        email: str,
        additional_claims: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """
        Create both access and refresh tokens.

        Args:
            user_id: User UUID
            email: User email
            additional_claims: Optional additional JWT claims

        Returns:
            Tuple of (access_token, refresh_token)
        """
        access_token = self.create_access_token(user_id, email, additional_claims)
        refresh_token = self.create_refresh_token(user_id)
        return access_token, refresh_token

    def verify_token(self, token: str) -> dict[str, Any] | None:
        """
        Verify and decode a JWT token.

        Args:
            token: JWT token to verify

        Returns:
            Decoded payload or None if invalid
        """
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
            return payload
        except JWTError as e:
            logger.debug(f"Token verification failed: {e}")
            return None

    def verify_access_token(self, token: str) -> dict[str, Any] | None:
        """
        Verify an access token.

        Args:
            token: JWT access token

        Returns:
            Decoded payload or None if invalid
        """
        payload = self.verify_token(token)
        if payload and payload.get("type") == "access":
            return payload
        return None

    def verify_refresh_token(self, token: str) -> dict[str, Any] | None:
        """
        Verify a refresh token.

        Args:
            token: JWT refresh token

        Returns:
            Decoded payload or None if invalid
        """
        payload = self.verify_token(token)
        if payload and payload.get("type") == "refresh":
            return payload
        return None

    def create_download_token(
        self,
        file_id: UUID,
        user_id: UUID,
        ttl_hours: int = 24,
    ) -> str:
        """Create a short-lived, single-purpose token for file downloads."""
        expire = datetime.now(UTC) + timedelta(hours=ttl_hours)
        payload = {
            "sub": str(user_id),
            "fid": str(file_id),
            "type": "download",
            "exp": expire,
            "iat": datetime.now(UTC),
        }
        return jwt.encode(payload, self._secret_key, algorithm=self._algorithm)

    def verify_download_token(self, token: str) -> tuple[UUID, UUID] | None:
        """Verify a download token. Returns (file_id, user_id) or None."""
        payload = self.verify_token(token)
        if not payload or payload.get("type") != "download":
            return None
        try:
            return UUID(payload["fid"]), UUID(payload["sub"])
        except (KeyError, ValueError):
            return None

    def get_user_id_from_token(self, token: str) -> UUID | None:
        """
        Extract user ID from token.

        Args:
            token: JWT token

        Returns:
            User UUID or None if invalid
        """
        payload = self.verify_token(token)
        if payload and "sub" in payload:
            try:
                return UUID(payload["sub"])
            except ValueError:
                return None
        return None


# Global JWT service instance
_jwt_service: JWTService | None = None


def get_jwt_service() -> JWTService:
    """Get or create the global JWT service instance."""
    global _jwt_service
    if _jwt_service is None:
        _jwt_service = JWTService()
    return _jwt_service
