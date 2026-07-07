# AGENTS.md — AI Agent 快速操作指南

RAGNexus 项目启动、调试和常见故障排查的一手经验沉淀。本项目面向人类开发者的说明见 [README.md](./README.md)。

## 启动项目（完整链路）

### 最小启动

```bash
docker compose up -d db elasticsearch  # 先起基础设施
docker compose up -d app               # 再起应用（自动触发 init-db）
```

### 判断是否需要重建镜像

**关键规则**：修改了 `src/` 下的任何 Python 代码后，必须重建 Docker 镜像，`docker compose up -d` 不会自动重新构建。

```bash
# 检查镜像是否过期
docker inspect ragnexus-app-1 --format '{{.Created}}'
# 如果时间早于你最近的代码修改时间 → 需要重建

# 重建并重启
docker compose build app
docker compose up -d app
```

### 验证后端路由完整性

```bash
curl -s http://localhost:8000/openapi.json | python3 -c "
import json,sys; d=json.load(sys.stdin)
for p in sorted(d['paths']): print(' ', list(d['paths'][p].keys())[0].upper(), p)
"
```

期望输出 8 个路由：
```
  GET /v1/auth/me
  GET /v1/documents/{doc_id}
  POST /v1/documents/{doc_id}/reindex
  POST /v1/documents:upload
  GET /v1/knowledge-bases/tree
  GET /v1/knowledge-bases/{kb_id}
  POST /v1/knowledge-bases:create
  POST /v1/rag:retrieve
```

如果只有 2 个路由 → Docker 镜像过期，需要 `docker compose build app`。

### Admin 前端

```bash
cd admin && npx vite --host 0.0.0.0
```

- 开发服务器端口 `5173`
- 需先启动后端（Vite proxy 将 `/v1` 转发到 `localhost:8000`）
- `admin/.env` 中的 `API_KEY` 变更后 Vite 会自动热重启

## 常见故障排查

### 前端报 404

**诊断路径**（按顺序排查）：

1. **检查 Docker 镜像是否过期** — 最常见原因
   ```bash
   docker inspect ragnexus-app-1 --format '{{.Created}}'
   ```
   如果早于代码修改时间 → `docker compose build app && docker compose up -d app`

2. **检查后端路由**
   ```bash
   curl -s http://localhost:8000/openapi.json | python3 -c "import json,sys;print(list(json.load(sys.stdin)['paths'].keys()))"
   ```

3. **检查容器日志**
   ```bash
   docker compose logs app --tail 30
   ```
   关注 lifespan 初始化异常（DB 连接、EMBED_DIM 不匹配等）

4. **容器状态**
   ```bash
   docker compose ps
   ```
   所有服务应显示 `healthy` 或 `Up`

### 前端报鉴权错误（401 / code 10200）

1. **确认 admin/.env 存在且 API_KEY 正确**
   ```bash
   cat admin/.env
   ```
   应有 `API_KEY=rk_live_<64hex>`

2. **验证 Key 有效性**
   ```bash
   curl -s http://localhost:8000/v1/auth/me \
     -H "Authorization: Bearer rk_live_<你的key>"
   ```
   返回 `{"tenant_id":"...","tenant_name":"..."}` → Key 有效
   返回 `{"code":10200,"message":"缺少 Authorization 请求头"}` → Key 无效或过期

3. **生成新 Key**
   ```bash
   # 如果租户不存在，先创建
   uv run python scripts/create_tenant.py --id my_tenant --name "我的租户"
   # 生成 Key（仅打印一次，注意保存）
   uv run python scripts/create_api_key.py --tenant-id <租户ID> --name "Admin前端"
   ```
   将输出的 Key 写入 `admin/.env` 的 `API_KEY=` 行

4. **快速跳过鉴权**（仅本地调试）
   在 `.env` 中设置 `AUTH_ENABLED=false`，重启 app 容器

### App 容器频繁重启

```bash
docker compose logs app --tail 50 | grep -i "error\|traceback\|failed"
```

常见原因：
- `PG_DSN` 指向了 `localhost:15432` 而非 Docker 内部地址 `db:5432`（Docker 环境会自动注入正确的 `PG_DSN`）
- `EMBED_API_KEY` 无效导致 embedding 服务初始化失败
- Elasticsearch 未就绪（等待 `elasticsearch:healthy`）

### 数据库连接问题

```bash
# 检查容器内 DB 连接
docker exec ragnexus-db-1 psql -U ragnexus -d ragnexus -c "SELECT count(*) FROM tenants"

# 本地直连（端口 15432）
psql -h localhost -p 15432 -U ragnexus -d ragnexus
```

## 开发工作流

### Python 代码修改后

```
修改代码 → docker compose build app → docker compose up -d app → 验证路由
```

### 前端代码修改后

Vite HMR 自动热更新，无需手动重启。如果改动了 `admin/.env`，Vite 会自动重启。

### 数据库 schema 变更

1. 修改 `docs/sql/schema.sql`
2. 手动重建或创建 Alembic migration
## 关键路径速查

| 文件 | 作用 |
|---|---|
| `.env` | 后端环境变量（PG_DSN, EMBED_API_KEY, LLM_API_KEY, AUTH_ENABLED 等） |
| `admin/.env` | 前端环境变量（API_KEY） |
| `docker-compose.yml` | 服务编排（db, elasticsearch, redis, init-db, app, worker, beat） |
| `Dockerfile` | app 镜像构建，入口 `ragnexus.composition:build_app` |
| `scripts/create_api_key.py` | 生成 API Key |
| `scripts/create_tenant.py` | 创建租户 |
| `scripts/update_tenant_plan.py` | 修改租户套餐 |
| `docs/sql/schema.sql` | 数据库初始化 DDL |
| `docs/tenant-onboarding.md` | 租户套餐接入指南 |
| `src/ragnexus/config.py` | Settings 定义和默认值 |
| `src/ragnexus/composition.py` | DI 容器 + FastAPI 组装 |
| `src/ragnexus/tenant/` | 套餐预设、profile 展开、PlanResolver |
| `src/ragnexus/services/` | RateLimitService (Redis) + QuotaService (DB) |

### 上传文档报 403（code 10201: "知识库不属于当前租户"）

**根因**：`PgKnowledgeBaseRepository.get()` 的 SQL 漏了 `tenant_id` 字段。

```python
# ❌ 旧 SQL — 缺 tenant_id，KnowledgeBase.tenant_id 取默认 ""，
#    永远不等于真实租户 ID → 403 FORBIDDEN
"SELECT id, name, created_at FROM knowledge_bases WHERE id=$1"

# ✅ 修复后
"SELECT id, name, tenant_id, created_at FROM knowledge_bases WHERE id=$1"
```

**为什么单元测试没发现**：
- `test_upload_doc.py` 的 mock `kb_repo.get` 直接返回 `MagicMock(tenant_id="test_tenant")`，绕过真实 `KnowledgeBase` 构造
- `test_kb_repo.py` 的 mock 数据也缺 `tenant_id`，断言从未检查该字段

**为什么 E2E 测试没发现**：
- `TestE2EUploadErrors` 只测了三个错误路径：KB 不存在（404）、格式不支持（415）、文件过大（413）
- 三者都在 `get()` 调用的**前面**就抛异常了——没一个走到 tenant 检查
- 缺少成功上传的 E2E 用例

**预防**：凡是新增 `KnowledgeBase` 字段，同步更新 `pg.py` 所有 SELECT 列表、mock fixture 数据、和 assertion。

### 上传报 502（code 10500: Embedder 失败）

DashScope embedding API (`text-embedding-v3`) 偶尔返回 400。重试即可：

```bash
# 检查 embedding 配置
grep EMBED .env
# 验证 API Key 有效
curl -s https://dashscope.aliyuncs.com/compatible-mode/v1/models \
  -H "Authorization: Bearer $EMBED_API_KEY"
```

### 前端显示"无法连接后端服务"

前端上传队列 (`admin/src/utils/upload-queue.ts`) 在 axios 错误消息匹配 `/network/i` 时显示此消息。
先检查后端是否存活：
```bash
curl -s http://localhost:8000/openapi.json | head -1
docker compose logs app --tail 20
```
注意：`/health` 端点不在 FastAPI 路由中，用 `/openapi.json` 验证。

## 通用开发经验

### asyncpg JSONB 返回字符串

asyncpg 查询 JSONB 列返回 Python `str` 而非 `dict`。使用前必须 `json.loads()`：

```python
# ❌ — asyncpg 返回 str, isinstance 判断永远 False
kb_settings = getattr(primary_kb, "settings", {}) or {}
if isinstance(kb_settings, dict): ...

# ✅
kb_settings_raw = getattr(primary_kb, "settings", {}) or {}
kb_settings = json.loads(kb_settings_raw) if isinstance(kb_settings_raw, str) else kb_settings_raw
```

### Docker 容器无热重载

Dockerfile 的 uvicorn 不带 `--reload`。代码变更必须完整重建：
```bash
docker compose build app && docker compose up -d app
```

### uv editable 安装

删除 `.venv` 后：
```bash
uv sync && uv pip install -e . --no-deps
uv pip show ragnexus | findstr Editable  # 验证
```

### openspec 规范

- delta spec 正文 SHALL 含 `SHALL` 或 `MUST`
- `MODIFIED` 要求目标 header 在主 spec 中已存在；纯新增用 `ADDED`
- 每个 Requirement 至少一个 Scenario
- 归档后 change → `openspec/changes/archive/YYYY-MM-DD-<name>/`

### 错误码速查

| 错误码 | HTTP | 含义 |
|--------|------|------|
| 10200 | 401 | 缺少 Authorization 头 |
| 10201 | 403 | 知识库不属于当前租户 |
| 10500 | 502 | Embedder 失败 |
| 20005 | 429 | API 限流（原 20002） |
| 20013 | 403 | 套餐不支持此功能 |
| 20014 | 429 | 配额超限 |
| 20020 | 503 | 反馈服务不可用 (Langfuse) |
| 20021 | 403 | 反馈无权操作 |
| 20022 | 422 | 反馈评分越界 (1-5) |

## 开发经验（query-semantic-optimization）

### 词表管理

```bash
uv run python scripts/update_kb_settings.py --kb-id kb_xxx --settings-file kb_settings.json
uv run python scripts/update_kb_settings.py --kb-id kb_xxx --merge --settings-file new.json
uv run python scripts/update_kb_settings.py --kb-id kb_xxx --remove-terms 背调 薪酬
```

上传文档后自动触发 LLM 提取术语 → 合并词表（`composition.py` `SynonymSyncUploadUseCase`）。

## 开发经验（tenant-plan-system）

### 架构

```
请求 → TenantContext(plan) → Router 层 profile 展开 → uc.execute()
                                   ↓
                            RateLimitService(Redis QPS+日配额)
                            QuotaService(DB 库数/文档数/并发)
```

核心模块：`tenant/` + `services/`；Plan 通过 `get_by_hash()` JOIN 带回，零额外 DB 查询。

### Redis 限流 Key

```
QPS:    rag:ratelimit:retrieve:{tid}:{unix_sec}     TTL 2s
日配额: rag:quota:retrieve:daily:{tid}:{YYYYMMDD}   TTL 25h
```

日配额仅在检索成功后 INCR，失败/拒绝不计数。

### 前端 profile

中文名: speed→追求速度, balanced→均衡, quality→追求质量, custom→自定义。
置灰: Tab 用 `allowed_profiles`；custom 内 hybrid/rerank/rewrite 按 plan ceiling。
`_FALLBACK_TENANT.plan = "pro"`（AUTH_ENABLED=false）。

### 运维

```bash
uv run python scripts/update_tenant_plan.py --tenant-id <id> --plan <free|standard|pro>
```

接入文档: `docs/tenant-onboarding.md`。

## 开发经验（retrieval-tuning-system）

### 架构

```
请求 → Router (trace + log_id 预生成) → UseCase → LogPort → retrieve_logs
  │                                                    │
  └─ Langfuse (旁路, fire-and-forget)                   └─ FeedbackService (校验归属)
```

### Langfuse 自托管

```bash
docker compose up -d langfuse  # 独立 Postgres + langfuse/langfuse:2
```

**必须配置的环境变量**: `NEXTAUTH_URL`, `NEXTAUTH_SECRET`, `ENCRYPTION_KEY`, **`SALT`**（v2 版本必需，与 ENCRYPTION_KEY 同值即可）。

首次使用需浏览器访问 `http://localhost:3000` 注册账户 → 创建 Org → 创建 Project → 获取 API Keys。

### trace_id + tenant_id 全链路传递

```
Router:  trace = langfuse_client.create_trace()  → trace["id"]
         uc.execute(trace_id=trace["id"], ...)
UseCase: _safe_log(trace_id=trace_id, tenant_id=tenant_id, ...)
LogPort: INSERT INTO retrieve_logs (trace_id, tenant_id, ...)
```

**教训**: 每个环节都必须显式传递，不能依赖默认空值。feedback API 通过 `WHERE log_id=$1 AND tenant_id=$2 AND trace_id=$3` 校验归属，任一字段为空都会导致 20021。

### feedback schema 设计取舍

`FeedbackRequest.score` 的 `ge=1, le=5` 校验有两种实现位置：
- **Pydantic schema 层**: 快速失败，返回 422/10001
- **Service 层**: 返回业务错误码 20022 (FEEDBACK_INVALID_SCORE)

选择 service 层校验（schema 不加 ge/le），确保错误码一致性。Pydantic 拦截会先于 service 生效，使得 20022 永不可达。

### 容器重建

修改 `src/` 下任何 Python 代码后：
```bash
docker compose build app && docker compose up -d app
```

### 数据库迁移

Docker 容器内没有 `alembic` CLI，migration 通过 `init-db` 服务在首次启动时执行。如需手动加列：
```bash
docker exec ragnexus-db-1 psql -U ragnexus -d ragnexus -c "ALTER TABLE ..."
```

### 预置测试失败处理原则

从第一性原理判断测试是否测试了正确的抽象层级：
- **同层修复**: mock 名变了但行为不变 → 更新 mock (如 `delay()` → `apply_async()`)
- **层级错位**: 测试了不该在此层测的行为 → 删除，标注应测的层级 (如双写逻辑在 IndexingService 而非 UploadUseCase)
- **skip 是技术债务**: 必须写清楚原因和待办

### 新增错误码

```python
FEEDBACK_SERVICE_UNAVAILABLE = 20020  # Langfuse 不可用
FEEDBACK_UNAUTHORIZED = 20021         # 租户无权
FEEDBACK_INVALID_SCORE = 20022        # 评分越界 (1-5)
```

### 新增路由

| 方法 | 路径 | 文件 |
|------|------|------|
| POST | /v1/rag/feedback | `adapters/http/feedback_router.py` |
| - | /v1/rag:retrieve (扩展) | `adapters/http/retrieve_router.py` |

### 新增脚本

| 脚本 | 用途 |
|------|------|
| `scripts/export_eval_cases_from_langfuse.py` | 导出低分反馈为 golden set |
| `scripts/run_retrieval_eval.py` | RAGAS 评估 context_precision + context_recall |

### Comet 归档后注意事项

- 归档脚本会 `git add -f` openspec 和 docs/superpowers（这些目录在 .gitignore 中）
- 归档后 change 目录移动到 `openspec/changes/archive/YYYY-MM-DD-<name>/`
- Design doc 和 plan 会被标注 `archived-with` 元数据
- 归档成功后不要对原 change 名运行 guard

## 开发经验（structured-markdown-chunking）

### 架构

```
文档上传 → UploadDocumentUseCase → Celery Worker
                                        ↓
                              IndexingService.execute(doc_id)
                                        ↓ 按扩展名分流
                    .md → structchunk.chunk()     .txt → fixed_size_split()
                              ↓                           ↓
                    chunk_markdown() bridge        chunker fallback
                    · heading_path 映射            · chunk_type="text"
                    · chunk_type 映射              · heading_path=""
                    · table_part 后处理
                              ↓
                    list[dict] → Embedding → Chunk dataclass
                              ↓
                    双写 pgvector + ES → metadata 透传新字段
```

核心模块：`src/ragnexus/infra/structchunk/` (structchunk 库) + `structchunk_bridge.py` (映射层)。

### chunk metadata 新字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `heading_path` | str | 标题层级路径，如 `"平台交易规则 / 退款时效"` |
| `chunk_type` | str | `section` / `table` / `code` / `list` / `text` |
| `table_part` | int | 大表分组序号 (仅表格 chunk) |

保留 `heading` / `heading_level` 向后兼容。

### 配置

```bash
# .env
CHUNK_MAX_CHARS=1500
TABLE_MAX_ROWS_PER_CHUNK=10  # 大表每组最多数据行数
```

### chunk 诊断

```bash
# 查看文档的 chunk 类型分布
docker exec ragnexus-db-1 psql -U ragnexus -d ragnexus -c "
SELECT metadata->>'chunk_type' AS type, count(*)
FROM chunks WHERE document_id = '<doc_id>' GROUP BY 1"

# 查看 heading_path
docker exec ragnexus-db-1 psql -U ragnexus -d ragnexus -c "
SELECT metadata->>'heading_path' AS path,
       metadata->>'chunk_type' AS type,
       LEFT(content, 60)
FROM chunks WHERE document_id = '<doc_id>'
ORDER BY metadata->>'chunk_index'"
```

### 切块策略升级后 reindex

```bash
# 对整个知识库 reindex
uv run python scripts/reindex_knowledge_base.py --kb-id <kb_id>

# 仅 reindex 指定文档
uv run python scripts/reindex_knowledge_base.py --kb-id <kb_id> --document-id <doc_id>
```

- reindex 期间文档暂时不可检索，建议低峰期执行
- 脚本结束后打印 success/failed/skipped 统计
- 单文档 reindex: `POST /v1/documents/{id}/reindex` 现在允许 SUCCESS 状态

### structchunk 集成注意事项

- structchunk 核心文件拷贝到 `src/ragnexus/infra/structchunk/`
- `_models.py` 的 `_default_node_id()` 使用 `os.uname()` (Unix only)，Windows 替换为 `os.environ.get("COMPUTERNAME", ...)`
- 库的 `__init__.py` 使用相对导入 (`from ._models import ...`)，在任意包深度均可工作

## 通用开发经验（补充）

### Pydantic Field(description=...) 不生成验证

`Field(..., description="评分 1~5")` 仅写入 JSON Schema description，**不拦截非法值**。需要实际约束时必须显式添加 `ge=/le=`:

```python
# ❌ — description 只写文档，score=0 也会通过
score: int = Field(..., description="评分 1~5")

# ✅
score: int = Field(..., ge=1, le=5, description="评分 1~5")
```

### Python 参数顺序规则

有默认值的参数之后的所有参数也必须有默认值：

```python
# ❌ SyntaxError: non-default argument follows default argument
def __init__(self, chunker=None, store: VectorStorePort):

# ✅ — required params 在前
def __init__(self, store: VectorStorePort, chunker=None):
```

### OpenSpec MODIFIED 要求精确 header 匹配

归档时 `## MODIFIED Requirements` 下的每个 `### Requirement:` header 必须在主 spec 中存在完全相同的 header。不存在时归档失败。纯新增内容用 `## ADDED Requirements`。

### Windows 上运行 Comet 脚本

嵌入式 `bash` 命令会路由到 WSL，无法解析 Windows 路径。必须使用 Git Bash 完整路径：

```bash
# ❌ — 路由到 WSL，路径 `\\?\C:\Users\...` 无法解析
bash comet-guard.sh ...

# ✅ — 使用 Git Bash 显式路径
"E:\Software\Git\bin\bash.exe" -c 'COMET_ENV="..."; . "$COMET_ENV"; "$COMET_GUARD" ...'
```

同时注意路径分隔符：Git Bash 中使用 `/f/learnAgent/...` 而非 `F:/learnAgent/...`。
