"""Authentication service."""

from uuid import UUID

import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories import UserRepository
from src.services.auth.jwt_service import get_jwt_service

logger = get_logger()


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


class AuthService:
    """Service for authentication flows."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._user_repo = UserRepository(session)
        self._jwt_service = get_jwt_service()

    async def register_with_password(
        self, email: str, password: str, name: str | None = None
    ) -> tuple[User, str, str]:
        """Create a new user with email + password. Returns (user, access, refresh).

        Raises ValueError if email is already registered.
        """
        existing = await self._user_repo.get_by_email(email)
        if existing:
            raise ValueError("Email already registered")

        user = await self._user_repo.create(
            email=email,
            name=name,
            password_hash=hash_password(password),
        )
        await self._session.commit()

        access_token, refresh_token = self._jwt_service.create_token_pair(
            user_id=user.id,
            email=user.email,
        )
        logger.info("User registered: %s", user.email)
        return user, access_token, refresh_token

    async def authenticate_credentials(
        self, email: str, password: str
    ) -> tuple[User, str, str] | None:
        """Authenticate a user with email and password.

        Returns (user, access_token, refresh_token) or None if invalid.
        """
        user = await self._user_repo.get_by_email(email)
        if not user or not user.is_active or not user.password_hash:
            return None

        if not verify_password(password, user.password_hash):
            return None

        access_token, refresh_token = self._jwt_service.create_token_pair(
            user_id=user.id,
            email=user.email,
        )

        logger.info("User authenticated: %s", user.email)
        return user, access_token, refresh_token

    async def get_current_user(self, access_token: str) -> User | None:
        """Get current user from access token."""
        payload = self._jwt_service.verify_access_token(access_token)
        if not payload:
            return None

        try:
            user_id = UUID(payload["sub"])
        except (KeyError, ValueError):
            return None

        user = await self._user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            return None

        return user

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID."""
        return await self._user_repo.get_by_id(user_id)
