# Task 1.8 Report: 多库改写上下文

## 改动摘要

将 LLM 改写时使用的 `kb_context` 从单库描述（只取 `kb_ids[0]`）改为所有 KB 的描述列表 `kb_contexts`。

## 改动文件

### 生产代码 (5 files)

| 文件 | 改动 |
|------|------|
| `src/ragnexus/application/retrieve_use_case.py` | 替换 `kb_context` 构建逻辑（L111-125）：遍历所有 `kb_ids` 构建 `kb_contexts: list[dict]`，每个元素含 `name` + `description`；传参从 `kb_context=` 改为 `kb_contexts=` |
| `src/ragnexus/adapters/rewrite/pipeline.py` | `process()` 参数 `kb_context: dict` → `kb_contexts: list[dict]` |
| `src/ragnexus/domain/ports.py` | `RewritePort.rewrite()` 签名更新 |
| `src/ragnexus/adapters/rewrite/llm.py` | `LLMRewriteProvider.rewrite()` 改为遍历 `kb_contexts` 列表构建 system prompt（格式：`知识库列表:\n- {name}: {desc}`） |
| `src/ragnexus/adapters/rewrite/noop.py` | 签名同步更新 |
| `src/ragnexus/domain/models.py` | 注释更新 `kb_context` → `kb_contexts` |

### 测试代码 (4 files)

| 文件 | 改动 |
|------|------|
| `tests/unit/application/test_retrieve_use_case.py` | 新增 `test_multi_kb_rewrite_context`；修复 `test_multi_kb_synonyms_merged` 的 `get.side_effect` 调用次数 |
| `tests/unit/application/test_retrieve.py` | 修复 `_passthrough` 签名 + `test_scenario_12_7` 的 `get.side_effect` |
| `tests/unit/application/test_retrieve_hybrid.py` | 修复 `_passthrough` 签名 |
| `tests/unit/test_rewrite_port.py` | 更新所有 `kb_context` 引用为 `kb_contexts` |
| `tests/unit/test_pipeline.py` | 更新所有 `kb_context` 调用为 `kb_contexts` |

## 测试结果

- **新增测试**: `test_multi_kb_rewrite_context` — 验证 2 个 KB 时 `kb_contexts` 为包含正确 `name`/`description` 的列表
- **回归**: 571 passed, 1 failed（`test_search_hit_fields` — 预存问题，Task 1.4 引入的 `kb_name` 字段未更新该 schema 测试）
- **TDD 流程**: RED（确认旧参数名 `kb_context` 导致断言失败）→ GREEN（全部通过）

## 边界处理

- KB 加载失败（`self._kb_repo.get` 返回 `None`）→ 跳过，不阻塞
- 空列表 → 传递空 `[]`，LLM 端 `if kb_contexts:` 检查自然短路

## Commit

```
838619a feat: use multi-KB context list for LLM query rewrite
```
