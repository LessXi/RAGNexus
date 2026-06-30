# Task 3.1 报告：创建 NoopRerankProvider 直通实现

**状态**: ✅ 完成  
**日期**: 2026-06-28  
**分支**: feature/20260628/llm-rerank-and-rewrite  
**Commit**: 66ac24d

## 任务背景
在 `adapters/rerank/` 下创建 NoopRerankProvider — 禁用重排时的直通实现。满足 `RerankPort` Protocol（Task 2.1 已创建）。

## TDD 流程

### RED 阶段
- 创建 `tests/unit/test_noop_rerank.py`，包含 6 个测试
- 运行失败：`ModuleNotFoundError: No module named 'ragnexus.adapters.rerank'` —— 符合预期

### GREEN 阶段
- 创建 `src/ragnexus/adapters/rerank/__init__.py` — 包入口，导出 `NoopRerankProvider`
- 创建 `src/ragnexus/adapters/rerank/noop.py` — NoopRerankProvider 类：
  - `rerank()` 直接返回原始 chunks（不排序、不截断，忽略 top_n）
  - `clear_cache()` 空实现（pass）
- 运行 6 个测试全部通过

### 关键决策
- **不使用 `issubclass(NoopRerankProvider, RerankPort)`**：`RerankPort` 非 `@runtime_checkable`，会抛 `TypeError`。改为通过 `inspect.signature` 静态检查签名 + 实际调用验证行为正确性，与 `test_rerank_port.py:test_minimal_implementation_satisfies_protocol` 风格一致。
- **不入肉实现**：仅直通行为 — LLMRerankProvider 留给 Task 3.2。

## 测试列表
| 测试 | 结果 |
|------|------|
| `test_provider_exists` | ✅ |
| `test_satisfies_rerank_port_protocol` | ✅ |
| `test_rerank_returns_same_chunks_no_modification` | ✅ |
| `test_rerank_empty_list_returns_empty` | ✅ |
| `test_rerank_ignores_top_n` | ✅ |
| `test_clear_cache_is_noop` | ✅ |
| **unit 全量 (189 tests)** | ✅ |

## 文件变更
| 文件 | 操作 | 行数 |
|------|------|------|
| `src/ragnexus/adapters/rerank/__init__.py` | 新建包入口 | +5 |
| `src/ragnexus/adapters/rerank/noop.py` | 新建 NoopRerankProvider | +28 |
| `tests/unit/test_noop_rerank.py` | 新建测试文件 | +202 |
