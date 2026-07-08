# RAGNexus 租户套餐接入指南

本文档面向接入方，说明 RAGNexus 多租户的套餐体系、Profile 配置、错误码、运维脚本及升级路径。

---

## 1. 套餐（Plan）对照表

RAGNexus 提供三档套餐：`free` / `standard` / `pro`，每档控制**功能开关**和**用量配额**。

| 维度 | Free | Standard | Pro |
|------|------|----------|-----|
| **允许的 Profile** | `speed` | `speed`, `balanced`, `custom` | `speed`, `balanced`, `quality`, `custom` |
| **Hybrid 混合检索** | ❌ | ✅ | ✅ |
| **Rerank 重排序** | ❌ | ❌ | ✅ |
| **Query Rewrite 查询改写** | ❌ | ❌ | ✅ |
| **检索 QPS** | 3 | 10 | 50 |
| **检索日配额** | 500 | 5,000 | 100,000 |
| **最大知识库数** | 1 | 5 | 50 |
| **单次检索最大 KB 数** | 1 | 3 | 5 |
| **每 KB 最大文档数** | 30 | 200 | 5,000 |
| **并发处理文档数** | 1 | 2 | 10 |

> **单次检索最大 KB 数**（`max_kb_per_retrieve`）：控制一次检索请求可同时查询的知识库数量上限。  
> Free 仅支持单库检索（1 个 KB）；Standard 最多 3 个；Pro 最多 5 个。超限返回 `FEATURE_NOT_ALLOWED`（20013）。  
> 套餐预设定义在 `src/ragnexus/tenant/plan_presets.py`，纯数据字典，零依赖，可直接查阅。

---

## 2. 检索 Profile 说明

Profile 是检索行为的一键预设，控制检索模式、返回数量、重排和查询改写。

| Profile | 模式 | Top-K | Rerank | 查询改写 | 适用套餐 |
|---------|------|-------|--------|----------|----------|
| **speed** | vector | 3 | 关闭 | 关闭 | free / standard / pro |
| **balanced** | hybrid | 5 | 关闭 | 关闭 | standard / pro |
| **quality** | hybrid | 8 | 开启 (top_n=5) | 开启 (rewrite) | pro |
| **custom** | 由请求参数决定 | — | — | — | standard / pro |

- `speed` — 仅向量检索，最快速度，适合低延迟场景
- `balanced` — 向量 + BM25 混合检索，兼顾精度与速度
- `quality` — 混合检索 + 重排 + 查询改写，最高精度
- `custom` — 请求体显式指定 `mode` / `top_k` / `rerank` 等参数，灵活度最高

> Profile 预设定义在 `src/ragnexus/tenant/retrieve_presets.py`，不含 `custom`（由请求参数动态决定）。

---

## 3. 错误码速查

多租户功能相关的三个关键错误码：

| Code | HTTP | 枚举名 | 说明 | 触发场景 |
|------|------|--------|------|----------|
| **20005** | 429 | `API_RATE_LIMIT` | 接口调用超限 | QPS 超过当前套餐上限 |
| **20013** | 403 | `FEATURE_NOT_ALLOWED` | 当前套餐不支持此功能 | free 套餐使用 hybrid/rerank/query_rewrite；standard 套餐使用 rerank/query_rewrite |
| **20014** | 429 | `QUOTA_EXCEEDED` | 配额超限 | 日检索量超过套餐日配额 |

统一的错误响应格式：

```json
{
  "code": 20013,
  "data": null,
  "message": "当前套餐不支持此功能",
  "errors": []
}
```

完整错误码表见 [README.md](../README.md#错误响应格式)。

---

## 4. curl 调用示例

以下示例假设服务运行在 `http://localhost:8000`，使用 Pro 租户的 API Key。

### 4.1 检索成功（200）

```bash
curl -X POST http://localhost:8000/api/v1/rag/retrieve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer rk_live_YOUR_KEY" \
  -d '{
    "query": "Go 后端开发需要什么技能？",
    "kb_ids": ["kb_939a5baf"],
    "top_k": 5
  }'
```

响应：

```json
{
  "code": 0,
  "data": {
    "hits": [
      {
        "chunk_id": "doc_3f2a1b7c:0",
        "score": 0.0821,
        "text": "# Go 后端工程师技能要求\n..."
      }
    ],
    "meta": {"total": 5, "latency_ms": 320, "mode": "hybrid"}
  },
  "message": "ok"
}
```

### 4.2 套餐不支持功能（20013）

Free 租户尝试使用 hybrid 模式：

```bash
curl -X POST http://localhost:8000/api/v1/rag/retrieve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer rk_live_FREE_KEY" \
  -d '{
    "query": "测试问题",
    "kb_ids": ["kb_test"],
    "mode": "hybrid"
  }'
```

响应：

```json
{
  "code": 20013,
  "data": null,
  "message": "当前套餐不支持此功能: hybrid 检索",
  "errors": []
}
```

### 4.3 接口调用超限（20005）

Free 租户 QPS 超过 3：

```bash
# 连续快速发送 4 次请求
for i in 1 2 3 4; do
  curl -s -X POST http://localhost:8000/api/v1/rag/retrieve \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer rk_live_FREE_KEY" \
    -d '{"query":"test","kb_ids":["kb_test"]}' &
done
wait
```

第 4 次响应：

```json
{
  "code": 20005,
  "data": null,
  "message": "QPS 超限，当前套餐 free 限制 3 次/秒，请稍后重试",
  "errors": []
}
```

### 4.4 日配额超限（20014）

Free 租户当日检索量超过 500 次：

```json
{
  "code": 20014,
  "data": null,
  "message": "日检索配额超限，当前套餐 free 限制 500 次/天",
  "errors": []
}
```


## 5. 检索反馈

用户可以通过前端五星反馈条对检索结果评分（1-5 分）。

- 反馈数据存储在 Langfuse，通过 trace_id 关联每次检索
- 仅当 `LANGFUSE_ENABLED=true` 时显示反馈条
- API: `POST /v1/rag/feedback`
- 错误码: `20020`（服务不可用）/ `20021`（无权）/ `20022`（评分越界）

---

## 6. 运维脚本

### 5.1 创建租户

```bash
uv run python scripts/create_tenant.py --id my_tenant --name "我的租户"
```

输出：

```
租户创建成功：id=my_tenant, name=我的租户
```

### 5.2 创建 API Key

```bash
uv run python scripts/create_api_key.py --tenant-id my_tenant --name "生产环境"
```

输出：

```
API Key 已创建: rk_live_<64位随机hex字符串>
```

### 5.3 修改租户套餐

```bash
# 升级到 standard
uv run python scripts/update_tenant_plan.py --tenant-id my_tenant --plan standard

# 升级到 pro
uv run python scripts/update_tenant_plan.py --tenant-id my_tenant --plan pro

# 降级到 free
uv run python scripts/update_tenant_plan.py --tenant-id my_tenant --plan free
```

输出：

```
租户 plan 已更新: id=my_tenant plan=standard
```

**自定义数据库连接**（默认连接本地 PostgreSQL）：

```bash
# 通过环境变量指定 DSN
PG_DSN="postgresql://user:pass@prod-host:5432/ragnexus" \
  uv run python scripts/update_tenant_plan.py --tenant-id my_tenant --plan pro
```

**错误处理**：

```
# 租户不存在
错误: 租户 nonexistent 不存在

# 无效套餐
usage: update_tenant_plan.py [-h] --tenant-id TENANT_ID --plan {free,pro,standard}
update_tenant_plan.py: error: argument --plan: invalid choice: 'enterprise' (choose from 'free', 'pro', 'standard')
```

### 5.4 脚本清单

| 脚本 | 用途 |
|------|------|
| `scripts/create_tenant.py` | 注册新租户 |
| `scripts/create_api_key.py` | 为租户生成 API Key |
| `scripts/update_tenant_plan.py` | 修改租户套餐等级 |

---

## 7. 升级路径

### 从 Free 升级到 Standard

```bash
uv run python scripts/update_tenant_plan.py --tenant-id my_tenant --plan standard
```

**即时生效** — 套餐信息存储在 `tenants` 表中，每次请求通过 `resolve_plan()` 实时解析，无需重启服务。

升级后获得的额外能力：

| 能力 | Free | Standard |
|------|------|----------|
| Hybrid 混合检索 | ❌ | ✅ |
| Balanced Profile | ❌ | ✅ |
| Custom Profile | ❌ | ✅ |
| 最大 KB 数 | 1 | 5 |
| 单次检索最大 KB 数 | 1 | 3 |
| 每 KB 文档数 | 30 | 200 |
| 检索 QPS | 3 | 10 |
| 日检索配额 | 500 | 5,000 |
| 并发处理文档 | 1 | 2 |

### 从 Standard 升级到 Pro

```bash
uv run python scripts/update_tenant_plan.py --tenant-id my_tenant --plan pro
```

额外获得：

| 能力 | Standard | Pro |
|------|----------|-----|
| Rerank 重排序 | ❌ | ✅ |
| Query Rewrite 查询改写 | ❌ | ✅ |
| Quality Profile | ❌ | ✅ |
| 最大 KB 数 | 5 | 50 |
| 单次检索最大 KB 数 | 3 | 5 |
| 每 KB 文档数 | 200 | 5,000 |
| 检索 QPS | 10 | 50 |
| 日检索配额 | 5,000 | 100,000 |
| 并发处理文档 | 2 | 10 |

### 降级注意事项

降级操作（如 Pro → Free）**同样即时生效**，但不会删除已有数据（知识库、文档仍保留）。
降级后如果**已有资源超出新套餐限制**（如 Pro 有 50 个 KB 降到 Free 仅允许 1 个），后续创建操作将触发 `QUOTA_EXCEEDED`（20014），需自行清理至配额范围内或重新升级。

### 调试验证

升级后可通过 API 快速验证：

```bash
# 使用 hybrid 模式检索（standard/pro 专属）
curl -X POST http://localhost:8000/api/v1/rag/retrieve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer rk_live_YOUR_KEY" \
  -d '{"query":"hello","kb_ids":["kb_test"],"mode":"hybrid"}'

# free 租户执行同上请求 → 20013 (FEATURE_NOT_ALLOWED)
```
