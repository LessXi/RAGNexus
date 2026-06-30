# Task 2.1 报告：新增 RerankPort Protocol

**状态**: ✅ 完成  
**日期**: 2026-06-28  
**分支**: feature/20260628/llm-rerank-and-rewrite  
**Commit**: 54e284a

## 任务背景
在 `domain/ports.py` 新增 RerankPort Protocol — LLM 重排的接口契约，供后续 Task 3 的 LLMRerankProvider / NoopRerankProvider 实现。

## TDD 流程

### RED 阶段
- 创建 `tests/unit/domain/test_rerank_port.py`，包含 4 个测试
- 运行失败：`ImportError: cannot import name 'RerankPort'` —— 符合预期

### GREEN 阶段
- 在 `src/ragnexus/domain/ports.py` 末尾（RetrieveLogPort 之后）新增 RerankPort
- 运行 4 个测试全部通过，ruff 零告警

### 关键决策
- **去掉 `isinstance(instance, RerankPort)` 断言**：Python `Protocol` 默认不支持 runtime `isinstance`（需 `@runtime_checkable`），而现有 5 个 Port 均未使用该装饰器。改为通过 `inspect.signature` 静态检查签名 + 实际调用验证行为正确性，与项目风格一致。
- **不入肉实现**：仅定义 Protocol 签名，LLMRerankProvider / NoopRerankProvider 留给 Task 3。

## 测试统计
| 测试 | 结果 |
|------|------|
| `test_rerank_port_is_protocol` | ✅ |
| `test_rerank_method_signature` | ✅ |
| `test_clear_cache_method_signature` | ✅ |
| `test_minimal_implementation_satisfies_protocol` | ✅ |
| **domain 全量 (18 tests)** | ✅ |
| **ruff check** | OK |

## 文件变更
| 文件 | 操作 | 行数 |
|------|------|------|
| `src/ragnexus/domain/ports.py` | 新增 RerankPort (lines 59-81) | +23 |
| `tests/unit/domain/test_rerank_port.py` | 新建测试文件 | +124 |
