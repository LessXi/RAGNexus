# 实施计划对抗性评审

## 🔴 阻塞问题

### 1. Task 8 依赖图位置错误

依赖图把 Task 8 (首页合并) 放在 Task 9 (列表页) 和 Task 10 (检索页) 之后。但 Task 8 的实际依赖只有：
- Task 7 (AppHeader + 路由) — 页面骨架
- Task 6 (tree API) — KB 下拉数据源

Task 8 不需要等列表页或检索页完成。正确的依赖图：

```
Task 7 (AppHeader) ──┬── Task 8 (首页合并)
                     ├── Task 9 (列表页) ←── Task 6 (tree API)
                     └── Task 10 (检索页) ←── Task 5 (retrieve router)
```

Task 8/9/10 可以三路并行。

### 2. `KnowledgeBase` dataclass 缺 `tenant_id` 字段

Task 2.2 说 `create()` 写入 `tenant_id`，但 `KnowledgeBase` dataclass（`models.py:9`）当前只有 `id, name, created_at`。Task 2 需要在 **models.py** 中先给 `KnowledgeBase` 加 `tenant_id: str` 字段，否则 `RETURNING` 回来的值无处安放。

**但 Task 3 也在改 models.py**（加 `RetrieveResult`），两者冲突。正确做法：models.py 的修改统一在 Task 3 做（`KnowledgeBase.tenant_id` + `RetrieveResult`），Task 2 声明依赖 Task 3。

## 🟡 中等问题

### 3. Task 2 验证命令不准确

验证跑 `test_retrieve.py`，但 Task 2 改的是 create KB 链路。应改为：
```
pytest tests/unit/application/ -k "create" tests/unit/adapters/test_http_schema_invariance.py -v
```

### 4. Tree API dataclass 定义位置歧义

Task 6.1 写 "在 models.py 或 ports.py"。根据项目 Convention：**Domain models → models.py，Protocols → ports.py**。`TenantKBTree` 等响应类型应在 `models.py` 中定义（和 `RetrieveResult` 同一位置）。

### 5. Task 10 缺少 retrieve API service 函数

Task 9.2 提到了 `fetchTree`，但 Task 10 没有对应的 `retrieveQuery()` 或 `ragService.retrieve()` 函数声明。implementer 只知道写页面，不知道 service 层在哪。

### 6. Task 3 与 Task 2 "并行"有前提

Task 3 标注"与 Task 2 并行"，但如果按修正后 Task 2 依赖 Task 3（models.py 的 `KnowledgeBase.tenant_id`），则不能并行。Task 3 必须先完成。

---

## 修正后的依赖图

```
Task 1 (migration)
  ↓
Task 3 (models.py: KnowledgeBase.tenant_id + RetrieveResult + rrf_fuse)
  ↓
Task 2 (create KB tenant_id) ←──→ Task 4 (RetrieveUseCase)
  ↓                                     ↓
Task 6 (tree API)                    Task 5 (retrieve router)
  ↓                                     ↓
  └──────────── Task 7 (AppHeader) ─────┘
                   ↓
         ┌────────┼────────┐
         ↓        ↓        ↓
     Task 8    Task 9    Task 10
    (首页)    (列表)    (检索)
         ↓        ↓        ↓
         └────────┼────────┘
                  ↓
            Task 11 (联调)
```
