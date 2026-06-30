## Context

RAGNexus 当前测试层级：
- **单元测试 (319)**：使用 Mock/MagicMock 隔离依赖，验证单个组件逻辑正确
- **集成测试 (5 文件)**：其中 4 个使用真实 PostgreSQL，1 个 (`test_retrieve_full_chain`) 实际是 Fake 实现
- **E2E 测试 (2 文件)**：使用 FastAPI TestClient，但无 DB 时崩溃

核心问题：测试金字塔底层宽（单元测试多）、中层窄（真实集成少）、顶层脆（E2E 不可靠）。

## Goals / Non-Goals

**Goals:**
- 补全集成测试层：核心业务链路有真实 PostgreSQL + pgvector 覆盖
- E2E 测试确定性可进 CI：pytest-httpx mock 外部 HTTP
- 失败模式有测试挡着：超时、429、连接拒绝、连接池耗尽
- 手工验收脚本：真实环境全链路一次性验证

**Non-Goals:**
- 不修改业务代码（只补测试）
- 不引入 perf/load 测试（需独立工具）
- 不测真实 embedder/LLM 质量（手工验收脚本负责）
- 不处理认证鉴权、多解析器（已有独立计划）

## Decisions

### 1. 集成测试策略：真实 DB + Mock 外部 HTTP

```
选择：真实 PostgreSQL + pgvector（Docker Compose test-db）
      + pytest-httpx mock embedder/LLM HTTP 调用

备选：纯 mock（如现有 test_retrieve_full_chain.py 的 Fake 实现）
拒绝：纯 mock 绕过了 SQL 语法、asyncpg 驱动、pgvector 扩展等真实集成点

备选：完整真实（含真实 embedder API）
拒绝：网络非确定性导致 CI flake，且需要 API key
```

### 2. E2E 测试策略：pytest-httpx 拦截外部 HTTP

```
选择：引入 pytest-httpx，在 E2E conftest 中 mock EMBED_BASE_URL + LLM_BASE_URL
      的 HTTP 请求，返回预定义响应

原理：FastAPI TestClient 创建真实 app stack（routing → middleware → use case → adapter），
      只在 adapter 层的 HTTP 出口做确定性 mock。这保证了：
      - HTTP 路由、参数校验、错误码 端到端真实
      - 数据库 CRUD 端到端真实  
      - 仅外部 API 调用被 mock（确定性，可进 CI）
```

### 3. pytest-httpx fixture 设计（含 TestClient 冲突规避）

**关键风险**：FastAPI TestClient 内部使用 httpx，pytest-httpx 默认拦截所有 httpx 请求。
不配置白名单会导致 TestClient 自身的请求被 mock 吞掉。

**解决方案**：使用 `non_mocked_hosts` 排除本地地址：

```python
# tests/e2e/conftest.py 新增
@pytest.fixture
def mock_external_http(httpx_mock):
    """Mock 外部 HTTP，不拦截 TestClient 自身的本地请求。"""
    # 关键：不让 pytest-httpx 拦截 localhost/127.0.0.1
    httpx_mock.add_response(
        url=re.compile(r"^https?://(?!localhost|127\.0\.0\.1).*"),
        is_optional=True,  # 兜底，不匹配的请求走真实网络
    )
    settings = get_settings()
    # Mock embedder
    httpx_mock.add_response(
        url=re.compile(re.escape(settings.EMBED_BASE_URL) + ".*"),
        json={"data": [{"embedding": [0.1] * settings.EMBED_DIM}]},
    )
    # Mock LLM
    httpx_mock.add_response(
        url=re.compile(re.escape(settings.LLM_BASE_URL) + ".*"),
        json={"choices": [{"message": {"content": '{"rankings": [...]}'}}]},
    )
    return httpx_mock
```

### 4. 外部服务降级测试设计

```
选择：在单元测试层做，不依赖真实 HTTP

原理：mock httpx.AsyncClient 的 post 方法抛出特定异常（TimeoutException、
      HTTPStatusError(429)），验证 adapter 层的 try/except 逻辑正确。

备选：集成/E2E 层用真实超时
拒绝：不可靠，CI 超时时间不好控制
```

### 5. Alembic 迁移验证测试设计

```
选择：独立测试脚本，操作真实 DB

实现：
1. 设置 os.environ["PG_DSN"] = TEST_DSN（覆盖生产配置）
2. get_settings.cache_clear()（清除 @lru_cache，避免读到旧 DSN）
3. conftest 提供空白数据库
4. subprocess.run(["alembic", "upgrade", "head"])
5. 验证所有表已创建
6. subprocess.run(["alembic", "downgrade", "-1"])
7. 验证所有表已删除

关键陷阱：alembic/env.py 中 get_settings() 有 @lru_cache，
如果其他测试先调用了 get_settings() 且 PG_DSN 指向生产库，
迁移测试会连错库。必须 cache_clear() 后再设环境变量。

备选：单元测试中 mock alembic API
拒绝：mock 绕过了迁移脚本本身的 SQL 语法验证
```

### 6. 手工验收脚本设计

```bash
#!/bin/bash
# scripts/verify-production.sh
set -e

echo "=== 1. 启动测试环境 ==="
docker compose -f docker-compose.test.yml up -d --wait

echo "=== 2. 数据库迁移 ==="
alembic upgrade head

echo "=== 3. 全量确定性测试 ==="
python -m pytest tests/ -m "not real_api" --ignore=tests/unit/adapters/test_middleware.py

echo "=== 4. 中间件测试 ==="
python -m pytest tests/unit/adapters/test_middleware.py

echo "=== 5. 真实 API E2E ==="
EMBED_API_KEY="$EMBED_API_KEY" LLM_API_KEY="$LLM_API_KEY" \
  python -m pytest tests/e2e/ -m real_api

| 风险 | 缓解 |
|------|------|
| pytest-httpx 是新增依赖 | 仅 dev 依赖，不影响生产 |
| 集成测试依赖 Docker | conftest skipif + 启动时 wait_for_db，CI 无 Docker 时优雅跳过 |
| Tier 3 E2E 测试变多可能拖慢 CI | mock 确定性快（无真实 HTTP），预估新增 <10s |
| middleware fixture 重构可能引入新问题 | 4 个测试原本就是 skip，最坏情况保持 skip；**2 轮修不好则重写 lifespan mock 为可复用 helper 函数，而非死磕修补** |
| 生命周期错误恢复测试 mock 链路过长 | 接受风险：5 层 mock 嵌套质量可能不高。**降级策略：若写不出干净的 mock 测试，改为在集成测试中验证（操作真实 DB，仅 mock Store）** |
| 手工验收脚本依赖真实 API key | 脚本检查环境变量，缺失时提示而非崩溃 |
| Alembic 迁移测试读到旧 DSN（@lru_cache） | 测试前显式 cache_clear() + 设 PG_DSN |
| pytest-httpx 拦截 TestClient 自身请求 | 使用 non_mocked_hosts 白名单排除 localhost（见决策 #3） |
