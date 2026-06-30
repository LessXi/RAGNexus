# Task 5.2 报告：创建 NoopRewriteProvider 直通实现

**状态**: ✅ 完成  
**日期**: 2026-06-28  
**分支**: feature/20260628/llm-rerank-and-rewrite  
**Commit**: 5e27ce6

## 任务背景
创建 `NoopRewriteProvider` —— 禁用查询改写时的直通实现。满足 `RewritePort` Protocol，`rewrite()` 返回原始 query（identity pass-through），`clear_cache()` 空实现。

## TDD 流程

### RED 阶段
- 创建 `tests/unit/test_noop_rewrite.py`，包含 5 个测试：
  1. `test_provider_exists` — 模块可导入
  2. `test_satisfies_rewrite_port_protocol` — 方法签名 + 返回类型验证
  3. `test_rewrite_returns_identity_no_modification` — identity 直通行为
  4. `test_rewrite_custom_query_identity` — 不同 query 的身份保持
  5. `test_clear_cache_is_noop` — 空实现不抛异常
- 运行 5/5 失败：`ModuleNotFoundError: No module named 'ragnexus.adapters.rewrite'` —— 符合预期

### GREEN 阶段
- 创建 `src/ragnexus/adapters/rewrite/__init__.py` — 包入口，导出 `NoopRewriteProvider`
- 创建 `src/ragnexus/adapters/rewrite/noop.py` — 包含 `NoopRewriteProvider` 类：
  - `rewrite()`: 返回 `RewriteResult(original_query=query, rewritten_query=query, needs_rewrite=False, reason="禁用改写，直通")`
  - `clear_cache()`: 空实现（`pass`）
- 运行 5/5 通过，全量 unit 232/236 通过（4 个预存在的 `composition.py: UploadResult` 失败，与本次变动无关）

### 关键决策
- **完全参考 NoopRerankProvider 模式**：类结构、方法签名、docstring 风格一致
- **中文 docstring**：模块/类/方法统一中文注释，与项目惯例一致
- **keyword-only 参数**：`rewrite(*, query, kb_ids)` 与 RewritePort Protocol 签名严格匹配

## 测试统计
| 测试 | 结果 |
|------|------|
| `test_provider_exists` | ✅ |
| `test_satisfies_rewrite_port_protocol` | ✅ |
| `test_rewrite_returns_identity_no_modification` | ✅ |
| `test_rewrite_custom_query_identity` | ✅ |
| `test_clear_cache_is_noop` | ✅ |

## 文件变更
| 文件 | 操作 | 行数 |
|------|------|------|
| `src/ragnexus/adapters/rewrite/__init__.py` | 新建 | +5 |
| `src/ragnexus/adapters/rewrite/noop.py` | 新建 | +36 |
| `tests/unit/test_noop_rewrite.py` | 新建 | +111 |
