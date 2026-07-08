# Task 1.1 实施报告

## 状态

**DONE**

## 摘要

`domain/ports.py`：删除 `RewriteResult` dataclass（4 字段），新增 `QueryProcessResult` dataclass（10 字段）。

## Commit

- **hash**: `ed5212c`
- **message**: `feat(query): task 1.1 — RewriteResult → QueryProcessResult`
- **变更**: 1 file changed, 24 insertions(+), 5 deletions(-)

## 变更内容

| 变更 | 详情 |
|------|------|
| 删除 | `RewriteResult` dataclass（原第 135-142 行，4 字段：original_query, rewritten_query, needs_rewrite, reason）|
| 新增 | `QueryProcessResult` dataclass（10 字段），位置同上 |

### QueryProcessResult 字段清单

| 字段 | 类型 | 说明 |
|------|------|------|
| `raw_query` | `str` | 用户原话，全程不变 |
| `effective_query` | `str` | LLM 改写后；未改写时 = raw_query |
| `search_query` | `str` | 追加扩展词后；无扩展时 = effective_query |
| `needs_rewrite` | `bool` | LLM 判断是否需要改写 |
| `strategy` | `str` | "rewrite" \| "noop" |
| `rewrite_latency_ms` | `int` | 改写耗时；未改写时 = 0（哨兵值）|
| `degraded` | `bool` | 改写是否失败降级 |
| `degraded_reason` | `str \| None` | 降级原因 |
| `synonym_applied` | `bool` | 词表是否命中 |
| `synonym_expansions` | `list[str]` | 追加的扩展词列表 |

## 验证方式

由于 `RewritePort.rewrite()` 的返回类型仍为 `RewriteResult`（待 Task 1.2 修改），直接 `import` 会因未定义名称而失败。采用 AST 解析验证：

1. **RED** — `from ragnexus.domain.ports import QueryProcessResult` → `ImportError`，确认类不存在
2. **GREEN** — AST 解析确认：`@dataclass` 装饰器存在、10 字段全部存在、类型注解正确（`str | None`、`list[str]` 等）

## 自审发现

1. **类型注解风格**: `str | None` 使用 PEP 604 联合类型语法，与 brief 要求一致。
2. **docstring 语言**: 字段级 docstring 使用中文，遵循项目规范。
3. **已知未完成**: `RewritePort.rewrite()` 返回类型仍为 `RewriteResult`，模块在此状态下无法直接 `import`。这是 Task 1.2 的职责范围，符合预期。
4. **无副作用**: 仅修改 `ports.py`，未改动测试文件、`__init__.py` 或其他模块。
