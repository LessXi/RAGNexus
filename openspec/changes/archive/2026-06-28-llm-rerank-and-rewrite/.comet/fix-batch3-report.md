# 批次3审查修复报告：NoopRerankProvider 按 top_n 截断

## 概述
修复 review-batch3 发现的缺陷：`NoopRerankProvider.rerank` 应返回 `chunks[:top_n]` 而非 `chunks`。

## 变更内容

### src/ragnexus/adapters/rerank/noop.py
- `return chunks` → `return chunks[:top_n]`
- 类级 docstring：`"不排序、不截断"` → `"不排序，按 top_n 截断"`
- 方法 docstring：`"不做任何重排"` → `"（不排序，按 top_n 截断），不做重排"`

### tests/unit/test_noop_rerank.py
- `test_rerank_returns_same_chunks_no_modification`：
  - docstring 更新为 `"不排序，按 top_n 截断"`
  - 断言 `len(result) == 2`（top_n=2，3个chunks）
  - 移除 `result is chunks` 断言，改为 `result is not chunks`（切片创建新列表）
  - 移除对 index 2 的断言
- `test_rerank_ignores_top_n` → `test_rerank_truncates_to_top_n`：
  - 重命名测试
  - docstring 改为 `"top_n < len(chunks) 时应截断到 top_n"`
  - 断言 `len(result) == 2`（原为 `== 5`）

## 测试结果
```
6 passed in 0.26s
```

## 提交
```
5067aba fix(rerank): NoopRerankProvider 按 top_n 截断
```
