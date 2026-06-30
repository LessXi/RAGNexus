# Task 4.1-4.2 Report — RetrieveUseCase 注入 RerankPort + 插入 rerank 步骤

**状态**: ✅ 完成  
**日期**: 2026-06-28  
**Commit**: `17986a5`  
**分支**: `feature/20260628/llm-rerank-and-rewrite`

---

## 变更概要

`RetrieveUseCase` 构造器新增 `reranker`/`candidate_multiplier`/`min_candidates` 三个参数，`execute()` 在向量召回后插入重排步骤。

## TDD 流程

### RED 阶段

1. **fixture 更新**: 新增 `mock_reranker = AsyncMock()`，`use_case` fixture 注入 `reranker=mock_reranker`
2. **现有 3 个测试更新**: `test_retrieve_success`、`test_retrieve_logs_biz_event`、`test_retrieve_log_fire_and_forget` 的函数签名添加 `mock_reranker` 参数，`search_by_vector` 断言改用 `candidate_k` 变量
3. **6 个新测试**: 见下方列表
4. **RED 信号**: `uv run pytest tests/unit/application/test_retrieve.py -v` → 6 failed + 10 errors，全部 `TypeError: RetrieveUseCase.__init__() got an unexpected keyword argument 'reranker'`

### GREEN 阶段

修改 `src/ragnexus/application/retrieve_use_case.py`:
- 导入 `RerankPort`
- 构造器新增 `reranker: RerankPort`、`candidate_multiplier: int = 1`、`min_candidates: int = 0`
- `execute()` 提取 `query_vector = vectors[0]`，计算 `candidate_k = max(top_k * self._candidate_multiplier, top_k + self._min_candidates)`，`search_by_vector` 使用 `candidate_k`，插入 `await self._reranker.rerank(…)` 步骤，返回重排结果
- 日志 `finally` 块保持不变（`hit_count` 读取的是重排后 `hits` 长度）

**GREEN 结果**: `uv run pytest tests/unit/application/ -v` → **28 passed** (16 本测试 + 12 其他 application 测试)

---

## 新增测试 (6 个)

| 测试 | 验证点 |
|------|--------|
| `test_candidate_k_uses_multiplier` | `candidate_multiplier=3, min=0, top_k=5` → `search_by_vector` 用 15 |
| `test_candidate_k_uses_min_candidates` | `multiplier=1, min=10, top_k=5` → `search_by_vector` 用 15 |
| `test_candidate_k_takes_max` | `multiplier=2, min=2, top_k=5` → max(10, 7) = 10 |
| `test_rerank_called_with_correct_kwargs` | `reranker.rerank` 用正确的 keyword 参数调用 |
| `test_rerank_result_is_returned` | `execute()` 返回重排后结果而非原始向量召回结果 |
| `test_noop_rerank_integration` | 使用真实 `NoopRerankProvider` 端到端验证 `chunks[:top_n]` 截断 |

---

## 变更文件

| 文件 | 变更 |
|------|------|
| `src/ragnexus/application/retrieve_use_case.py` | 构造器 +3 参数，`execute()` 插入 `candidate_k` 计算 + `rerank` 调用；新增 `RerankPort` 导入 |
| `tests/unit/application/test_retrieve.py` | 新增 `mock_reranker` fixture；更新 3 个现有测试签名+断言；追加 6 个新测试；新增 `NoopRerankProvider` 导入 |

---

## 架构要点

- **candidate_k 公式**: `max(top_k * multiplier, top_k + min_candidates)`
  - 禁用重排时 (`multiplier=1, min=0`) → `candidate_k = top_k`，NoopRerankProvider 直通
  - 启用重排时 (`multiplier=3, min=10`) → `candidate_k` 更大，确保 LLM 有充足候选
- **rerank 调用协议**: `reranker.rerank(query=query, query_vector=query_vector, kb_ids=kb_ids, chunks=hits, top_n=top_k)` — 全部 keyword 参数
- **日志语义变化**: `hit_count` 现在是重排后的结果数（而非原始向量召回数），`BIZ_EVENT` 仍然记录在 `finally` 块中

---

## 踩坑记录

1. **pytest fixture 签名依赖**: fixture 必须在测试函数签名中声明才能注入返回值。`test_retrieve_success` 等 3 个测试在函数签名中遗漏 `mock_reranker`，导致 `AttributeError: 'FixtureFunctionDefinition' object has no attribute 'rerank'`。修复后全绿。

2. **构造器重复赋值**: `SWAP` 范围计算偏差导致 `self._log_port = log_port` 重复，已通过 `DEL` 修复。

---

## 全量回归

- `uv run pytest tests/unit/ -v` → **220 passed, 1 failed, 1 warning**
- 唯一失败: `TestLoggedPoolWiring.test_repo_pool_is_wrapped_with_loggedpool` — Phase 5 known-RED，与本任务无关
- 本任务引入的 16 个测试及 `tests/unit/application/` 下其他 12 个测试全部通过

---

## 禁止项确认

- ✅ 未修改 `composition.py` (Task 4.3)
- ✅ 未修改 `RerankPort` 或 `RerankProvider`
- ✅ 未勾选 `tasks.md`
