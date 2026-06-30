# Task 5.1 报告：新增 RewritePort Protocol + RewriteResult dataclass

**状态**: ✅ 完成  
**日期**: 2026-06-28  
**分支**: feature/20260628/llm-rerank-and-rewrite  
**Commit**: 62eb920

## 任务背景
在 `domain/ports.py` 新增 RewritePort Protocol + RewriteResult dataclass — LLM 查询改写的接口契约，供后续 Task 5.2 (LLMRewriteProvider) 和 Task 5.3 (NoopRewriteProvider) 实现。

## TDD 流程

### RED 阶段
- 创建 `tests/unit/test_rewrite_port.py`，包含 7 个测试（3 个 RewriteResult + 4 个 RewritePort）
- 运行失败：`ImportError: cannot import name 'RewritePort' from 'ragnexus.domain.ports'` —— 符合预期

### GREEN 阶段
- 在 `src/ragnexus/domain/ports.py` 顶部添加 `from dataclasses import dataclass`
- 在文件末尾（RerankPort 之后）新增 `RewriteResult` dataclass 和 `RewritePort` Protocol
- 运行 7 个测试全部通过，ruff 自动修复 import 顺序后零告警

### 关键决策
- **测试路径选择 `tests/unit/` 而非 `tests/unit/domain/`**：按 assignment 显式要求 `tests/unit/test_rewrite_port.py`，不走 RerankPort 的 `tests/unit/domain/` 惯例。这是有意为之的有意识偏离，不是遗漏。
- **`clear_cache(kb_id: str)` 统一为单 KB 粒度**：与 RerankPort.clear_cache 接口一致，`composition.py` 可按 KB 逐粒度调清缓存。
- **`RewriteResult` 为独立 dataclass**：非 `TypedDict` 或 named tuple，与项目现有风格（dataclass 贯穿 domain models）一致，且利于 pyright 类型检查。
- **不实现 LLMRewriteProvider / NoopRewriteProvider**：仅定义 Protocol 签名 + 数据结构，留给 Task 5.2 / 5.3。

## 测试统计
| 测试 | 结果 |
|------|------|
| `test_rewrite_result_is_dataclass` | ✅ |
| `test_rewrite_result_fields` | ✅ |
| `test_rewrite_result_default_behavior` | ✅ |
| `test_rewrite_port_is_protocol` | ✅ |
| `test_rewrite_method_signature` | ✅ |
| `test_clear_cache_method_signature` | ✅ |
| `test_minimal_implementation_satisfies_protocol` | ✅ |
| **ruff format** | OK |
| **ruff check** | OK |

## 文件变更
| 文件 | 操作 | 行数 |
|------|------|------|
| `src/ragnexus/domain/ports.py` | 新增 dataclass import + RewriteResult (lines 85-92) + RewritePort (lines 95-110) | +28 |
| `tests/unit/test_rewrite_port.py` | 新建测试文件 | +134 |
