"""Application configuration via pydantic-settings.

All settings are read from .env file with sensible defaults.
"""

from functools import cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """20 configuration fields loaded from .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Postgres
    PG_DSN: str = "postgresql://ragnexus:ragnexus@localhost:5432/ragnexus"
    PG_POOL_MIN: int = 1
    PG_POOL_MAX: int = 10
    PG_COMMAND_TIMEOUT: float = 30.0

    # Embedder
    EMBED_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBED_API_KEY: str = ""
    EMBED_MODEL: str = "text-embedding-v3"
    EMBED_DIM: int = 1024
    EMBED_BATCH_SIZE: int = 50
    EMBED_MAX_CONCURRENCY: int = 5
    EMBED_MAX_RETRIES: int = 3
    EMBED_REQUEST_TIMEOUT: float = 30.0
    EMBED_CONNECT_TIMEOUT: float = 5.0
    EMBED_RETRY_BACKOFF_BASE: float = 2.0

    # Chunking
    CHUNK_MAX_CHARS: int = 1500
    CHUNK_OVERLAP: int = 50
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB


@cache
def get_settings() -> Settings:
    """Return cached Settings singleton."""
    return Settings()
