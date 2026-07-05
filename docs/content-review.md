# 对抗性内容评审

逐文档找逻辑漏洞、缺失细节和矛盾。不搞形式化 checklist。

---

## design.md (Superpowers Design Doc)

### 🔴1. `rrf_fuse` 改造方案有漏洞

设计写的 `_merge_metadata` 合并逻辑是对的，但**当前 `rrf_fuse` 代码结构不支持**：

```python
# 当前代码：同一个 chunk_id 只在 chunk_map 中存一次（先到先得）
for rank, hit in enumerate(vector_hits, start=1):
    chunk_map[chunk_id] = hit  # 向量优先

for rank, hit in enumerate(kw_hits, start=1):
    if chunk_id in rrf_scores:
        rrf_scores[chunk_id] += contrib
    else:
        chunk_map[chunk_id] = hit  # 仅当向量没有时才存
```

共享 chunk（两路都有）时，`chunk_map[cid]` 指向**向量来源的 hit**，`_bm25_score` 根本不存在于该 hit 的 metadata 中——因为 BM25 分数只标记在 `kw_hits` 上，而 `kw_hits` 的 metadata 没有被引用。

**正确做法**：需要预先建一个 `kw_meta_map: dict[str, dict]`，在构造新 SearchHit 时合并。设计里写了合并逻辑但没指出 rrf_fuse 的当前控制流不支持。

### 🔴2. `latency_ms` 计算时机错误

当前 RetrieveUseCase 用 `finally` 块计算 `latency_ms`：

```python
try:
    ...
    return hits          # ← 这里已经返回了
finally:
    latency_ms = ...     # ← finally 在 return 之后才执行
```

`RetrieveResult` 需要 `latency_ms`，但它在 `return` 之后才计算。**必须把计时移到 try 块 return 之前**，否则 `RetrieveResult.latency_ms` 永远是旧值或未定义。

### 🟡3. `rerank_model` 来源未指定

`RetrieveResult.rerank_model` 需要返回模型名（如 `"deepseek-chat"`），但设计没说明从哪里取。现有代码中 `RetrieveUseCase` 不持有模型名——只有 `LLMRerankProvider` 内部有 `self.llm`。

需要让 `LLMRerankProvider` 暴露 `model_name` 属性，或通过 `composition.py` 注入。目前完全缺失这条路。

### 🟡4. `_serialize_hit` 与 api-spec 矛盾

设计写 `meta.pop("filename", "")` → 把 `filename` 从 metadata 中**删除**，只留在 `title` 字段。但 `docs/api-spec.md` 的响应示例里，`metadata` 仍然包含 `"filename": "backend_engineer.md"`。

两者矛盾。要么改 `pop` 为 `get`（保留在 metadata），要么改 api-spec。

### 🟡5. migration 约束名是假设值

```sql
ALTER TABLE knowledge_bases DROP CONSTRAINT knowledge_bases_name_key_key;
```

PostgreSQL 的约束名可能与 Alembic 生成的不同。正确做法是先查询实际约束名：

```sql
SELECT conname FROM pg_constraint WHERE conrelid='knowledge_bases'::regclass AND contype='u';
```

---

## api-spec.md

### 🟡6. Tree API 响应不含 `total` 或 `count`

列表页需要显示「共 N 个租户」。当前响应只有数组，调用方需自己数。建议顶层加 `total_tenants` 或前端自己算——不是 bug，但与其他 API 的 `total` 不一致。

### 🟡7. 文档层没有 `chunk_count` 

文档层响应有 `chunk_count`，但 `documents` 表有 `chunk_count` 列——这是上传时写入的。确认 JOIN 时直接用这个列，不需要 COUNT(chunks)。

---

## acceptance-criteria.md

### 🟡8. AC2.9 是死条目

「文档仅 SUCCESS」标注为「无需实现过滤」。但既然确定不加 status 列，这个 AC 应该删除或改为「文档层返回所有文档（同步模式全 SUCCESS）」——否则 implementer 会困惑。

### 🟡9. E2E.6 URL 传参不对

`/retrieve?tenant_id=tech_position&kb_id=xxx`——但 RetrievePage 实际需要的是 KB 选择下拉。Tree API 返回 `tenant_id` → `kb_id` 的映射。前端需从 URL 参数反查 KB 名并选中。验收标准没说明这个映射逻辑由谁负责（前端还是新 API）。

---

## tasks.md

### 🟡10. 错误处理任务缺失

所有任务只覆盖正常路径。没有：
- network error 时的前端展示（retry、toast）
- API 返回 5xx 时的降级
- Tree API 返回空数据时的空状态
- `rrf_fuse` 改造后旧测试失败时的修复路径

建议在 §9 加一个 `9.5 错误路径验证`。

### 🟡11. §2 缺少「计时重构」任务

任务 2.4 说 `execute()` 签名扩展，2.5 说返回值改为 `RetrieveResult`。但中间缺了一步：**把 finally 块中的 latency 计算移到 try 块 return 之前**。不改这一步，`RetrieveResult.latency_ms` 永远是错的。

---

## 汇总：必须修 vs 建议修

| # | 等级 | 问题 | 影响 |
|---|---|---|---|
| 1 | 🔴 | `rrf_fuse` 改造需要预建 `kw_meta_map` | 共享 chunk 丢失 `_bm25_score` |
| 2 | 🔴 | `latency_ms` 计算需移到 return 前 | `RetrieveResult.latency_ms` 永远是旧值 |
| 3 | 🟡 | `rerank_model` 来源缺失 | meta 中 `rerank_model` 始终 null |
| 4 | 🟡 | `_serialize_hit` pop 与 api-spec 矛盾 | 响应 metadata 缺 `filename` |
| 5 | 🟡 | migration 约束名需动态查询 | 在非 Alembic 环境可能失败 |
| 8 | 🟡 | AC2.9 死条目 | 混淆 implementer |
| 10 | 🟡 | 错误处理任务缺失 | 实现时不覆盖边界 |
| 11 | 🟡 | 计时重构任务缺失 | `latency_ms` 错误 |
