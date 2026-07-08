# 多租户鉴权 — 提示词 × 项目现状 融合比对报告

> 日期：2026-07-04
> 状态：探索阶段（/comet-open 前）

---

## 一、总体判断

两份提示词的设计方向与项目现状**高度兼容**，不存在阻塞性冲突。核心设计理念（API Key → Bearer → Depends 注入 → 业务接口透明鉴权）可直接落地。

**关键发现**：
- 3 个冲突点（均可通过小幅调整解决）
- 3 个提示词未覆盖的设计盲区（FK 约束、存量数据迁移、前端 Key 暴露）
- 2 个提示词中与项目实际不符的假设

---

## 二、架构映射

提示词使用传统扁平结构（`app/models/`、`app/api/v1/`），项目使用 Clean Architecture 分层。映射关系：

| 提示词路径 | 项目实际路径 | 说明 |
|---|---|---|
| `app/models/tenant.py` | `src/ragnexus/domain/models.py`（新增 Tenant/ApiKey dataclass） | 领域模型放 domain 层 |
| `app/repositories/tenant_repository.py` | `src/ragnexus/adapters/` 下新增 `tenant/` 包 | 仓库是适配器，放 adapters 层 |
| `app/core/auth.py` | `src/ragnexus/core/auth.py` | 鉴权逻辑放 core 层 |
| `app/core/config.py` | `src/ragnexus/config.py` | 已有 Settings 类，新增字段即可 |
| `app/api/v1/deps.py` | `src/ragnexus/adapters/http/deps.py` | Depends 是 HTTP 适配器层的横切关注点 |
| `app/api/v1/router.py` | `src/ragnexus/adapters/http/auth_router.py`（新建） | 按项目惯例，每个端点一个独立 Router 工厂 |
| `scripts/create_tenant.py` | 项目根目录 `scripts/` | 一致 |
| 迁移 `versions/0002_xxx.py` | 应命名为 `0003_` | 项目已有 0002_add_tenant_id |

---

## 三、冲突点（3 个，均已给出推荐方案）

### 冲突 1：错误码 — 20010 vs 10200

| | 提示词 | 项目现状 |
|---|---|---|
| UNAUTHORIZED | code=20010 | code=10200（已在认证区间 10200-10299） |
| HTTP 状态码 | 200（body code 标识错误） | 401（标准 HTTP） |

**分析**：项目错误码体系有明确的区间分类（10200-10299 = 认证与鉴权），且有 3 个现有成员。20000 区间属于"接口与 HTTP"，不适合放鉴权错误码。

**推荐**：沿用现有 `ErrorCode.UNAUTHORIZED = 10200`，不改动。提示词中"HTTP 200 + body code"的模式需要单独讨论——这涉及全局错误处理器的行为变更（当前 `error_handlers.py` 可能将 AppError.http_status 映射到 HTTP 响应码），影响面超出鉴权本身。

> **决策点**：鉴权失败时 HTTP 状态码是 401 还是 200？如果是 200，需要改全局 error_handler，影响所有 AppError。

**暂定方案**：保持现有行为（HTTP 401 + body code 10200），与提示词目标的差异仅在于 HTTP 状态码不同，功能语义等价。

### 冲突 2：路由命名风格

| 提示词 | 项目实际 |
|---|---|
| `POST /rag/retrieve` | `POST /v1/rag:retrieve`（Google AIP `:action` 风格） |
| `GET /knowledge-bases/tree` | `GET /v1/knowledge-bases/tree` |

**推荐**：沿用项目现有风格（`:action` + `/v1` 前缀），包括 `/v1/auth/me`。

### 冲突 3：upload 接口「去掉 tenant_id」

提示词说 upload 接口要"去掉 body tenant_id"。**项目 upload 接口目前就不传 tenant_id**（只传 `kb_id: Form(...)` + `file: UploadFile`）。

**结论**：这个改动对项目是 **no-op**，无需任何代码修改。

---

## 四、后端 — 第一阶段（搭地基）逐项比对

| # | 提示词目标 | 项目现状 | 差异 | 对齐方式 |
|---|---|---|---|---|
| 1 | 新建 `tenants` 表 | 无 | 全新 | 0003 迁移建表 |
| 2 | 新建 `api_keys` 表 | 无 | 全新 | 同上迁移 |
| 3 | Key 格式 `rk_live_<32位hex>` | 无 | 全新 | 直接实现 |
| 4 | SHA-256 hash 存储 | 无 | 全新 | 直接实现 |
| 5 | Alembic 迁移 | 已有 0001、0002 | 编号冲突 | 用 0003，风格对齐 0001 |
| 6 | Tenant/ApiKey Model | domain/models.py 已有 dataclass 风格 | 需新增 | 新增两个 dataclass |
| 7 | TenantRepository + ApiKeyRepository | adapters/ 下尚无 tenant 包 | 全新 | 新建 adapters/tenant/ |
| 8 | `core/auth.py` + `deps.py` | 无 | 全新 | 新建 |
| 9 | `TenantContext` dataclass | 无 | 全新 | 放 domain/models.py 或 core/auth.py |
| 10 | `AUTH_ENABLED` 配置 | config.py 无此字段 | 新增 | Settings 加 `AUTH_ENABLED: bool = True` |
| 11 | `GET /v1/auth/me` | 无 | 全新 | 新建 `adapters/http/auth_router.py` |
| 12 | 运维脚本 | 无 scripts/ 目录 | 全新 | 新建 scripts/create_tenant.py + create_api_key.py |
| 13 | composition.py DI 装配 | 无 auth 依赖 | 需扩展 | lifespan 中创建 TenantRepository 等，注入 auth_router |

### 配置项细节

`config.py` 新增字段：

```python
# Auth
AUTH_ENABLED: bool = True
```

`.env.example` 补充：

```
AUTH_ENABLED=true
```

**注意**：提示词中 `AUTH_ENABLED=false` 时固定使用 `tenant_demo`。如果 `tenant_demo` 不存在于 tenants 表，也需要"占位通过"。这意味着 `get_current_tenant` 在 AUTH_ENABLED=false 时需要构造一个假的 TenantContext，不查数据库。

---

## 五、后端 — 第二阶段（挂到业务接口）逐项比对

| # | 接口 | 提示词目标 | 项目现状 | 差异 |
|---|---|---|---|---|
| 1 | `POST /v1/knowledge-bases:create` | 去掉 body tenant_id，Key 注入 | body 有 `tenant_id: Field(...)` 必填 | 改 Schema + 改 UseCase 调用 |
| 2 | `GET /v1/knowledge-bases/tree` | 只返回当前租户 | 返回全量，keyword 模糊匹配 tenant_id | 改 UseCase 签名 + repo 查询 |
| 3 | `POST /v1/documents:upload` | 去掉 body tenant_id | **本来就没有** | 无改动 |
| 4 | `POST /v1/rag:retrieve` | 去掉 body tenant_id | **本来就没有**（只传 kb_ids） | 无改动（但需确认：用 Key A 调 Key B 的 kb_id 是否拒绝？） |

### tree 接口改动的连锁影响

提示词要求 tree 只返回当前租户。这意味着：

1. **UseCase 签名变化**：`execute(keyword)` → `execute(tenant_id, keyword)`
2. **keyword 语义变化**：从"模糊匹配 tenant_id"变为"模糊匹配知识库名称"（在租户范围内）
3. **repo 查询变化**：`WHERE kb.tenant_id ILIKE keyword` → `WHERE kb.tenant_id = $1 AND kb.name ILIKE $2`
4. **前端适配**：三级树→两级树，前端 flatMap 去重（提示词二已规划）

### retrieve 接口的隐式隔离

当前 retrieve 通过 kb_ids 间接关联租户（chunks→documents→knowledge_bases→tenant_id）。加上鉴权后，如果用户传了其他租户的 kb_id：

- **方案 A**：检索前校验 kb_ids 是否属于当前租户，不属于则拒绝
- **方案 B**：检索后过滤（但 chunks 表没有 tenant_id，过滤成本高）

**推荐方案 A**：在 RetrieveUseCase 执行前加 `validate_kb_ids_belong_to_tenant(kb_ids, tenant_id)` 校验。

### Schema 变化的细节

| Request | 当前字段 | 提示词目标 |
|---|---|---|
| `_CreateKBRequest` | `name`, `tenant_id`（必填） | 只留 `name`, `description` |
| `_RetrieveRequest` | `query`, `kb_ids`, `top_k`, `mode`, `vector_top_k`, `bm25_top_k`, `rrf_k`, `rerank` | 不变（本来就没有 tenant_id） |
| upload（Form） | `kb_id`, `file` | 不变（本来就没有 tenant_id） |

**注意**：提示词说"body 多传 tenant_id 时由 Pydantic 忽略"。当前 `_CreateKBRequest` 配置了 `extra = "forbid"`，多传会报 422。去掉 tenant_id 字段后不需要改这个配置——只是响应 body 里不再接收 tenant_id，响应仍可回显。

---

## 六、前端 — 逐项比对

| # | 提示词目标 | 项目现状 | 差异 |
|---|---|---|---|
| 1 | http.ts 请求拦截器自动带 Bearer | 无拦截器 | 全新 |
| 2 | 响应 code=20010 时错误提示 | 无拦截器 | 全新（错误码用 10200） |
| 3 | 上传页去掉 tenant_id 输入 | 有 tenant_id 输入框 | 删 UI + 改逻辑 |
| 4 | 列表页三级→两级 | 三级树（租户→KB→文档） | 改数据映射 |
| 5 | 列表页标题展示当前租户 badge | 无 | 新增 |
| 6 | 列表页搜索改为按 KB 名 | 按 tenant_id 搜索 | 改搜索逻辑 |
| 7 | 跳转 URL 只带 kb_id | 带 tenant_id | 改链接生成 |
| 8 | 检索页去掉 tenant_id 输入 | 有租户下拉筛选 | 删 UI |
| 9 | 检索页 HelpTooltip | 无 | 新增公共组件 |
| 10 | types 三个 Request 去掉 tenant_id | 三个类型有 tenant_id | 删字段 |
| 11 | 新增 authService.ts + AuthMeData | 无 | 新增 |
| 12 | .env.example + envPrefix | 无 | 新增 |
| 13 | .env gitignore | 无 | 确认 .gitignore |

### 前端隐式冲突

| 问题 | 说明 |
|---|---|
| upload 页当前从 tree 提取 tenant_id | `loadKBs()` 从 tree 数据里读 `item.tenant_id` 构造 KBOption。tree 改两级后，KB 数据不再嵌套在 tenant 下，需要调整数据提取路径 |
| list 页的组件 key 用了 tenant_id | 三级树渲染时 `key={item.tenant_id}`，改两级后不再需要 |
| retrieve 页按 tenant_id 过滤 KB 列表 | `filteredKbs = kbs.filter(kb => !tenantId || kb.tenant_id === tenantId)`，改两级后去掉 |

---

## 七、提示词未覆盖的设计盲区

### 盲区 1：`knowledge_bases.tenant_id` 是否需要 FK 约束？

**现状**：`knowledge_bases.tenant_id` 是 `TEXT NOT NULL DEFAULT 'default'`，无 FK。

**风险**：如果 tenants 表建了但 knowledge_bases 不做 FK，删除租户后其 KB 变成孤立数据。检索、上传、tree 仍能通过 kb_id 访问到这些 KB（因为没有租户级校验），形成"逻辑删除但数据残留"的半隔离状态。

**推荐**：迁移中加 FK：
```sql
ALTER TABLE knowledge_bases
  ADD CONSTRAINT fk_kb_tenant
  FOREIGN KEY (tenant_id) REFERENCES tenants(id)
  ON DELETE RESTRICT;  -- 有 KB 的租户不允许删除，避免孤立数据
```

**代价**：存量数据需要先迁移（见盲区 2）。

### 盲区 2：存量数据迁移路径

**现状**：knowledge_bases.tenant_id 可能有以下值：
- `'default'`（0002 迁移的默认值）
- 用户手动输入的任意字符串

**问题**：切换到 Key 派生 tenant_id 后，这些存量 tenant_id 和 tenants 表中的 id 不匹配。

**推荐方案**：
1. 迁移 0003 先建 `tenants` 表
2. 插入一条 `tenants(id='default', name='默认租户（迁移）', status='active')`
3. 然后加 FK 约束（存量 KB 的 `tenant_id='default'` 匹配到该租户）
4. 如果用户手动创建了其他 tenant_id，需要运维脚本扫描 `SELECT DISTINCT tenant_id FROM knowledge_bases`，逐个插入 tenants 表

**AUTH_ENABLED=false 的占位行为**：提示词说用 `tenant_demo`，但存量数据是 `'default'`。建议统一：AUTH_ENABLED=false 时占位租户也用 `'default'`，与存量一致。如果建了 `tenant_demo` 租户且开启了 AUTH_ENABLED，API Key 绑定 `tenant_demo`，存量 `'default'` 数据不可见——这是预期行为。

### 盲区 3：前端 `API_KEY` 在 Vite build 中暴露

**现状分析**：
- `import.meta.env.API_KEY` 会被 Vite 在构建时**内联进 JS bundle**
- 任何拿到前端静态资源的人都能看到 API Key 明文
- 与提示词"Key 只在创建时终端打印一次"的设计**隐含矛盾**

**风险评估**：
- 对**内部管理 SPA**（本项目的使用场景）：可接受。前端部署在内网，Key 泄露面可控
- 对外提供能力的 RAG 中台：不可接受。应拆成两层认证

**推荐**：分两期处理
- **本期**：接受当前方案，但报告中标注此风险。在前端 README 中注明"API_KEY 会被打包进前端 JS，仅适用于内网部署"
- **下期**：引入 session token 机制（后端签发短期 JWT，前端用 API Key 换 token）

---

## 八、推荐执行顺序

```
Phase 1: 后端地基（迁移 + Model + Repo + Auth 核心 + 脚本 + /auth/me）
  ├── 0003 迁移：tenants + api_keys + FK 约束 + 存量 tenant_id 迁移
  ├── domain/models.py：新增 Tenant, ApiKey dataclass
  ├── adapters/tenant/：PgTenantRepository + PgApiKeyRepository
  ├── core/auth.py：TenantContext + get_current_tenant + hash/verify
  ├── adapters/http/auth_router.py：GET /v1/auth/me
  ├── adapters/http/deps.py：get_current_tenant Depends
  ├── config.py：AUTH_ENABLED
  ├── scripts/create_tenant.py + create_api_key.py
  └── composition.py：装配 auth 依赖

Phase 2: 后端接入（四个业务接口挂鉴权）
  ├── create_kb_router：去掉 tenant_id，Depends(get_current_tenant)
  ├── kb_tree_router：tenant_id 过滤 + keyword 语义改为按 KB 名搜
  ├── retrieve_router：kb_ids 归属校验
  └── upload_doc_router：无改动（本来就不传 tenant_id）

Phase 3: 前端适配
  ├── http.ts 拦截器（Bearer + 10200 错误提示）
  ├── 三个页面去 tenant_id + 两级树 + tenant badge
  ├── types/services 更新
  └── .env.example + envPrefix
```

---

## 九、待决策事项

| # | 决策点 | 选项 | 推荐 |
|---|---|---|---|
| D1 | 鉴权失败 HTTP 状态码 | A) 401（现有行为） B) 200（提示词方案） | A（改动最小） |
| D2 | knowledge_bases.tenant_id FK | A) 加 FK RESTRICT B) 不加 FK C) 加 FK CASCADE | A（防孤立数据） |
| D3 | AUTH_ENABLED=false 占位租户 | A) `tenant_demo` B) `default`（与存量一致） | B |
| D4 | retrieve 接口其他租户 kb_id 行为 | A) 前端拒绝（校验归属） B) 静默过滤 | A（明确报错） |
| D5 | 前端 API_KEY 暴露风险 | A) 本期接受 B) 本期拆两层认证 | A（内网场景可接受，标注风险） |
| D6 | 提示词中"去掉 tenant_id 的 upload" | 已是 no-op，是否需要在 tasks 中标注？ | 标注"验证通过，无需改动" |
