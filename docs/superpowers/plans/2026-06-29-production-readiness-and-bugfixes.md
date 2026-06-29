---
change: production-readiness-and-bugfixes
design-doc: docs/superpowers/specs/2026-06-29-production-readiness-and-bugfixes-design.md
base-ref: 949b2efc629e662137e40903dffa15a8588b6578
---

# RAGNexus Production Readiness & Bugfixes 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 RAGNexus 中 9 个确凿问题（资源泄漏、正确性风险、类型安全、生产就绪能力）

**Architecture:** 六边形架构，每个修复限定在对应层内。httpx 泄漏 → Adapter 层；log task → Application 层；Alembic → 基础设施层；/health → HTTP Adapter 层

**Tech Stack:** Python 3.11+, FastAPI, asyncpg, httpx, alembic

---

### Task 1: 修复 httpx 客户端资源泄漏

**Files:**
- Modify: `src/ragnexus/adapters/embedder/openai_compat.py`
- Modify: `src/ragnexus/adapters/llm/openai_compatible.py`
- Modify: `src/ragnexus/composition.py`

- [x] **1.1 在 OpenAICompatEmbedder 添加 close() 方法**

`openai_compat.py` 末尾：

```python
async def close(self) -> None:
    await self._client.aclose()
```

- [x] **1.2 在 OpenAICompatibleLLMProvider 添加 close() 方法**

`openai_compatible.py` 末尾（`chat_json` 方法之后）：

```python
async def close(self) -> None:
    await self._client.aclose()
```

- [x] **1.3 在 lifespan finally 块中关闭客户端**

`composition.py` 的 `lifespan` finally 块中，在关闭连接池之前：

```python
# 关闭 httpx 客户端
try:
    if embedder is not None:
        await embedder.close()
finally:
    if llm_provider is not None:
        await llm_provider.close()
```

- [x] **1.4 运行测试确认不回归**

```bash
cd /mnt/f/learnAgent/MyProjects/RAGNexus && python -m pytest tests/unit/adapters/test_embedder.py tests/unit/adapters/test_http.py -v --tb=short 2>&1
```

- [x] **1.5 提交**

---

### Task 2: 修复 log task 引用丢失

**Files:**
- Modify: `src/ragnexus/application/retrieve_use_case.py`

- [x] **2.1 在 RetrieveUseCase 中添加 _background_tasks set**

`__init__` 中添加 `self._background_tasks: set[asyncio.Task] = set()`

- [x] **2.2 修改 _log_retrieve 调用**

将 `asyncio.create_task(self._log_retrieve(...))` 改为：

```python
task = asyncio.create_task(self._log_retrieve(...))
task.add_done_callback(self._background_tasks.discard)
self._background_tasks.add(task)
```

- [x] **2.3 运行测试确认不回归**

```bash
cd /mnt/f/learnAgent/MyProjects/RAGNexus && python -m pytest tests/unit/application/test_retrieve.py -v --tb=short 2>&1
```

- [x] **2.4 提交**

---

### Task 3: 消除 type:ignore

**Files:**
- Modify: `src/ragnexus/composition.py`

- [x] **3.1 导入 cast**

```python
from typing import Any, cast
```

- [x] **3.2 替换 # type: ignore[arg-type]**

```python
kb_repo = PgKnowledgeBaseRepository(pool=cast(Any, repo_pool))
log_repo = PgRetrieveLogRepository(pool=cast(Any, repo_pool))
```

- [x] **3.3 运行 pyright 确认类型检查通过**

```bash
cd /mnt/f/learnAgent/MyProjects/RAGNexus && python -m pyright src/ragnexus/composition.py 2>&1
```

- [x] **3.4 提交**

---

### Task 4: Alembic 数据库迁移

**Files:**
- Create: `alembic.ini`
- Create: `alembic/` (directory)
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_initial_schema.py`
- Modify: `pyproject.toml`
- Modify: `src/ragnexus/composition.py`

- [x] **4.1 添加 alembic 依赖**

`pyproject.toml` 的 `[project.dependencies]` 中添加 `"alembic>=1.13"`

- [x] **4.2 初始化 Alembic 脚手架**

```bash
cd /mnt/f/learnAgent/MyProjects/RAGNexus && pip install alembic && alembic init alembic 2>&1
```

- [x] **4.3 配置 env.py 从 settings 读取连接串**

编辑 `alembic/env.py`：从环境变量读取 `PG_DSN`，配置 `target_metadata = None`（无 ORM 模型），`run_migrations_online()` 中使用连接串而非 `engine_from_config`

- [x] **4.4 编写初始迁移脚本**

手动创建 `alembic/versions/0001_initial_schema.py`，内容基于 `docs/sql/schema.sql`：
- `upgrade()`: CREATE EXTENSION IF NOT EXISTS vector; CREATE TABLE knowledge_bases, documents, chunks (含 vector(1024)), retrieve_logs + 索引
- `downgrade()`: DROP TABLE ...; 不删除扩展（安全降级）

- [x] **4.5 添加迁移检测告警**

`composition.py` lifespan 启动时（连接池创建后）：

```python
try:
    version = await repo_pool.fetchval("SELECT version_num FROM alembic_version")
except Exception:
    logger.warning("N 个待迁移未执行。部署前请运行 'alembic upgrade head'")
```

- [x] **4.6 运行测试确认不回归**

```bash
cd /mnt/f/learnAgent/MyProjects/RAGNexus && python -m pytest tests/ -v --tb=short -x 2>&1 | tail -50
```

- [x] **4.7 提交**

---

### Task 5: retrieve_logs TTL 清理

**Files:**
- Modify: `src/ragnexus/adapters/retrieve_log/pg.py`
- Modify: `src/ragnexus/composition.py`

- [x] **5.1 添加 prune() 方法**

`PgRetrieveLogRepository` 中添加：

```python
async def prune(self, before: datetime) -> int:
    result = await self.pool.execute(
        "DELETE FROM retrieve_logs WHERE created_at < $1", before
    )
    return result  # 返回删除行数
```

- [x] **5.2 lifespan 启动时执行清理**

`composition.py` lifespan 中（路由注册前）：

```python
try:
    deleted = await log_repo.prune(datetime.now(UTC) - timedelta(days=30))
    logger.info("Cleaned up %d old retrieve logs", deleted)
except Exception:
    logger.debug("Retrieve log cleanup skipped", exc_info=True)
```

- [x] **5.3 注册 24h 周期清理任务**

`composition.py` lifespan 中（启动清理后），使用 `asyncio.create_task` + task set 持有：

```python
async def _periodic_log_cleanup():
    while True:
        await asyncio.sleep(86400)
        try:
            await log_repo.prune(datetime.now(UTC) - timedelta(days=30))
        except Exception:
            logger.debug("Periodic log cleanup failed", exc_info=True)

_cleanup_task = asyncio.create_task(_periodic_log_cleanup())
_cleanup_task.add_done_callback(app.state._background_tasks.discard)
app.state._background_tasks.add(_cleanup_task)
```

（在 lifespan finally 中 cancel 该 task）

- [x] **5.4 运行测试确认**

```bash
cd /mnt/f/learnAgent/MyProjects/RAGNexus && python -m pytest tests/unit/adapters/test_retrieve_log.py -v --tb=short 2>&1
```

- [x] **5.5 提交**

---

### Task 6: /health 健康检查端点

**Files:**
- Create: `src/ragnexus/adapters/http/health_router.py`
- Modify: `src/ragnexus/composition.py`

- [x] **6.1 创建 health_router.py**

`src/ragnexus/adapters/http/health_router.py`：

```python
"""健康检查端点。"""
from datetime import datetime, timezone
import time
import sys

from fastapi import APIRouter, Depends
from ragnexus import __version__

_start_time = time.time()

def create_router(get_store, get_embedder):
    router = APIRouter(tags=["health"])

    @router.get("/health")
    async def health():
        checks = {}
        # DB 检查
        try:
            store = get_store()
            await asyncio.wait_for(store.pool.fetchval("SELECT 1"), timeout=3.0)
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "error"
        # Embedder 检查
        try:
            embedder = get_embedder()
            await asyncio.wait_for(
                embedder._client.head(embedder._base_url), timeout=3.0
            )
            checks["embedder"] = "ok"
        except Exception:
            checks["embedder"] = "error"

        status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
        return {
            "status": status,
            "checks": checks,
            "version": __version__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": int(time.time() - _start_time),
            "python_version": sys.version.split()[0],
        }

    return router
```

- [x] **6.2 在 composition.py 中注册路由**

```python
from ragnexus.adapters.http.health_router import create_router as create_health_router
...
app.include_router(create_health_router(
    lambda: store, lambda: embedder
))
```

- [x] **6.3 编写测试**

`tests/unit/adapters/test_health.py`（简单的响应格式验证）

- [x] **6.4 运行测试确认**

```bash
cd /mnt/f/learnAgent/MyProjects/RAGNexus && python -m pytest tests/unit/adapters/test_health.py tests/unit/adapters/test_http.py -v --tb=short 2>&1
```

- [x] **6.5 提交**

---

### Task 7: 修复缓存 key 不含 kb_id

**Files:**
- Modify: `src/ragnexus/adapters/rerank/llm.py`

- [x] **7.1 修改缓存 key 格式**

在 `LLMRerankProvider.rerank` 中，将缓存 key 从：

```python
_cache_key = (query_embedding_tuple, chunk.id)
```

改为：

```python
_cache_key = (tuple(sorted(kb_ids)), query_embedding_tuple, chunk.id)
```

（`kb_ids` 是 `rerank()` 方法的参数，已可用）

- [x] **7.2 修复 clear_cache(kb_id)**

将 `clear_cache` 方法从精确 key 删除改为按前缀匹配：

```python
async def clear_cache(self, kb_id: str) -> None:
    self._cache = {
        key: value
        for key, value in self._cache.items()
        if not (isinstance(key, tuple) and key[0] == kb_id)
    }
```

注意新 key 格式是 `(kb_ids_tuple, embedding_tuple, chunk_id)`，所以 `clear_cache(kb_id)` 需要匹配 `key[0]` 中是否包含该 `kb_id`。改为遍历匹配逻辑：

```python
async def clear_cache(self, kb_id: str) -> None:
    keys_to_delete = [
        key for key in self._cache
        if isinstance(key, tuple) and len(key) >= 3 and kb_id in key[0]
    ]
    for key in keys_to_delete:
        del self._cache[key]
```

- [x] **7.3 运行单元测试确认**

```bash
cd /mnt/f/learnAgent/MyProjects/RAGNexus && python -m pytest tests/unit/adapters/test_llm_rerank.py -v --tb=short 2>&1
```

- [x] **7.4 提交**

---

### Task 8: 移除 domain/errors.py

**Files:**
- Remove: `src/ragnexus/domain/errors.py`
- Modify: `src/ragnexus/domain/__init__.py`（如有导出该模块）

- [x] **8.1 搜索所有导入引用**

搜索 `from ragnexus.domain.errors` 并替换为 `from ragnexus.core.errors`

- [x] **8.2 删除文件**

```bash
rm src/ragnexus/domain/errors.py
```

- [x] **8.3 更新 __init__.py**

从 `domain/__init__.py` 中移除对 errors 的导出

- [x] **8.4 运行全量测试确认无导入断裂**

```bash
cd /mnt/f/learnAgent/MyProjects/RAGNexus && python -m pytest tests/ -x --tb=short 2>&1 | tail -30
```

- [x] **8.5 提交**

---

### Task 9: UploadDocumentUseCase 路由优化

**Files:**
- Modify: `src/ragnexus/adapters/http/upload_doc_router.py`

- [x] **9.1 精简路由响应**

在路由函数中，调用 `execute()` 后构造精简 `UploadResult`：

```python
result = await uc.execute(...)
return {
    "code": 0,
    "data": {
        "doc_id": result.doc_id,
        "chunk_count": result.chunk_count,
    },
    "message": "ok",
}
```

不修改 `UploadDocumentUseCase` 签名。

- [x] **9.2 运行测试确认不回归**

```bash
cd /mnt/f/learnAgent/MyProjects/RAGNexus && python -m pytest tests/unit/adapters/test_http.py tests/unit/application/test_upload_doc.py -v --tb=short 2>&1
```

- [x] **9.3 提交**
