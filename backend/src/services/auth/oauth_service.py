"""OAuth provider abstraction and Google implementation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from src.core.logger import get_logger
from src.core.oauth_config import oauth_settings

logger = get_logger()


@dataclass(frozen=True)
class OAuthUserInfo:
    """Normalized user information returned by an OAuth provider."""

    provider: str
    provider_id: str
    email: str
    name: str | None
    picture: str | None


class OAuthProvider(ABC):
    """Base class for OAuth 2.0 providers."""

    @abstractmethod
    def get_authorization_url(self, state: str) -> str:
        """Build the provider's authorization URL."""

    @abstractmethod
    async def exchange_code(self, code: str) -> OAuthUserInfo:
        """Exchange an authorization code for user information."""


class GoogleOAuthProvider(OAuthProvider):
    """Google OAuth 2.0 provider."""

    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
    ):
        self._client_id = client_id or oauth_settings.OAUTH_GOOGLE_CLIENT_ID
        self._client_secret = client_secret or oauth_settings.OAUTH_GOOGLE_CLIENT_SECRET
        self._redirect_uri = redirect_uri or oauth_settings.OAUTH_GOOGLE_REDIRECT_URI

    def get_authorization_url(self, state: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthUserInfo:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Exchange code for tokens
            token_response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self._redirect_uri,
                },
            )
            token_response.raise_for_status()
            tokens = token_response.json()
            access_token = tokens["access_token"]

            # Fetch user info
            userinfo_response = await client.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_response.raise_for_status()
            userinfo = userinfo_response.json()

        logger.info("Google OAuth: fetched user info for %s", userinfo.get("email"))

        return OAuthUserInfo(
            provider="google",
            provider_id=userinfo["sub"],
            email=userinfo["email"],
            name=userinfo.get("name"),
            picture=userinfo.get("picture"),
        )
