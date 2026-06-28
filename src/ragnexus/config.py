"""应用配置 — 基于 pydantic-settings，从 .env 文件读取。"""

from functools import cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """46 个配置字段，从 .env 加载。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Logging
    LOG_DIR: str = "logs"
    LOG_QUEUE_SIZE: int = 5000
    LOG_CONSOLE_MAX_LENGTH: int = 500
    LOG_MODEL_CONTENT: bool = True

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

    # LLM 通用配置（被 Rerank 和 Rewrite 共享）
    LLM_BASE_URL: str = "https://opencode.ai/zen/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-v4-flash-free"
    LLM_REQUEST_TIMEOUT: float = 30.0
    LLM_CONNECT_TIMEOUT: float = 5.0
    LLM_MAX_CONCURRENCY: int = 5
    LLM_MAX_RETRIES: int = 3
    LLM_RETRY_BACKOFF_BASE: float = 2.0

    # Rerank 配置
    RERANK_ENABLED: bool = False
    RERANK_CANDIDATE_MULTIPLIER: int = 3
    RERANK_MIN_CANDIDATES: int = 10
    RERANK_MAX_CANDIDATES: int = 20
    RERANK_CHUNK_MAX_CHARS: int = 1000
    RERANK_TEMPERATURE: float = 0.0
    RERANK_CACHE_TTL_SECONDS: int = 300
    RERANK_CACHE_MAX_ENTRIES: int = 100
    RERANK_CACHE_SIMILARITY_THRESHOLD: float = 0.95

    # Rewrite 配置
    REWRITE_ENABLED: bool = False
    REWRITE_TEMPERATURE: float = 0.0
    REWRITE_CACHE_TTL_SECONDS: int = 300
    REWRITE_CACHE_MAX_ENTRIES: int = 100
    REWRITE_CACHE_SIMILARITY_THRESHOLD: float = 0.95


@cache
def get_settings() -> Settings:
    """返回缓存的 Settings 单例。"""
    return Settings()
