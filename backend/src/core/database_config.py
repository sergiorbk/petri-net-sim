from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PostgresSettings(BaseSettings):
    """PostgreSQL database configuration."""

    DB_HOST: str = Field(default="localhost")
    DB_PORT: int = Field(default=5432)
    DB_NAME: str = Field(default="petri_net_sim")
    DB_USER: str = Field(default="postgres")
    DB_PASSWORD: str = Field(default="postgres")

    # Connection pool
    DB_POOL_SIZE: int = Field(default=20)
    DB_MAX_OVERFLOW: int = Field(default=10)
    DB_POOL_RECYCLE: int = Field(default=3600)
    DB_POOL_PRE_PING: bool = Field(default=True)
    # Max seconds to wait for a free connection before failing the request.
    # Bounds request latency under load instead of hanging indefinitely.
    DB_POOL_TIMEOUT: int = Field(default=10)

    # Timeouts
    DB_CONNECT_TIMEOUT: int = Field(default=10)
    DB_COMMAND_TIMEOUT: int = Field(default=60)

    # SSL mode: disable | allow | prefer | require | verify-ca | verify-full

    @property
    def DATABASE_URL(self) -> str:
        """Async PostgreSQL connection URL."""
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def engine_config(self) -> dict:
        """SQLAlchemy engine configuration."""
        return {
            "pool_size": self.DB_POOL_SIZE,
            "max_overflow": self.DB_MAX_OVERFLOW,
            "pool_pre_ping": self.DB_POOL_PRE_PING,
            "pool_recycle": self.DB_POOL_RECYCLE,
            "pool_timeout": self.DB_POOL_TIMEOUT,
            "echo": False,
            "connect_args": {
                "server_settings": {"jit": "off"},
                "command_timeout": self.DB_COMMAND_TIMEOUT,
                "timeout": self.DB_CONNECT_TIMEOUT,
            },
        }

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


postgres_settings = PostgresSettings()
