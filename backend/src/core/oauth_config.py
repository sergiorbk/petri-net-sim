"""OAuth provider configuration settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OAuthSettings(BaseSettings):
    """OAuth provider configuration."""

    # Google
    OAUTH_GOOGLE_CLIENT_ID: str = Field(default="")
    OAUTH_GOOGLE_CLIENT_SECRET: str = Field(default="")
    OAUTH_GOOGLE_REDIRECT_URI: str = Field(
        default="http://localhost:6201/api/v1/auth/oauth/google/callback"
    )

    # Frontend callback URL (backend redirects here with tokens in fragment)
    OAUTH_FRONTEND_CALLBACK_URL: str = Field(
        default="http://localhost:6203/auth/callback"
    )

    @property
    def google_enabled(self) -> bool:
        return bool(self.OAUTH_GOOGLE_CLIENT_ID and self.OAUTH_GOOGLE_CLIENT_SECRET)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


oauth_settings = OAuthSettings()
