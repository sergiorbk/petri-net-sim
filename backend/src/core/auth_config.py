"""Authentication configuration settings."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    """Authentication and JWT configuration."""

    # Authentication mode. "multi" (default) is the normal accounts-required
    # mode: every protected endpoint needs a JWT or API key, and signup/login
    # work as usual. "single_user" removes login entirely -- every request
    # that doesn't carry its own valid credentials is treated as one fixed
    # local account (see src/services/auth/local_user.py), and the
    # signup/login/oauth endpoints are disabled. Intended for a personal,
    # locally-run instance; see validate_production_settings for the startup
    # warning this triggers when combined with APP_ENV=prod/stage.
    AUTH_MODE: Literal["multi", "single_user"] = Field(default="multi")

    # JWT
    AUTH_JWT_SECRET_KEY: str = Field(default="change-me-in-production-use-strong-secret")
    AUTH_JWT_ALGORITHM: str = Field(default="HS256")
    AUTH_JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=1440)
    AUTH_JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)

    # API-key auth hot-path tuning. last_used_at is informational (shown in the
    # key-management UI), not security-critical, so we skip the per-request
    # UPDATE+commit and only write when the stored value is older than this many
    # seconds. Removes write contention on the /chat hot path under load.
    API_KEY_LAST_USED_THROTTLE_SECONDS: int = Field(default=300)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


auth_settings = AuthSettings()
