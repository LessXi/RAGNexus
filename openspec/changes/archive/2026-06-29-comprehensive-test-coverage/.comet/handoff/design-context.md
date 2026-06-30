# Comet Design Handoff

- Change: comprehensive-test-coverage
- Phase: design
- Mode: compact
- Context hash: b9c108b1b5760396a2658c2d931923ad5180c308f56ffabde0ec1a95cbbf8bed

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/comprehensive-test-coverage/proposal.md

- Source: openspec/changes/comprehensive-test-coverage/proposal.md
- Lines: 1-56
- SHA256: b4d70119d2d0caed515b2b9df82982c1461500857503098ac2501b865d4c8dae

```md
## Why

RAGNexus 当前 319 个单元测试全部通过，但测试金字塔严重倒置——81% 的源码只有 mock 覆盖，核心业务链路（上传→解析→分块→向量化→存储→检索→重排）从未在真实环境中完整验证。新增功能（/health 端点、TTL 清理、close() 资源释放、Alembic 迁移、frozenset 缓存）几乎零测试覆盖。此外 E2E 测试在数据库不可用时崩溃而非优雅跳过，CI 无法执行。

简单说：**319 个测试全绿，但没人知道线上能不能跑。**

## What Changes

### 新增（按 Tier 分层）

**Tier 0 — 生死线（核心链路真实集成测试，上线前必备）**
- composition.py 集成测试：启动/关闭全生命周期（DB 连接、维度检测、迁移告警、TTL 清理、资源关闭顺序）
- RetrieveUseCase 真实集成测试：embed→search→rerank→log 全链路（真实 PostgreSQL + pgvector，mock 外部 HTTP）
- UploadDocumentUseCase 真实集成测试：parse→chunk→embed→store 全链路（同上）
- Alembic upgrade/downgrade 验证测试：迁移脚本在真实 DB 上可执行可回滚

**Tier 1 — 线上保障（失败模式覆盖）**
- 外部服务降级测试：embedder/LLM 超时、429 限流、连接拒绝时的降级行为
- 连接池耗尽测试：并发压力下 backpressure 不会 silent hang
- 生命周期错误恢复测试：启动阶段某步失败后资源清理正确性
- close() 测试：embedder/LLM HTTP client 正确关闭、无泄漏、重入安全

**Tier 2 — 技术债务清理**
- middleware fixture 重构：4 个 skip 测试恢复（MagicMock → AsyncMock 升级）
- candidate_k=0 边界测试：防御性配置边界验证
- E2E DB 探活 skipif：数据库不可用时优雅跳过而非崩溃
- coverage 配置：pyproject.toml 添加 `[tool.coverage.run]`

**Tier 3 — E2E 补全 + 手工验收**
- 引入 pytest-httpx：确定性 mock 外部 HTTP，E2E 可进 CI
- /health 端点 E2E：正常/降级/超时
- rewrite 启用全流程 E2E：mock LLM 返回改写结果 → 验证改写后检索正确
- rerank 启用全流程 E2E：mock LLM 返回重排结果 → 验证重排后排序正确
- 并发请求 E2E：5 并发请求连接池不炸
- 外部服务降级 E2E：mock 超时/429/连接拒绝 → 验证 HTTP 层降级行为
- `scripts/verify-production.sh`：手工验收脚本（启动 Docker → 迁移 → 真实 embedder/LLM 全链路验证 → 覆盖率报告），不进 CI

### 不变

- 不修改业务逻辑代码（除非发现 bug）
- 不新增功能
- 认证鉴权（#7）和多解析器（#9）不在本次范围

## Capabilities

### New Capabilities

- `integration-testing`: 真实 PostgreSQL + pgvector 集成测试基础设施，覆盖 composition 生命周期和核心业务链路
- `e2e-testing`: 确定性 E2E 测试框架（pytest-httpx mock 外部 HTTP），覆盖 HTTP 全栈行为
- `failure-mode-testing`: 外部服务故障注入和降级行为验证
- `coverage-config`: pytest-cov 配置和覆盖率报告
- `manual-verification`: 手工验收脚本，真实环境全链路一次性验证

### Modified Capabilities

无。本次不修改任何已有 spec 的 REQUIREMENTS，纯补测试覆盖。
```

## openspec/changes/comprehensive-test-coverage/design.md

- Source: openspec/changes/comprehensive-test-coverage/design.md
- Lines: 1-149
- SHA256: dc9dc0f13f69f7519728bf37fa53bd3afde9f789a9f82ce1c3193b93bf677172

[TRUNCATED]

```md
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

Full source: openspec/changes/comprehensive-test-coverage/design.md

## openspec/changes/comprehensive-test-coverage/tasks.md

- Source: openspec/changes/comprehensive-test-coverage/tasks.md
- Lines: 1-48
- SHA256: 9b2f67760b43afa15a43e2b1ef64e17935bf2e60eda622f16a18879bfa4f488b

```md
# Tasks — comprehensive-test-coverage

> 19 项任务，分 4 个 Tier。每个任务完成后勾选。

## 1. 基础设施准备

- [ ] 1.1 添加 dev 依赖：pytest-httpx>=0.23, pytest-asyncio 确认已安装
- [ ] 1.2 pyproject.toml 添加 [tool.coverage.run] 配置（source + omit）
- [ ] 1.3 E2E conftest.py DB 探活 skipif（DB 不可用时优雅跳过而非崩溃）

## 2. Tier 0 — 生死线（核心链路真实集成测试）

- [ ] 2.1 编写 composition 生命周期集成测试：正常启动/关闭/迁移告警（`tests/integration/test_composition.py`）
- [ ] 2.2 编写 RetrieveUseCase 真实集成测试：单 KB/多 KB/rerank 候选放大（`tests/integration/test_retrieve_full_chain.py` 重写为真实 DB）
- [ ] 2.3 编写 UploadDocumentUseCase 真实集成测试：上传→检索全链路（`tests/integration/test_upload_full_chain.py`）
- [ ] 2.4 编写 Alembic 迁移验证测试：upgrade head + downgrade -1（`tests/integration/test_alembic_migration.py`）

## 3. Tier 1 — 线上保障（失败模式覆盖）

- [ ] 3.1 编写 embedder 降级测试：超时/重试耗尽/连接拒绝（补入 `tests/unit/adapters/test_embedder.py`）
- [ ] 3.2 编写 LLMProvider 降级测试：429/连接拒绝（补入 `tests/unit/test_llm_provider.py`）
- [ ] 3.3 编写 Semaphore 并发控制测试：验证 max_concurrency 限制和释放（补入 `tests/unit/adapters/test_embedder.py`）
- [ ] 3.4 编写 close() 测试：Embedder 和 LLMProvider 正确关闭/重入安全（补入已有测试文件）
- [ ] 3.5 编写生命周期错误恢复测试：Store 连接失败后资源清理（补入 `tests/integration/test_composition.py`，降级策略：若 mock 链路过长，改为真实 DB + 仅 mock Store）

## 4. Tier 2 — 技术债务清理

- [ ] 4.1 重构 test_middleware.py fixture：MagicMock→AsyncMock 升级，恢复 4 个 skip 测试（降级策略：2 轮修不好则重写 lifespan mock 为可复用 helper 函数）
- [ ] 4.2 补 frozenset 多 KB 缓存隔离测试（补入 `tests/unit/test_llm_rerank.py`）
- [ ] 4.3 补 CacheInvalidatingUploadUseCase 测试：上传后 rerank/rewrite 缓存被清空（补入 `tests/unit/adapters/test_middleware.py`）

## 5. Tier 3 — E2E 补全

- [ ] 5.1 E2E conftest 添加 pytest-httpx mock fixture（non_mocked_hosts 白名单避免拦截 TestClient）
- [ ] 5.2 编写 /health 端点 E2E：正常 (200 + checks.db=ok) / 降级 (503 + checks.db=error)（补入 `tests/e2e/test_smoke.py`）
- [ ] 5.3 编写 rewrite 启用全流程 E2E：mock LLM 返回改写结果 → 验证改写后检索（新文件 `tests/e2e/test_optimizations.py`）
- [ ] 5.4 编写 rerank 启用全流程 E2E：mock LLM 返回重排结果 → 验证排序（同上）
- [ ] 5.5 编写并发请求 E2E：5 并发检索无 500（补入 `tests/e2e/test_smoke.py`）
- [ ] 5.6 编写外部服务降级 E2E：mock embedder 超时 / LLM 429 → 验证降级（补入 `tests/e2e/test_smoke.py`）
- [ ] 5.7 编写 scripts/verify-production.sh 手工验收脚本

## 6. 验收

- [ ] 6.1 全量单元+集成测试通过（无 skip，无 error）
- [ ] 6.2 middleware 测试恢复：4 skip → pass（或按降级策略重写）
- [ ] 6.3 E2E 测试通过：pytest tests/e2e/ -m "not real_api"
- [ ] 6.4 覆盖率报告：pytest --cov=src/ragnexus --cov-report=term
- [ ] 6.5 手工验收脚本执行：bash scripts/verify-production.sh（需 Docker + API key）
```

## openspec/changes/comprehensive-test-coverage/specs/coverage-config/spec.md

- Source: openspec/changes/comprehensive-test-coverage/specs/coverage-config/spec.md
- Lines: 1-12
- SHA256: 7ccb9cff5784827d2cc8b78b0a06defc14b3fbfc7d815e137295aedd304a39df

```md
## ADDED Requirements

### Requirement: pytest-cov 配置

#### Scenario: 覆盖率只统计源码
- **WHEN** 运行 pytest --cov
- **THEN** 仅统计 src/ragnexus/ 目录下的代码
- **AND** 不统计 tests/、.venv/、alembic/ 等目录

#### Scenario: 覆盖率报告可读
- **WHEN** 运行 pytest --cov --cov-report=term
- **THEN** 终端输出按文件展示覆盖率百分比
```

## openspec/changes/comprehensive-test-coverage/specs/e2e-testing/spec.md

- Source: openspec/changes/comprehensive-test-coverage/specs/e2e-testing/spec.md
- Lines: 1-61
- SHA256: 5a79758f398e86c4fa69ab9ab20a46a3d013d2e9abd4676ff9344b413cf6e70c

```md
## ADDED Requirements

### Requirement: E2E 测试使用 pytest-httpx 确定性 mock

E2E 测试通过 pytest-httpx mock 外部 HTTP 调用，确保确定性、可进 CI。

#### Scenario: embedder 请求被 mock 拦截
- **WHEN** E2E 测试发起上传请求
- **THEN** 所有发往 EMBED_BASE_URL 的 HTTP 请求被 pytest-httpx mock 拦截
- **AND** mock 返回预定义的向量

#### Scenario: LLM 请求被 mock 拦截
- **WHEN** E2E 测试启用 rerank/rewrite
- **THEN** 所有发往 LLM_BASE_URL 的 HTTP 请求被 pytest-httpx mock 拦截
- **AND** mock 返回预定义的 JSON 响应

### Requirement: /health 端点 E2E 测试

#### Scenario: 正常响应
- **WHEN** GET /health 且数据库可连接
- **THEN** 返回 200
- **AND** body 含 {"status": "ok", "checks": {"database": "ok"}}
- **AND** 含 version、timestamp、uptime_seconds、python_version 字段

#### Scenario: 数据库不可用时降级
- **WHEN** GET /health 且数据库连接超时
- **THEN** 返回 503
- **AND** body 含 {"status": "degraded", "checks": {"database": "error"}}

### Requirement: Rewrite 启用全流程 E2E

#### Scenario: 查询改写后检索
- **WHEN** rewrite 启用且发起 retrieve 请求
- **THEN** LLM 被调用进行查询改写
- **AND** 改写后的查询用于向量搜索

### Requirement: Rerank 启用全流程 E2E

#### Scenario: 重排后结果排序改变
- **WHEN** rerank 启用且发起 retrieve 请求
- **THEN** LLM 被调用进行重排打分
- **AND** 返回结果按 rerank_score 降序排列

### Requirement: 并发请求 E2E

#### Scenario: 5 并发检索无错误
- **WHEN** 同时发起 5 个检索请求
- **THEN** 所有请求返回 200，无 500 错误
- **AND** 连接池未耗尽

### Requirement: 外部服务降级 E2E

#### Scenario: embedder 超时时优雅降级
- **WHEN** mock embedder 返回超时
- **THEN** 上传请求返回 5xx 错误而非 crash
- **AND** 应用仍可接受后续请求

#### Scenario: LLM 429 限流时优雅降级
- **WHEN** mock LLM 返回 429
- **THEN** 检索请求降级返回原始向量排序结果
- **AND** 不抛异常到 HTTP 层
```

## openspec/changes/comprehensive-test-coverage/specs/failure-mode-testing/spec.md

- Source: openspec/changes/comprehensive-test-coverage/specs/failure-mode-testing/spec.md
- Lines: 1-65
- SHA256: bb0d2664b1dae6ce5c5cb6c082bace8faaeb7ddb0ca4211470cb7e0a719ee971

```md
## ADDED Requirements

### Requirement: Embedder 超时降级

#### Scenario: embedder API 超时
- **WHEN** embedder.embed() 调用超时
- **THEN** 抛出明确的应用异常（非原始 httpx 异常）
- **AND** 异常含可操作的错误信息

#### Scenario: embedder 重试耗尽后失败
- **WHEN** embedder API 连续失败超过 max_retries
- **THEN** 抛出异常，最后一次失败原因被保留

### Requirement: LLM Provider 降级

#### Scenario: LLM API 返回 429
- **WHEN** LLM API 返回 HTTP 429
- **THEN** 调用方（rerank/rewrite）感知为失败
- **AND** rerank 降级返回原始向量排序
- **AND** rewrite 降级使用原始查询

#### Scenario: LLM API 连接拒绝
- **WHEN** LLM_BASE_URL 不可达
- **THEN** 连接异常被正确捕获并包装

### Requirement: 并发控制 Semaphore 验证

#### Scenario: Semaphore 限制并发数
- **WHEN** 同时发起超过 max_concurrency 的 embedder 调用
- **THEN** 超出并发的调用等待而非立即失败
- **AND** Semaphore 正确释放（无泄漏）

#### Scenario: 并发未超限时全速执行
- **WHEN** 并发数不超过 max_concurrency
- **THEN** 所有调用不被 Semaphore 阻塞

### Requirement: 生命周期错误恢复

#### Scenario: Store 连接失败时清理已创建资源
- **WHEN** PgVectorStore.connect() 失败
- **THEN** 已创建的 _raw_store_pool 被正确关闭
- **AND** 不泄漏连接

#### Scenario: Embedder 初始化后 Store 连接失败
- **WHEN** 流程已创建 embedder 但 store 连接失败
- **THEN** finally 中 embedder.close() 被调用

### Requirement: close() 资源释放

#### Scenario: Embedder close() 正确关闭 HTTP client
- **WHEN** 调用 embedder.close()
- **THEN** 内部 httpx.AsyncClient 被 aclose()
- **AND** 后续访问 client 属性返回 None

#### Scenario: Embedder close() 重入安全
- **WHEN** 连续调用两次 embedder.close()
- **THEN** 第二次调用不抛异常

#### Scenario: LLMProvider close() 正确关闭
- **WHEN** 调用 llm_provider.close()
- **THEN** 内部 httpx.AsyncClient 被 aclose()

#### Scenario: LLMProvider close() 重入安全
- **WHEN** 连续调用两次 llm_provider.close()
- **THEN** 第二次调用不抛异常
```

## openspec/changes/comprehensive-test-coverage/specs/integration-testing/spec.md

- Source: openspec/changes/comprehensive-test-coverage/specs/integration-testing/spec.md
- Lines: 1-60
- SHA256: 5d7d683697528b9f5509652c9c7a4bcadcb7adc408fd9778ce441289a7854b7f

```md
## ADDED Requirements

### Requirement: Composition 生命周期集成测试

composition.py 的 lifespan 启动/关闭流程可通过集成测试验证。

#### Scenario: 正常启动
- **WHEN** 测试数据库可用且 schema 已创建
- **THEN** build_app() 返回的 FastAPI 实例在 TestClient 中正常启动，所有路由已注册
- **AND** /health 返回 200

#### Scenario: 正常关闭
- **WHEN** TestClient 上下文退出
- **THEN** 连接池正确关闭，embedder/LLM HTTP client 正确关闭
- **AND** 后台清理任务被取消

#### Scenario: 迁移未执行时告警
- **WHEN** alembic_version 表不存在或为空
- **THEN** lifespan 打印 WARNING 级别日志但不阻塞启动

### Requirement: RetrieveUseCase 全链路集成测试

检索全链路可在真实 PostgreSQL + pgvector 上验证（外部 HTTP 用 mock）。

#### Scenario: 单 KB 检索
- **WHEN** 向已有 chunks 的 KB 发起检索请求
- **THEN** 返回按 cosine 相似度排序的 SearchHit 列表

#### Scenario: 多 KB 检索
- **WHEN** 同时检索 2 个 KB
- **THEN** 返回跨 KB 合并排序的结果

#### Scenario: Rerank 启用时候选放大
- **WHEN** RERANK_ENABLED=true 且配置了 candidate_multiplier
- **THEN** 向量搜索使用 candidate_k = top_k × candidate_multiplier 召回

### Requirement: UploadDocumentUseCase 全链路集成测试

上传全链路可在真实 PostgreSQL + pgvector 上验证。

#### Scenario: Markdown 上传成功
- **WHEN** 上传一个多标题 Markdown 文件
- **THEN** 文件被解析、分块、向量化、存储
- **AND** 返回 chunk_count >= 分块数

#### Scenario: 上传后立即可检索
- **WHEN** 上传成功后立即检索
- **THEN** 返回至少 1 个命中结果

### Requirement: Alembic 迁移验证

迁移脚本可在真实数据库上执行和回滚。

#### Scenario: upgrade head 成功
- **WHEN** 对空白测试库运行 alembic upgrade head
- **THEN** 所有表被创建，包含 chunks.embedding vector 列

#### Scenario: downgrade 成功
- **WHEN** 对已迁移库运行 alembic downgrade -1
- **THEN** 所有表被删除，回到空白状态
```

## openspec/changes/comprehensive-test-coverage/specs/manual-verification/spec.md

- Source: openspec/changes/comprehensive-test-coverage/specs/manual-verification/spec.md
- Lines: 1-22
- SHA256: a5075e1ddc330f3fde0675abf4eb05fe8282f75de441552bb3164ee36988727b

```md
## ADDED Requirements

### Requirement: 手工验收脚本

#### Scenario: 一键启动验收环境
- **WHEN** 运行 bash scripts/verify-production.sh
- **THEN** Docker Compose 启动 test-db
- **AND** Alembic upgrade head 执行
- **AND** 全量确定性测试执行
- **AND** 真实 API E2E 测试执行（需 EMBED_API_KEY + LLM_API_KEY）
- **AND** 覆盖率报告生成
- **AND** 打印验收结果摘要

#### Scenario: 验收脚本不进 CI
- **WHEN** CI 环境运行 pytest
- **THEN** verify-production.sh 不被调用
- **AND** 真实 API 测试被 pytest.mark.skipif 跳过

#### Scenario: 验收失败时清理
- **WHEN** 验收过程中任一步骤失败
- **THEN** 脚本打印失败原因
- **AND** Docker Compose 被停止（teardown）
```

