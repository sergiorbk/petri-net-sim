"""Authentication API schemas."""

from datetime import datetime
from uuid import UUID

from email_validator import EmailNotValidError
from email_validator import validate_email as _validate_email_address
from pydantic import BaseModel, EmailStr, Field, field_validator

from src.services.auth.integrations import HTTP_API, MCP, integration_enabled
from src.services.auth.local_user import LOCAL_USER_EMAIL


# --- User Schemas ---


class UserResponse(BaseModel):
    """User info response."""

    id: UUID = Field(description="User UUID")
    # Plain str, not EmailStr: this is an output field read back from a row
    # that was already validated (or exempted -- see SignupRequest._validate_email)
    # on the way in. AUTH_MODE=single_user's fixed local user lives at
    # LOCAL_USER_EMAIL, on the .local special-use TLD, which email_validator
    # rejects even with check_deliverability=False -- EmailStr here made
    # GET/PATCH /me 500 for every single-user-mode request, unconditionally.
    email: str = Field(description="User email")
    name: str | None = Field(description="User full name")
    picture: str | None = Field(default=None, description="User avatar URL")
    is_active: bool = Field(description="Whether user is active")
    created_at: datetime = Field(description="Account creation timestamp")
    display_name: str | None = Field(default=None, description="Preferred name the assistant uses")
    work_type: str | None = Field(default=None, description="User's occupation category")
    custom_instructions: str | None = Field(default=None, description="Custom instructions for the assistant")
    mcp_enabled: bool = Field(default=True, description="Whether API keys may reach the MCP server")
    http_api_enabled: bool = Field(default=True, description="Whether API keys may reach the OpenAI-compatible HTTP API")

    model_config = {"from_attributes": True}

    @classmethod
    def from_user(cls, user: object) -> "UserResponse":
        """Build response from ORM User, extracting metadata fields."""
        meta: dict = getattr(user, "metadata_", None) or {}
        return cls(
            id=getattr(user, "id"),
            email=getattr(user, "email"),
            name=getattr(user, "name"),
            picture=getattr(user, "picture"),
            is_active=getattr(user, "is_active"),
            created_at=getattr(user, "created_at"),
            display_name=meta.get("display_name"),
            work_type=meta.get("work_type"),
            custom_instructions=meta.get("custom_instructions"),
            mcp_enabled=integration_enabled(user, MCP),
            http_api_enabled=integration_enabled(user, HTTP_API),
        )


class UpdateProfileRequest(BaseModel):
    """Request to update the authenticated user's profile."""

    name: str | None = Field(default=None, max_length=255, description="Full name")
    display_name: str | None = Field(default=None, max_length=100, description="Preferred name for the assistant")
    work_type: str | None = Field(default=None, max_length=100, description="Occupation category")
    custom_instructions: str | None = Field(default=None, max_length=4000, description="Custom instructions for the assistant")
    mcp_enabled: bool | None = Field(default=None, description="Allow API keys to reach the MCP server")
    http_api_enabled: bool | None = Field(default=None, description="Allow API keys to reach the OpenAI-compatible HTTP API")


class SignupRequest(BaseModel):
    """Request to register a new account via email + password."""

    email: str = Field(description="Email address")
    password: str = Field(min_length=8, max_length=128, description="Password")
    name: str | None = Field(default=None, max_length=255, description="Display name")

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        """Email format validation, matching pydantic's EmailStr exactly --
        with one deliberate carve-out for LOCAL_USER_EMAIL.

        That address (services/auth/local_user.py) sits on the .local
        special-use TLD, which the underlying email_validator library
        hard-rejects on its own, regardless of AUTH_MODE. Left alone, that
        rejection would incidentally do the job of blocking signup at that
        address -- but silently, and only for as long as the address
        happens to live on a reserved TLD. The signup endpoint
        (routers/auth.py) carries its own explicit, documented check for
        this exact address; this validator's only job is to let that
        specific string reach it unmodified instead of being swallowed
        here as a generic "invalid email" 422. Every other address is
        validated exactly as strictly as EmailStr validates it today.
        """
        if value.strip().lower() == LOCAL_USER_EMAIL.lower():
            return value
        try:
            result = _validate_email_address(value, check_deliverability=False)
        except EmailNotValidError as e:
            raise ValueError(str(e)) from e
        return result.normalized


class LoginRequest(BaseModel):
    """Request to log in via email + password."""

    email: EmailStr = Field(description="Email address")
    password: str = Field(description="Password")


class OAuthAuthorizeResponse(BaseModel):
    """OAuth authorization URL response."""

    url: str = Field(description="OAuth authorization URL to redirect user to")


class RefreshTokenRequest(BaseModel):
    """Request to refresh an access token."""

    refresh_token: str = Field(description="JWT refresh token")


class TokenPairResponse(BaseModel):
    """Token pair response."""

    access_token: str = Field(description="JWT access token")
    refresh_token: str = Field(description="JWT refresh token")
    token_type: str = Field(default="bearer")
    expires_in: int = Field(description="Access token lifetime in seconds")


# --- API Key Schemas ---


class ApiKeyCreateRequest(BaseModel):
    """Request to create a new API key."""

    name: str | None = Field(default=None, max_length=255, description="Optional label for the key")
    llm_credential_id: UUID | None = Field(
        default=None,
        description=(
            "Bind this key to a specific LLM credential profile. "
            "Requests authenticated with this key will use that credential automatically, "
            "without needing metadata.llm_credential_id. "
            "Omit to create an unbound key (shared key or metadata-driven BYOK)."
        ),
    )


class ApiKeyCreateResponse(BaseModel):
    """Response after creating an API key. The raw key is shown only once."""

    id: UUID = Field(description="API key ID")
    key: str = Field(description="Raw API key — save it now, it will not be shown again")
    name: str | None = Field(description="Key label")
    llm_credential_id: UUID | None = Field(
        default=None,
        description="Bound LLM credential profile ID, or null if unbound",
    )


class ApiKeyListItem(BaseModel):
    """API key metadata (no secrets exposed)."""

    id: UUID = Field(description="API key ID")
    name: str | None = Field(description="Key label")
    prefix: str = Field(description="Key prefix for identification (e.g. sk-abc1...)")
    is_active: bool = Field(description="Whether the key is active")
    last_used_at: datetime | None = Field(description="Last time the key was used")
    created_at: datetime = Field(description="Key creation timestamp")
    llm_credential_id: UUID | None = Field(
        default=None,
        description="Bound LLM credential profile ID, or null if unbound",
    )
    llm_credential_name: str | None = Field(
        default=None,
        description="Bound LLM credential profile name, or null if unbound",
    )
