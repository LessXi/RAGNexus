"""Tests for config.py — pydantic-settings with LLM/Rerank/Rewrite 配置字段。"""

from ragnexus.config import Settings, get_settings


def test_defaults(monkeypatch):
    """验证所有配置字段的默认值正确（不含 .env 或环境变量覆盖）。"""
    # 清除可能干扰测试的环境变量
    monkeypatch.delenv("PG_DSN", raising=False)
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    monkeypatch.delenv("PG_POOL_MIN", raising=False)
    monkeypatch.delenv("PG_POOL_MAX", raising=False)
    monkeypatch.delenv("PG_COMMAND_TIMEOUT", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("RERANK_ENABLED", raising=False)
    monkeypatch.delenv("REWRITE_ENABLED", raising=False)
    s = Settings(_env_file=None)  # type: ignore[call-arg]  # 跳过 .env，仅测试默认值

    # ---- 现有字段 ----
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

    # ---- LLM 通用配置 ----
    assert s.LLM_BASE_URL == "https://opencode.ai/zen/v1"
    assert s.LLM_API_KEY == ""
    assert s.LLM_MODEL == "deepseek-v4-flash-free"
    assert s.LLM_REQUEST_TIMEOUT == 30.0
    assert s.LLM_CONNECT_TIMEOUT == 5.0
    assert s.LLM_MAX_CONCURRENCY == 5
    assert s.LLM_MAX_RETRIES == 3
    assert s.LLM_RETRY_BACKOFF_BASE == 2.0

    # ---- Rerank 配置 ----
    assert s.RERANK_ENABLED is False
    assert s.RERANK_CANDIDATE_MULTIPLIER == 3
    assert s.RERANK_MIN_CANDIDATES == 10
    assert s.RERANK_MAX_CANDIDATES == 20
    assert s.RERANK_CHUNK_MAX_CHARS == 1000
    assert s.RERANK_TEMPERATURE == 0.0
    assert s.RERANK_CACHE_TTL_SECONDS == 300
    assert s.RERANK_CACHE_MAX_ENTRIES == 100
    assert s.RERANK_CACHE_SIMILARITY_THRESHOLD == 0.95

    # ---- Rewrite 配置 ----
    assert s.REWRITE_ENABLED is False
    assert s.REWRITE_TEMPERATURE == 0.0
    assert s.REWRITE_CACHE_TTL_SECONDS == 300
    assert s.REWRITE_CACHE_MAX_ENTRIES == 100
    assert s.REWRITE_CACHE_SIMILARITY_THRESHOLD == 0.95


def test_get_settings_is_singleton():
    """get_settings() returns the same instance (@cache)."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
