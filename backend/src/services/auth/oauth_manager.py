"""OAuth authentication manager -- provider-agnostic user resolution."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories import UserRepository
from src.services.auth.jwt_service import get_jwt_service
from src.services.auth.oauth_service import OAuthUserInfo

logger = get_logger()


class OAuthManager:
    """Resolves OAuth user info into application users and JWT tokens."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._user_repo = UserRepository(session)
        self._jwt_service = get_jwt_service()

    async def authenticate(
        self, user_info: OAuthUserInfo
    ) -> tuple[User, str, str]:
        """Find or create a user from OAuth info and issue a JWT pair.

        Returns:
            Tuple of (user, access_token, refresh_token).
        """
        user = await self._user_repo.get_by_email(user_info.email)

        if user:
            if not user.is_active:
                raise PermissionError("User account is deactivated")

            # Update profile fields from provider
            await self._user_repo.update(
                user,
                name=user_info.name or user.name,
                picture=user_info.picture or user.picture,
            )

            # Backfill provider info if missing
            if not user.auth_provider:
                user.auth_provider = user_info.provider
                user.auth_provider_id = user_info.provider_id

            logger.info("OAuth login: existing user %s via %s", user.email, user_info.provider)
        else:
            user = await self._user_repo.create(
                email=user_info.email,
                name=user_info.name,
                picture=user_info.picture,
            )
            user.auth_provider = user_info.provider
            user.auth_provider_id = user_info.provider_id

            logger.info("OAuth login: created user %s via %s", user.email, user_info.provider)

        await self._session.commit()

        access_token, refresh_token = self._jwt_service.create_token_pair(
            user_id=user.id,
            email=user.email,
        )

        return user, access_token, refresh_token
