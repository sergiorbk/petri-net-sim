import logging
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    # Application
    APP_NAME: str = Field(default="Petri Net Sim")
    APP_VERSION: str = Field(default="1.3.0")
    APP_DEBUG: bool = Field(default=False)
    # Deployment environment. Drives production-only hardening: when set to
    # "stage" or "prod", insecure configuration fails startup (see
    # validate_production_settings) and API docs are disabled by default.
    APP_ENV: str = Field(default="local")

    # API documentation exposure. Leave unset (None) to derive from APP_ENV:
    # enabled for local/dev, disabled for stage/prod. Set explicitly to override.
    DOCS_ENABLED: Optional[bool] = Field(default=None)

    # Server
    SERVER_HOST: str = Field(default="0.0.0.0")
    SERVER_PORT: int = Field(default=8000)
    # Public base URL used to build absolute links in chat responses
    # (e.g. PNML download links). Must be reachable from the user's browser
    # (not an internal container hostname). No trailing slash.
    APP_PUBLIC_URL: str = Field(default="http://localhost:6201")

    # Path to a pre-built frontend (frontend/dist) to serve as static files,
    # with an SPA fallback to index.html for client-side routes. Empty
    # (default) means: serve no frontend here. Used only by the all-in-one
    # Docker image (deploy/allinone), which packages frontend + backend +
    # Postgres into one container on one port; the normal multi-container
    # stack has nginx serve the frontend instead (see frontend/nginx.conf).
    FRONTEND_STATIC_DIR: Optional[str] = Field(default=None)

    # CORS
    CORS_ORIGINS: str = Field(default="*")
    CORS_ALLOW_CREDENTIALS: bool = Field(default=True)
    CORS_ALLOW_METHODS: str = Field(default="*")
    CORS_ALLOW_HEADERS: str = Field(default="*")

    # Simulation backend
    # Which engine runs a model. "builtin" (the default) is the Python engine
    # that ships with this service; "remote" hands the run to the external
    # petri-server at SIMULATION_REMOTE_URL. The built-in engine is the primary
    # one, and choosing the other is a deliberate act: a URL sitting in the
    # environment used to be enough on its own to route every run through a
    # service that may not even be deployed.
    SIMULATION_ENGINE: Literal["builtin", "remote"] = Field(default="builtin")
    # Base URL of the external engine (e.g. http://localhost:8080), whose
    # POST /api/v1/simulation/stream endpoint the simulate routes proxy to.
    # Only consulted when SIMULATION_ENGINE is "remote".
    SIMULATION_REMOTE_URL: Optional[str] = Field(default=None)
    # What happens when the external engine is unreachable: True falls back to
    # the built-in engine and says so on the stream, False reports the failure
    # and simulates nothing.
    SIMULATION_REMOTE_FALLBACK: bool = Field(default=True)

    # Auth rate limiting (in-memory, per-process fixed window)
    AUTH_RATE_LIMIT_LOGIN_MAX: int = Field(default=10)
    AUTH_RATE_LIMIT_LOGIN_WINDOW: int = Field(default=60)
    AUTH_RATE_LIMIT_SIGNUP_MAX: int = Field(default=5)
    AUTH_RATE_LIMIT_SIGNUP_WINDOW: int = Field(default=3600)

    # MCP Server
    MCP_ENABLED: bool = Field(default=True)
    MCP_NAME: str = Field(default="Petri Net Sim")
    MCP_HOST: str = Field(default="127.0.0.1")
    MCP_PORT: int = Field(default=8001)
    MCP_SESSION_TTL_SECONDS: int = Field(default=3600)
    MCP_PATH: str = Field(default="/mcp")

    # OpenAI-Compatible API
    OPENAI_ENABLED: bool = Field(default=True)

    # Agent (LangGraph)
    # Recursion limit passed to the compiled graph's ainvoke/astream calls --
    # the "Standard" tier of the chat workbench's per-message effort control
    # (metadata.agent_effort, see openai_api/v1/routers/chat.py's
    # _resolve_recursion_limit). One tool call is 2 graph steps (chat_node,
    # then tool_node), so 100 steps is ~50 tool calls per turn. Raised from
    # LangGraph's own default of 25 (~12 tool calls): the chat workbench's
    # Object net-style mode (chat_node.py's DEFAULT_NET_STYLE) routinely
    # needs create_object + set_active_object + add_*/list_elements per
    # object, times several objects, plus link_objects per connection -- a
    # 3-object composed model with a couple of link retries was hitting 25
    # well before validate_model, aborting the turn outright.
    AGENT_RECURSION_LIMIT: int = Field(default=100)
    # The "Thorough" effort tier -- for a larger composed build (5+ objects,
    # several links, a couple of retries) where Standard's ~50 tool calls
    # would still cut the turn off partway through.
    AGENT_RECURSION_LIMIT_THOROUGH: int = Field(default=250)
    # The ceiling for a turn the user chose NOT to cap (the composer's
    # iteration limit switched off, which is its default). Still a number
    # because LangGraph requires one, but set far above what any real build
    # reaches, so it acts as a runaway backstop rather than a budget: the
    # point of an uncapped turn is that it finishes the net it started,
    # instead of leaving a half-built model behind at step 100.
    AGENT_RECURSION_LIMIT_UNCAPPED: int = Field(default=1000)

    # Logging
    LOGGING_LEVEL: str = Field(default="INFO")
    LOGGING_FILE: Optional[str] = Field(default=None)
    LOGGING_FORMAT: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    LOGGING_DATE_FORMAT: str = Field(default="%Y-%m-%d %H:%M:%S")

    @property
    def LOG_LEVEL(self) -> str:
        return self.LOGGING_LEVEL

    @property
    def LOG_FILE(self) -> Optional[Path]:
        if self.LOGGING_FILE:
            return Path(self.LOGGING_FILE)
        return None

    @property
    def DEBUG(self) -> bool:
        return self.APP_DEBUG

    @property
    def is_production(self) -> bool:
        """True when running in a deployed (stage/prod) environment."""
        return self.APP_ENV.strip().lower() in {"stage", "staging", "prod", "production"}

    @property
    def docs_enabled(self) -> bool:
        """Whether to expose /docs, /redoc and /openapi.json.

        Defaults to disabled in deployed environments unless explicitly turned
        on via DOCS_ENABLED.
        """
        if self.DOCS_ENABLED is not None:
            return self.DOCS_ENABLED
        return not self.is_production

    @property
    def simulation_remote_target(self) -> Optional[str]:
        """Base URL of the external engine, or None to run on the built-in one.

        The one place the engine choice is made. Routes ask this and take the
        built-in path when it answers None; reading SIMULATION_REMOTE_URL
        directly is what let three copies of the same decision drift apart.
        """
        if self.SIMULATION_ENGINE != "remote":
            return None
        return (self.SIMULATION_REMOTE_URL or "").strip() or None

    @model_validator(mode="after")
    def _validate_simulation_engine(self) -> "Settings":
        if self.SIMULATION_ENGINE == "remote" and not (
            self.SIMULATION_REMOTE_URL or ""
        ).strip():
            raise ValueError(
                "SIMULATION_ENGINE=remote requires SIMULATION_REMOTE_URL to point "
                "at the external engine. Unset SIMULATION_ENGINE to run on the "
                "built-in one."
            )
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def cors_methods_list(self) -> list[str]:
        if self.CORS_ALLOW_METHODS == "*":
            return ["*"]
        return [m.strip() for m in self.CORS_ALLOW_METHODS.split(",") if m.strip()]

    @property
    def cors_headers_list(self) -> list[str]:
        if self.CORS_ALLOW_HEADERS == "*":
            return ["*"]
        return [h.strip() for h in self.CORS_ALLOW_HEADERS.split(",") if h.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()


# Known insecure placeholder JWT secrets shipped in defaults/examples.
_INSECURE_JWT_SECRETS = frozenset(
    {
        "change-me-in-production-use-strong-secret",
        "change-me-to-a-long-random-string-at-least-32-chars",
    }
)


class ProductionConfigError(RuntimeError):
    """Raised at startup when deployed configuration is unsafe."""


def validate_production_settings() -> None:
    """Fail fast on insecure configuration in deployed environments.

    Called early in the application lifespan. In local/dev this is a no-op
    aside from informational logging. In stage/prod it raises
    ``ProductionConfigError`` (aborting startup) for any hard security issue —
    refusing to boot insecurely is safer than silently running exposed.
    """
    from src.core.agent_config import agent_settings
    from src.core.auth_config import auth_settings

    errors: list[str] = []
    warnings: list[str] = []

    if not settings.is_production:
        _logger.info(
            "Config check: APP_ENV=%s (development mode — production "
            "validation is advisory only)",
            settings.APP_ENV,
        )

    # --- JWT secret strength ---
    secret = auth_settings.AUTH_JWT_SECRET_KEY or ""
    if secret in _INSECURE_JWT_SECRETS:
        errors.append(
            "AUTH_JWT_SECRET_KEY is set to a known placeholder value — "
            "generate a strong random secret."
        )
    elif len(secret) < 32:
        errors.append(
            f"AUTH_JWT_SECRET_KEY is too short ({len(secret)} chars); "
            "use at least 32 characters of entropy."
        )

    # --- Credentials cipher ---
    if agent_settings.CREDENTIALS_CIPHER == "noop":
        errors.append(
            "CREDENTIALS_CIPHER=noop stores BYOK keys in plaintext — "
            "use 'fernet' in production."
        )
    if agent_settings.CREDENTIALS_CIPHER == "fernet" and not (
        agent_settings.CREDENTIALS_MASTER_KEY or ""
    ).strip():
        errors.append(
            "CREDENTIALS_CIPHER=fernet requires CREDENTIALS_MASTER_KEY to be set."
        )

    # --- Debug mode ---
    if settings.APP_DEBUG:
        errors.append("APP_DEBUG=true must not be enabled in production.")

    # --- CORS ---
    wildcard_cors = "*" in settings.cors_origins_list
    if wildcard_cors and settings.CORS_ALLOW_CREDENTIALS:
        errors.append(
            "CORS wildcard origin '*' with CORS_ALLOW_CREDENTIALS=true is "
            "invalid and unsafe — pin explicit origins or disable credentials."
        )
    elif wildcard_cors:
        warnings.append(
            "CORS origin is wildcard '*'; consider pinning explicit origins."
        )

    # --- Docs exposure (soft) ---
    if settings.docs_enabled:
        warnings.append(
            "API docs (/docs, /redoc, /openapi.json) are exposed; set "
            "DOCS_ENABLED=false to hide them in production."
        )

    # --- Single-user (no-login) mode in a deployed environment ---
    # Not an error: a private, single-operator deployment is a legitimate
    # reason to run without accounts. But it's a choice with sharp edges if
    # made by accident, so it gets its own prominent banner rather than
    # blending into the one-line-per-issue warnings loop below.
    if settings.is_production and auth_settings.AUTH_MODE == "single_user":
        _logger.warning(
            "\n" + "!" * 70 + "\n"
            "AUTH_MODE=single_user with APP_ENV=%s: this server has NO LOGIN.\n"
            "Every request that doesn't carry its own credentials is treated\n"
            "as the local user -- anyone who can reach this server has full\n"
            "access, with no username or password. This is fine for a private,\n"
            "single-operator deployment; it is NOT fine if this server is\n"
            "reachable from the open internet without another layer (firewall,\n"
            "VPN, reverse-proxy auth) restricting who can reach it.\n"
            + "!" * 70,
            settings.APP_ENV,
        )

    for w in warnings:
        _logger.warning("Production config warning: %s", w)

    if errors:
        for e in errors:
            _logger.error("Production config error: %s", e)
        if settings.is_production:
            raise ProductionConfigError(
                f"{len(errors)} insecure setting(s) detected for APP_ENV="
                f"{settings.APP_ENV}: " + "; ".join(errors)
            )
        _logger.warning(
            "%d insecure setting(s) detected — tolerated because APP_ENV=%s "
            "is not a deployed environment. These WILL abort startup in stage/prod.",
            len(errors),
            settings.APP_ENV,
        )
    else:
        _logger.info("Production config validation passed (no security issues).")
