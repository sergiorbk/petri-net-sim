"""Security and abuse-protection configuration.

Groups every defense-in-depth knob in one place (mirrors the
``database_config`` pattern). All limits default to
generous, non-breaking values so enabling this module never changes behavior
for legitimate traffic; only abusive traffic hits the ceilings.

Deployment assumption: the app is exposed directly via uvicorn/Docker (no
trusted reverse proxy), therefore ``X-Forwarded-For`` is **not** trusted by
default and every defense lives at the application layer.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecuritySettings(BaseSettings):
    """Application-layer hardening settings."""

    # --- Request body size limits (bytes) ---
    # Normal endpoints rarely need more than a few KB. The "large" cap applies
    # to endpoints that legitimately accept full Petri-net JSON payloads
    # (/simulate, /chat completions with long histories).
    SECURITY_MAX_BODY_BYTES: int = Field(default=262_144, ge=1024)  # 256 KB
    SECURITY_MAX_BODY_BYTES_LARGE: int = Field(default=2_097_152, ge=1024)  # 2 MB
    # Path prefixes that get the large body cap. /api/v1/pnml carries the
    # POST /pnml/parse endpoint, which -- like /simulate -- legitimately
    # accepts a full net's worth of content, just as PNML/XML rather than
    # net_data JSON (typically the more verbose of the two for the same
    # model, given its graphics/toolspecific blocks).
    SECURITY_LARGE_BODY_PATH_PREFIXES: str = Field(
        default="/api/v1/chat/completions,/api/v1/simulate,/api/v1/pnml"
    )

    # --- Global concurrency limit ---
    # Caps total in-flight requests so a flood cannot exhaust the DB pool or
    # spawn unbounded coroutines. 0 disables the limiter.
    SECURITY_MAX_CONCURRENT_REQUESTS: int = Field(default=200, ge=0)

    # --- Request timeout (non-streaming) ---
    # Hard wall-clock ceiling for normal requests. Streaming endpoints (SSE,
    # MCP) are excluded and rely on their own caps.
    SECURITY_REQUEST_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0)
    SECURITY_STREAMING_PATH_PREFIXES: str = Field(
        default="/api/v1/chat/completions,/api/v1/simulate,/mcp"
    )

    # --- Trusted proxy / client IP resolution ---
    # When False (default for direct uvicorn deploy), X-Forwarded-For is ignored
    # and the real TCP peer is used — prevents rate-limit bypass via header spoofing.
    SECURITY_TRUST_PROXY_HEADERS: bool = Field(default=False)
    # Number of trusted proxy hops; the client IP is taken this many entries
    # from the right of the X-Forwarded-For chain.
    SECURITY_TRUSTED_PROXY_HOPS: int = Field(default=1, ge=1)

    # --- Security response headers ---
    SECURITY_HSTS_ENABLED: bool = Field(default=False)  # enable only behind TLS
    SECURITY_HSTS_MAX_AGE: int = Field(default=31_536_000, ge=0)  # 1 year
    SECURITY_HSTS_INCLUDE_SUBDOMAINS: bool = Field(default=True)
    # frontend/index.html carries one static inline <script> (the pre-paint
    # dark-mode class toggle, so there's no flash of the wrong theme before
    # React mounts) -- with no explicit script-src, default-src 'self' falls
    # back to blocking ALL inline script execution, hash or not, so the
    # browser was silently dropping it on every page load. The hash below is
    # sha256 over that script's exact text content (see index.html); it only
    # ever needs to change if that script's source changes.
    # style-src has to allow inline, and cannot do it with hashes: React Flow
    # positions and sizes every node by writing a `style` attribute at
    # runtime, and Mermaid injects generated stylesheets for each diagram it
    # draws. Neither is a fixed string anything could be hashed against. With
    # no style-src at all these fell back to default-src 'self', so the
    # browser silently dropped them and logged a CSP violation per node --
    # the editor canvas and every rendered diagram lost their layout.
    #
    # Deliberately NOT extended to script-src, which is where the risk
    # actually is and which stays 'self' plus the one hash below. Inline CSS
    # cannot execute; the worst it buys an attacker who already has markup
    # injection is selector-based exfiltration, and this app renders foreign
    # text only through its sanitizing markdown path.
    #
    # img-src adds data: and blob: for the same class of reason. Exporting a
    # chart as PNG means serializing the rendered SVG, loading it into an
    # <img> and drawing that onto a canvas -- entirely in the browser, no
    # server round trip. Both the data: URL that image is loaded from and the
    # blob: URL the finished PNG is downloaded through fell back to
    # default-src 'self', so the load failed silently and the export produced
    # nothing at all. An image source cannot execute; script-src, where that
    # would matter, still names neither scheme.
    SECURITY_CSP: str = Field(
        default=(
            "default-src 'self'; "
            "script-src 'self' 'sha256-KAp8487tircwOoLnty6kcLgundcozb9ZR7Qzi5IgLRk='; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:"
        )
    )
    SECURITY_FRAME_DENY: bool = Field(default=True)
    SECURITY_REFERRER_POLICY: str = Field(default="no-referrer")
    SECURITY_PERMISSIONS_POLICY: str = Field(
        default="geolocation=(), microphone=(), camera=()"
    )

    # --- Rate limiting ---
    # Fail-open: if the in-memory limiter raises unexpectedly, allow the request
    # (availability over strictness). Set False to fail-closed (reject instead).
    SECURITY_RATE_LIMIT_FAIL_OPEN: bool = Field(default=True)

    # Per-user / per-IP request ceilings (max requests per window seconds).
    RATE_LIMIT_CHAT_MAX: int = Field(default=30, ge=1)
    RATE_LIMIT_CHAT_WINDOW: int = Field(default=60, ge=1)
    RATE_LIMIT_SIMULATE_MAX: int = Field(default=20, ge=1)
    RATE_LIMIT_SIMULATE_WINDOW: int = Field(default=60, ge=1)
    RATE_LIMIT_CREDENTIALS_MAX: int = Field(default=20, ge=1)
    RATE_LIMIT_CREDENTIALS_WINDOW: int = Field(default=60, ge=1)
    RATE_LIMIT_REFRESH_MAX: int = Field(default=30, ge=1)
    RATE_LIMIT_REFRESH_WINDOW: int = Field(default=60, ge=1)
    RATE_LIMIT_OAUTH_MAX: int = Field(default=30, ge=1)
    RATE_LIMIT_OAUTH_WINDOW: int = Field(default=60, ge=1)
    RATE_LIMIT_API_KEYS_MAX: int = Field(default=20, ge=1)
    RATE_LIMIT_API_KEYS_WINDOW: int = Field(default=3600, ge=1)

    # --- Simulation caps (CPU / memory bomb protection) ---
    SIMULATION_MAX_TIME: float = Field(default=1_000_000.0, gt=0)
    SIMULATION_MAX_STEPS: int = Field(default=2_000_000, ge=1)
    # Same idea one level down: it stops a run that will never end, and a
    # big net legitimately takes minutes.
    SIMULATION_WALL_CLOCK_TIMEOUT_SECONDS: float = Field(default=300.0, ge=1.0)
    SIMULATION_MAX_PLACES: int = Field(default=5_000, ge=1)
    SIMULATION_MAX_TRANSITIONS: int = Field(default=5_000, ge=1)
    SIMULATION_MAX_ARCS: int = Field(default=20_000, ge=1)
    SIMULATION_MAX_SNAPSHOTS: int = Field(default=50_000, ge=1)
    SIMULATION_MAX_OBJECTS: int = Field(default=20, ge=1)

    # --- Input validation bounds (chat) ---
    CHAT_MAX_MESSAGES: int = Field(default=200, ge=1)
    CHAT_MAX_MESSAGE_CHARS: int = Field(default=100_000, ge=1)
    CHAT_MAX_METADATA_KEYS: int = Field(default=20, ge=1)
    CHAT_MAX_METADATA_VALUE_CHARS: int = Field(default=1_000, ge=1)

    @property
    def large_body_prefixes(self) -> tuple[str, ...]:
        return tuple(
            p.strip()
            for p in self.SECURITY_LARGE_BODY_PATH_PREFIXES.split(",")
            if p.strip()
        )

    @property
    def streaming_prefixes(self) -> tuple[str, ...]:
        return tuple(
            p.strip()
            for p in self.SECURITY_STREAMING_PATH_PREFIXES.split(",")
            if p.strip()
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


security_settings = SecuritySettings()
