"""Tests for config.py — pydantic-settings with 20 fields."""

from config import Settings, get_settings


def test_defaults(monkeypatch):
    """Verify default values are correct (without .env or env var overrides)."""
    monkeypatch.delenv("PG_DSN", raising=False)
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    monkeypatch.delenv("PG_POOL_MIN", raising=False)
    monkeypatch.delenv("PG_POOL_MAX", raising=False)
    monkeypatch.delenv("PG_COMMAND_TIMEOUT", raising=False)
    s = Settings(_env_file=None)  # skip .env to test built-in defaults
    assert s.HOST == "0.0.0.0"
    assert s.PORT == 8000
    assert s.LOG_LEVEL == "INFO"
    assert s.PG_DSN == "postgresql://ragnexus:ragnexus@localhost:5432/ragnexus"
    assert s.PG_POOL_MIN == 1
    assert s.PG_POOL_MAX == 10
    assert s.EMBED_BASE_URL == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert s.EMBED_API_KEY == ""
    assert s.EMBED_MODEL == "text-embedding-v3"
    assert s.EMBED_DIM == 1024
    assert s.EMBED_BATCH_SIZE == 50
    assert s.EMBED_MAX_CONCURRENCY == 5
    assert s.EMBED_MAX_RETRIES == 3
    assert s.CHUNK_MAX_CHARS == 1500
    assert s.CHUNK_OVERLAP == 50
    assert s.MAX_FILE_SIZE == 10 * 1024 * 1024  # 10MB
    assert s.EMBED_REQUEST_TIMEOUT == 30.0
    assert s.EMBED_CONNECT_TIMEOUT == 5.0
    assert s.EMBED_RETRY_BACKOFF_BASE == 2.0
    assert s.PG_COMMAND_TIMEOUT == 30.0


def test_get_settings_is_singleton():
    """get_settings() returns the same instance (lru_cache)."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
