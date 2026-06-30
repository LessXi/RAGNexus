# Task 7.5-7.7 完成报告

## 概述

完成了 RAGNexus Phase 7 三个测试任务：集成测试、HTTP schema 不变性验证、E2E 测试。

## Task 7.5: 集成测试

**文件**: `tests/integration/test_retrieve_full_chain.py`
**测试数**: 16 个（全部通过 ✅）

### Fake 实现
- `FakeKBRepo` — 假 KB 仓库（所有 KB 均存在）
- `FakeEmbedder` — 假 Embedder（返回固定向量 8 维）
- `FakeVectorStore` — 假向量存储（返回可控 SearchHit 列表）
- `FakeLogPort` — 假日志端口（记录调用，无 IO）
- `FakeReranker` — 假 Reranker（反转 chunks 模拟重排）
- `FakeRewriter` — 假 Rewriter（给 query 加前缀）

### 测试场景

| 场景 | 类名 | 测试数 | 验证内容 |
|------|------|--------|----------|
| 两者启用 | `TestBothRewriteAndRerankEnabled` | 3 | 数据流顺序、reranker 输出是最终结果、rerank 用原始 query |
| 两者禁用 | `TestBothDisabled` | 3 | 直通 embed(原始)→search→return、noop 行为 |
| 仅 Rewrite | `TestRewriteOnly` | 2 | embed 用改写 query、返回长度等于 top_k |
| 仅 Rerank | `TestRerankOnly` | 3 | embed 用原始 query、rerank 接收原始 query、rerank 修改结果 |
| candidate_k | `TestCandidateK` | 5 | multiplier 计算、min_candidates 计算、max 取大者、默认值 |

## Task 7.6: HTTP schema 不变性验证

**文件**: `tests/unit/adapters/test_http_schema_invariance.py`
**测试数**: 19 个（全部通过 ✅）

### 验证内容

#### 请求 schema（9 个测试）
- `model_fields` 只含 `{"query", "kb_ids", "top_k"}`
- `extra='forbid'` 配置
- 无 `rerank_options` / `rewrite_options` / `rerank_enabled` / `rewrite_enabled`
- `top_k` 默认值 5
- `query` 和 `kb_ids` 必填
- request model 是 Pydantic BaseModel 子类

#### 响应 schema（6 个测试）
- `SearchHit` 字段只含 6 个标准字段
- `score` 类型为 `float`
- 无 `rerank_score` / `rewritten_query` / `rewrite_reason` / `rewrite_needed`
- `score` 不为 Optional

#### Router 响应格式（4 个测试）
- `create_router` 导出存在
- `model_dump()` 只有三个 key
- SearchHit 序列化含 round(score, 6)
- 响应 code/message/data/total/hits 从源码字符串验证

## Task 7.7: E2E 测试

**文件**: `tests/e2e/test_optimizations.py`
**测试数**: 8 个（3 通过 ✅ + 5 skip ⏭️）

### 结构

| 类名 | 测试数 | 状态 | 说明 |
|------|--------|------|------|
| `TestE2ERetrieveBasic` | 1 | skip | 需要 Docker + embedder API key |
| `TestE2EErrorCases` | 4 | skip | 需要 Docker |
| `TestE2EOptimizationIsolation` | 3 | pass | 纯结构验证，无需 DB |

### Skip 原因
E2E conftest 依赖 Docker Compose 启动的 test-db (port 5433)，当前环境无 Docker，因此数据库相关测试全部 skip。三个无数据库依赖的结构测试正常通过。

## 运行结果

```
$ uv run pytest tests/unit/ tests/integration/test_retrieve_full_chain.py -v --ignore=tests/e2e
pytest: 294 passed, 1 warning

$ uv run pytest tests/integration/test_retrieve_full_chain.py tests/unit/adapters/test_http_schema_invariance.py -v
pytest: 35 passed

$ uv run pytest tests/e2e/test_optimizations.py -v
pytest: 3 passed, 5 skipped
```

## 未修改实现代码

所有测试均使用 mock/fake 实现或结构检查，未修改任何 `src/` 下的实现代码。
