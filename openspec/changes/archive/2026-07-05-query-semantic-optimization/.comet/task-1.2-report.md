# Task 1.2 报告: RewritePort 签名更新

## 状态: ✅ 完成

## 变更摘要

`src/ragnexus/domain/ports.py` — `RewritePort.rewrite()` 方法签名更新：

| 项目 | 变更前 | 变更后 |
|---|---|---|
| 返回类型 | `RewriteResult`（已删除） | `QueryProcessResult` |
| 新参数 | — | `kb_context: dict \| None = None` |
| keyword-only | `*` 保留 | 不变 |
| `clear_cache` | — | 不变 |

## kb_context 参数说明

传给 LLM 改写器的额外上下文字典，包含 KB 的 `name`、`description`、`settings`（含 `rewrite_hint`）。
改写器将其注入 system prompt 以提升改写质量。

## TDD 验证

- **RED**: AST 确认 `RewriteResult` 被引用但未定义 → 模块 import 失败
- **GREEN**: AST 验证确认:
  - ✅ 返回类型 `QueryProcessResult`
  - ✅ `kb_context: dict | None = None` 为 keyword-only 参数（`*` 之后）
  - ✅ `clear_cache` 方法不变
- **REFACTOR**: 无需重构（改动最小化）

## Commit

```
98dabf8 feat(query): task 1.2 — RewritePort 签名更新
```

## 后续影响

Task 1.2 仅修改端口定义（Protocol）。下游 `LLMRewriteProvider` 和 `NoopRewriteProvider` 的实现签名还引用旧的 `RewriteResult`，将在后续 task 中更新。
