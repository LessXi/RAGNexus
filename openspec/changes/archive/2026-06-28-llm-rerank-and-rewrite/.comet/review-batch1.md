aeaf843 feat(llm): 创建 LLMProvider ABC 抽象基类
bde2082 chore(env): 同步 .env.example 新增 LLM/Rerank/Rewrite 配置项
f6df7cf feat(config): 新增 LLM/Rerank/Rewrite 配置字段

 .env.example                          | 28 +++++++++++++++++++++
 src/ragnexus/adapters/llm/__init__.py |  5 ++++
 src/ragnexus/adapters/llm/base.py     | 41 ++++++++++++++++++++++++++++++
 src/ragnexus/config.py                | 30 +++++++++++++++++++++-
 tests/unit/test_config.py             | 40 ++++++++++++++++++++++++++---
 tests/unit/test_llm_provider.py       | 47 +++++++++++++++++++++++++++++++++++
 6 files changed, 187 insertions(+), 4 deletions(-)

diff --git a/.env.example b/.env.example
index 2d5cce3..1a42123 100644
--- a/.env.example
+++ b/.env.example
@@ -17,10 +17,38 @@ HOST=0.0.0.0
 PORT=8000
 LOG_LEVEL=INFO
 EMBED_REQUEST_TIMEOUT=30
 EMBED_CONNECT_TIMEOUT=5
 EMBED_RETRY_BACKOFF_BASE=2
 PG_COMMAND_TIMEOUT=30
 LOG_DIR=logs
 LOG_QUEUE_SIZE=5000
 LOG_CONSOLE_MAX_LENGTH=500
 LOG_MODEL_CONTENT=true
+
+# LLM 通用配置（被 Rerank 和 Rewrite 共享）
+LLM_BASE_URL=https://opencode.ai/zen/v1
+LLM_API_KEY=
+LLM_MODEL=deepseek-v4-flash-free
+LLM_REQUEST_TIMEOUT=30
+LLM_CONNECT_TIMEOUT=5
+LLM_MAX_CONCURRENCY=5
+LLM_MAX_RETRIES=3
+LLM_RETRY_BACKOFF_BASE=2
+
+# Rerank 配置（重排）
+RERANK_ENABLED=false
+RERANK_CANDIDATE_MULTIPLIER=3
+RERANK_MIN_CANDIDATES=10
+RERANK_MAX_CANDIDATES=20
+RERANK_CHUNK_MAX_CHARS=1000
+RERANK_TEMPERATURE=0
+RERANK_CACHE_TTL_SECONDS=300
+RERANK_CACHE_MAX_ENTRIES=100
+RERANK_CACHE_SIMILARITY_THRESHOLD=0.95
+
+# Rewrite 配置（查询改写）
+REWRITE_ENABLED=false
+REWRITE_TEMPERATURE=0
+REWRITE_CACHE_TTL_SECONDS=300
+REWRITE_CACHE_MAX_ENTRIES=100
+REWRITE_CACHE_SIMILARITY_THRESHOLD=0.95
diff --git a/src/ragnexus/adapters/llm/__init__.py b/src/ragnexus/adapters/llm/__init__.py
new file mode 100644
index 0000000..99d18ad
--- /dev/null
+++ b/src/ragnexus/adapters/llm/__init__.py
@@ -0,0 +1,5 @@
+"""LLM 调用适配器包。"""
+
+from ragnexus.adapters.llm.base import LLMProvider
+
+__all__ = ["LLMProvider"]
diff --git a/src/ragnexus/adapters/llm/base.py b/src/ragnexus/adapters/llm/base.py
new file mode 100644
index 0000000..121540b
--- /dev/null
+++ b/src/ragnexus/adapters/llm/base.py
@@ -0,0 +1,41 @@
+"""LLMProvider 抽象基类 — 通用大模型调用抽象。
+
+与 domain/ports.py 中的 Protocol 不同，LLMProvider 用 ABC 因为：
+- 包含共享的 HTTP client 管理、并发控制、重试逻辑
+- 子类需要继承这些共享实现，而非纯鸭子类型
+- 这是 adapters 层内部抽象，不是 domain 端口
+"""
+
+from abc import ABC, abstractmethod
+
+
+class LLMProvider(ABC):
+    """通用大模型调用抽象。所有 LLM 调用必须通过此接口。
+
+    不定义在 domain/ports.py 中 — 这是 adapters 层内部抽象。
+    后续 query rewrite、意图识别、评测辅助生成等也通过它调用大模型。
+
+    子类必须实现 chat_json 方法，通过 OpenAI 兼容 API 调用大模型并返回 JSON 响应。
+    """
+
+    @abstractmethod
+    async def chat_json(
+        self,
+        *,
+        system_prompt: str,
+        user_payload: dict,
+        temperature: float = 0.0,
+        timeout_seconds: int | None = None,
+    ) -> dict:
+        """调用大模型并返回 JSON 响应。
+
+        参数:
+            system_prompt: 系统提示词，定义模型角色和输出要求
+            user_payload: 用户输入负载（会被 JSON 序列化后发送）
+            temperature: 采样温度，0.0 表示确定性输出
+            timeout_seconds: 可选超时秒数，None 使用默认值
+
+        返回:
+            模型返回的 JSON 响应（已解析为 dict）
+        """
+        ...
diff --git a/src/ragnexus/config.py b/src/ragnexus/config.py
index c5ece6b..0a137bd 100644
--- a/src/ragnexus/config.py
+++ b/src/ragnexus/config.py
@@ -1,19 +1,19 @@
 """应用配置 — 基于 pydantic-settings，从 .env 文件读取。"""
 
 from functools import cache
 
 from pydantic_settings import BaseSettings, SettingsConfigDict
 
 
 class Settings(BaseSettings):
-    """24 configuration fields loaded from .env."""
+    """46 个配置字段，从 .env 加载。"""
 
     model_config = SettingsConfigDict(env_file=".env", extra="ignore")
 
     # Server
     HOST: str = "0.0.0.0"
     PORT: int = 8000
     LOG_LEVEL: str = "INFO"
 
     # Logging
     LOG_DIR: str = "logs"
@@ -37,15 +37,43 @@ class Settings(BaseSettings):
     EMBED_MAX_RETRIES: int = 3
     EMBED_REQUEST_TIMEOUT: float = 30.0
     EMBED_CONNECT_TIMEOUT: float = 5.0
     EMBED_RETRY_BACKOFF_BASE: float = 2.0
 
     # Chunking
     CHUNK_MAX_CHARS: int = 1500
     CHUNK_OVERLAP: int = 50
     MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB
 
+    # LLM 通用配置（被 Rerank 和 Rewrite 共享）
+    LLM_BASE_URL: str = "https://opencode.ai/zen/v1"
+    LLM_API_KEY: str = ""
+    LLM_MODEL: str = "deepseek-v4-flash-free"
+    LLM_REQUEST_TIMEOUT: float = 30.0
+    LLM_CONNECT_TIMEOUT: float = 5.0
+    LLM_MAX_CONCURRENCY: int = 5
+    LLM_MAX_RETRIES: int = 3
+    LLM_RETRY_BACKOFF_BASE: float = 2.0
+
+    # Rerank 配置
+    RERANK_ENABLED: bool = False
+    RERANK_CANDIDATE_MULTIPLIER: int = 3
+    RERANK_MIN_CANDIDATES: int = 10
+    RERANK_MAX_CANDIDATES: int = 20
+    RERANK_CHUNK_MAX_CHARS: int = 1000
+    RERANK_TEMPERATURE: float = 0.0
+    RERANK_CACHE_TTL_SECONDS: int = 300
+    RERANK_CACHE_MAX_ENTRIES: int = 100
+    RERANK_CACHE_SIMILARITY_THRESHOLD: float = 0.95
+
+    # Rewrite 配置
+    REWRITE_ENABLED: bool = False
+    REWRITE_TEMPERATURE: float = 0.0
+    REWRITE_CACHE_TTL_SECONDS: int = 300
+    REWRITE_CACHE_MAX_ENTRIES: int = 100
+    REWRITE_CACHE_SIMILARITY_THRESHOLD: float = 0.95
+
 
 @cache
 def get_settings() -> Settings:
     """返回缓存的 Settings 单例。"""
     return Settings()
diff --git a/tests/unit/test_config.py b/tests/unit/test_config.py
index d259c7a..ff3f03c 100644
--- a/tests/unit/test_config.py
+++ b/tests/unit/test_config.py
@@ -1,23 +1,29 @@
-"""Tests for config.py — pydantic-settings with 20 fields."""
+"""Tests for config.py — pydantic-settings with LLM/Rerank/Rewrite 配置字段。"""
 
 from ragnexus.config import Settings, get_settings
 
 
 def test_defaults(monkeypatch):
-    """Verify default values are correct (without .env or env var overrides)."""
+    """验证所有配置字段的默认值正确（不含 .env 或环境变量覆盖）。"""
+    # 清除可能干扰测试的环境变量
     monkeypatch.delenv("PG_DSN", raising=False)
     monkeypatch.delenv("EMBED_API_KEY", raising=False)
     monkeypatch.delenv("PG_POOL_MIN", raising=False)
     monkeypatch.delenv("PG_POOL_MAX", raising=False)
     monkeypatch.delenv("PG_COMMAND_TIMEOUT", raising=False)
-    s = Settings(_env_file=None)  # type: ignore[call-arg]  # skip .env to test defaults
+    monkeypatch.delenv("LLM_API_KEY", raising=False)
+    monkeypatch.delenv("RERANK_ENABLED", raising=False)
+    monkeypatch.delenv("REWRITE_ENABLED", raising=False)
+    s = Settings(_env_file=None)  # type: ignore[call-arg]  # 跳过 .env，仅测试默认值
+
+    # ---- 现有字段 ----
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
@@ -25,16 +31,44 @@ def test_defaults(monkeypatch):
     assert s.EMBED_MAX_CONCURRENCY == 5
     assert s.EMBED_MAX_RETRIES == 3
     assert s.CHUNK_MAX_CHARS == 1500
     assert s.CHUNK_OVERLAP == 50
     assert s.MAX_FILE_SIZE == 10 * 1024 * 1024  # 10MB
     assert s.EMBED_REQUEST_TIMEOUT == 30.0
     assert s.EMBED_CONNECT_TIMEOUT == 5.0
     assert s.EMBED_RETRY_BACKOFF_BASE == 2.0
     assert s.PG_COMMAND_TIMEOUT == 30.0
 
+    # ---- LLM 通用配置 ----
+    assert s.LLM_BASE_URL == "https://opencode.ai/zen/v1"
+    assert s.LLM_API_KEY == ""
+    assert s.LLM_MODEL == "deepseek-v4-flash-free"
+    assert s.LLM_REQUEST_TIMEOUT == 30.0
+    assert s.LLM_CONNECT_TIMEOUT == 5.0
+    assert s.LLM_MAX_CONCURRENCY == 5
+    assert s.LLM_MAX_RETRIES == 3
+    assert s.LLM_RETRY_BACKOFF_BASE == 2.0
+
+    # ---- Rerank 配置 ----
+    assert s.RERANK_ENABLED is False
+    assert s.RERANK_CANDIDATE_MULTIPLIER == 3
+    assert s.RERANK_MIN_CANDIDATES == 10
+    assert s.RERANK_MAX_CANDIDATES == 20
+    assert s.RERANK_CHUNK_MAX_CHARS == 1000
+    assert s.RERANK_TEMPERATURE == 0.0
+    assert s.RERANK_CACHE_TTL_SECONDS == 300
+    assert s.RERANK_CACHE_MAX_ENTRIES == 100
+    assert s.RERANK_CACHE_SIMILARITY_THRESHOLD == 0.95
+
+    # ---- Rewrite 配置 ----
+    assert s.REWRITE_ENABLED is False
+    assert s.REWRITE_TEMPERATURE == 0.0
+    assert s.REWRITE_CACHE_TTL_SECONDS == 300
+    assert s.REWRITE_CACHE_MAX_ENTRIES == 100
+    assert s.REWRITE_CACHE_SIMILARITY_THRESHOLD == 0.95
+
 
 def test_get_settings_is_singleton():
     """get_settings() returns the same instance (@cache)."""
     s1 = get_settings()
     s2 = get_settings()
     assert s1 is s2
diff --git a/tests/unit/test_llm_provider.py b/tests/unit/test_llm_provider.py
new file mode 100644
index 0000000..d6dfbf8
--- /dev/null
+++ b/tests/unit/test_llm_provider.py
@@ -0,0 +1,47 @@
+"""LLMProvider ABC 抽象基类测试。
+
+TDD: RED → GREEN → REFACTOR。
+运行: uv run pytest tests/unit/test_llm_provider.py -v
+"""
+
+import abc
+
+import pytest
+
+from ragnexus.adapters.llm.base import LLMProvider
+
+
+class TestLLMProviderABC:
+    """测试 LLMProvider 抽象基类的结构约束。"""
+
+    def test_is_abc_subclass(self):
+        """LLMProvider 必须是 abc.ABC 的直接或间接子类。"""
+        assert issubclass(LLMProvider, abc.ABC)
+
+    def test_cannot_instantiate_directly(self):
+        """抽象类不能直接实例化——缺少 chat_json 实现时抛 TypeError。"""
+        with pytest.raises(TypeError):
+            LLMProvider()  # type: ignore[abstract]
+
+    def test_has_chat_json_abstract_method(self):
+        """LLMProvider 必须声明 chat_json 为抽象方法。"""
+        assert hasattr(LLMProvider, "chat_json")
+        method = LLMProvider.chat_json
+        assert getattr(method, "__isabstractmethod__", False), "chat_json 必须是 @abstractmethod"
+
+    def test_concrete_subclass_can_be_instantiated(self):
+        """实现了 chat_json 的最小子类可以正常实例化。"""
+
+        class ConcreteLLM(LLMProvider):
+            async def chat_json(
+                self,
+                *,
+                system_prompt: str,
+                user_payload: dict,
+                temperature: float = 0.0,
+                timeout_seconds: int | None = None,
+            ) -> dict:
+                return {"result": "ok"}
+
+        instance = ConcreteLLM()
+        assert isinstance(instance, LLMProvider)
