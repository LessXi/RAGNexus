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

期望输出 6 个路由：
```
  GET /health
  GET /v1/auth/me
  POST /v1/documents:upload
  GET /v1/knowledge-bases/tree
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
3. `docker compose down -v` 清除数据卷后重建（或手动执行 DDL）

## 关键路径速查

| 文件 | 作用 |
|---|---|
| `.env` | 后端环境变量（PG_DSN, EMBED_API_KEY, LLM_API_KEY, AUTH_ENABLED 等） |
| `admin/.env` | 前端环境变量（API_KEY） |
| `docker-compose.yml` | 服务编排（db, elasticsearch, init-db, app） |
| `Dockerfile` | app 镜像构建，入口 `ragnexus.composition:build_app` |
| `scripts/create_api_key.py` | 生成 API Key |
| `scripts/create_tenant.py` | 创建租户 |
| `docs/sql/schema.sql` | 数据库初始化 DDL |
| `src/ragnexus/config.py` | Settings 定义和默认值 |
| `src/ragnexus/composition.py` | DI 容器 + FastAPI 组装 |

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
curl -s http://localhost:8000/health
docker compose logs app --tail 20
```

## 开发经验（query-semantic-optimization 变更沉淀）

### asyncpg JSONB 返回字符串

asyncpg 查询 JSONB 列返回 Python `str` 而非 `dict`。使用前必须 `json.loads()`：

```python
# ❌ 错误 — asyncpg 返回 str, isinstance 判断失败
kb_settings = getattr(primary_kb, "settings", {}) or {}
if isinstance(kb_settings, dict):  # 永远是 False
    ...

# ✅ 正确
kb_settings_raw = getattr(primary_kb, "settings", {}) or {}
kb_settings = json.loads(kb_settings_raw) if isinstance(kb_settings_raw, str) else kb_settings_raw
```

### Docker 容器无热重载

Dockerfile 的 uvicorn 不带 `--reload`。`docker cp` 复制文件后进程不会自动重载。代码变更必须完整重建：

```bash
docker compose build app && docker compose down app && docker compose up -d app
```

### uv editable 安装

删除 `.venv` 后必须重新 editable 安装，否则 `uv run` 使用编译包而非源码：
```bash
uv sync
uv pip install -e . --no-deps
```

验证：`uv pip show ragnexus | findstr Editable` 应显示项目路径。

### 词表管理

```bash
# 覆盖写入
uv run python scripts/update_kb_settings.py --kb-id kb_xxx --settings-file kb_settings.json
# 增量合并（去重）
uv run python scripts/update_kb_settings.py --kb-id kb_xxx --merge --settings-file new.json
# 删除词组
uv run python scripts/update_kb_settings.py --kb-id kb_xxx --remove-terms 背调 薪酬
```

上传文档后自动触发 LLM 提取术语 → 合并词表。（见 `composition.py` `SynonymSyncUploadUseCase`）

### openspec archive 验证规则

- delta spec 正文必须含 `SHALL` 或 `MUST`
- `MODIFIED` 操作要求主 spec 已存在；新 spec 用 `ADDED`
- proposal requirements 同样需要 SHALL/MUST

## 开发经验（tenant-plan-system 变更沉淀）

### 租户套餐系统架构

```
请求 → TenantContext(plan) → Router 层 profile 展开 → uc.execute()
                                   ↓
                            RateLimitService(Redis QPS+日配额)
                            QuotaService(DB 库数/文档数/并发)
```

核心模块：
- `src/ragnexus/tenant/plan_presets.py` — 三档 PLAN_PRESETS 常量
- `src/ragnexus/tenant/retrieve_presets.py` — 四档 profile 展开规则
- `src/ragnexus/tenant/plan_resolver.py` — PlanContext 纯函数
- `src/ragnexus/services/rate_limit_service.py` — Redis 限流
- `src/ragnexus/services/quota_service.py` — DB 配额

### Plan 通过 JOIN 带回，零额外查询

```python
# adapters/tenant/pg.py — get_by_hash()
SELECT ... t.plan AS tenant_plan
FROM api_keys ak JOIN tenants t ON t.id = ak.tenant_id
```

### Redis 限流 Key 格式

```
QPS:    rag:ratelimit:retrieve:{tid}:{unix_sec}  TTL 2s
日配额: rag:quota:retrieve:daily:{tid}:{YYYYMMDD} TTL 25h
```

日配额仅在检索成功后 INCR，失败/拒绝不计数。

### 新增错误码

| 错误码 | HTTP | 含义 |
|--------|------|------|
| 20005 | 429 | API 限流（从 20002 改来） |
| 20013 | 403 | 套餐不支持此功能 |
| 20014 | 429 | 配额超限 |

### 前端 profile 选择器

检索页 profile Tab 通过 `planInfo.features.allowed_profiles` 控制置灰，custom 模式下 hybrid/rerank/rewrite 按 plan ceiling 单独禁用。
Profile 中文名映射: speed→追求速度, balanced→均衡, quality→追求质量, custom→自定义。

### 运维脚本

```bash
uv run python scripts/update_tenant_plan.py --tenant-id <id> --plan <free|standard|pro>
```

### 接入文档

`docs/tenant-onboarding.md` — Plan 对照表、Profile 说明、错误码表、curl 示例。

### openspec 归档注意

- `MODIFIED` 要求 header 在主 spec 中存在；新增内容用 `ADDED`
- 每个 Requirement 必须至少一个 Scenario
- 归档后 change 移入 `openspec/changes/archive/YYYY-MM-DD-<name>/`
