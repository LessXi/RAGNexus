# Tasks: 多租户鉴权

> 设计：[design.md](./design.md)
> 提案：[proposal.md](./proposal.md)

## Phase 1: 后端鉴权地基

- [x] 1.1 创建 Alembic 迁移 0003：`tenants` 表 + `api_keys` 表（字段、约束、索引含 `idx_api_keys_tenant ON api_keys(tenant_id)`）
- [x] 1.2 迁移存量数据：扫描 `SELECT DISTINCT tenant_id FROM knowledge_bases WHERE tenant_id IS NOT NULL AND tenant_id != ''`，对不在 tenants 中的逐条 `INSERT INTO tenants`；加 FK 约束 `knowledge_bases.tenant_id → tenants.id ON DELETE RESTRICT`
- [x] 1.3 领域模型：`domain/models.py` 新增 `Tenant`、`ApiKey` dataclass
- [x] 1.4 仓库层：`adapters/tenant/pg.py` 实现 `PgTenantRepository`（create/get/list）和 `PgApiKeyRepository`（create_by_hash/by_hash，by_hash 返回 JOIN tenants 的完整记录）
- [x] 1.5a 鉴权数据层：`core/auth.py` 实现 `TenantContext` dataclass + SHA-256 纯函数 `hash_key(raw_key)` + Bearer 头解析 `extract_token(header)`
- [x] 1.5b 鉴权 Depends：`core/auth.py` 实现 `make_get_current_tenant` 工厂函数——闭包注入 repo+config，校验流程含 Header 缺失→UNAUTHORIZED、Bearer 格式错误→UNAUTHORIZED、Key 不存在/已吊销/已过期→UNAUTHORIZED、租户禁用→UNAUTHORIZED、AUTH_ENABLED=false→占位
- [x] 1.6 HTTP Depends：`adapters/http/deps.py` 重新导出 `make_get_current_tenant`
- [x] 1.7 auth/me 端点：`adapters/http/auth_router.py` 实现 `GET /v1/auth/me`，返回当前 Key 的租户信息
- [x] 1.8 配置：`config.py` 新增 `AUTH_ENABLED: bool = True`，`.env.example` 补充
- [x] 1.9 运维脚本：`scripts/create_tenant.py`（`--id --name`，重复报错使用 RESOURCE_CONFLICT 10301）
- [x] 1.10 运维脚本：`scripts/create_api_key.py`（`--tenant-id --name`，终端打印一次明文 `rk_live_<32hex>`，tenant 不存在报错）
- [x] 1.11 composition.py：lifespan 中创建 TenantRepository/ApiKeyRepository → `make_get_current_tenant` → 传入所有 5 个 router 工厂（auth + 4 个业务 router），业务 router 签名新增 `get_current_tenant` 参数
- [x] 1.12 测试：迁移 up/down 测试 + `get_current_tenant` 单元测试（正常/Header缺失/错误Key/过期Key/已吊销Key/租户禁用/AUTH_ENABLED=false 降级）

## Phase 2: 业务接口鉴权接入

- [x] 2.1 `POST /v1/knowledge-bases:create`：`_CreateKBRequest` 移除 `tenant_id`（`extra="ignore"`），路由工厂加 `get_current_tenant` 参数，`tenant_id` 从 Key 注入
- [x] 2.2 `GET /v1/knowledge-bases/tree`：UseCase 签名加 `tenant_id` 参数，keyword 语义改为「按 KB 名称模糊搜」，repo 查询改为 `WHERE kb.tenant_id = $1 AND kb.name ILIKE $2`，路由工厂加 `get_current_tenant` 参数
- [x] 2.3 `POST /v1/documents:upload`：路由工厂加 `get_current_tenant` 参数；`UploadDocumentUseCase.execute()` 新增 `tenant_id` 参数，入口校验 `kb.tenant_id != tenant_id → FORBIDDEN (10201)`
- [x] 2.4 `POST /v1/rag:retrieve`：路由工厂加 `get_current_tenant` 参数；在 `RetrieveUseCase` 中新增 `validate_kb_ownership(kb_ids, tenant_id)` 方法（实现：先 `set(kb_ids)` 去重，再 `SELECT id FROM knowledge_bases WHERE id = ANY($kb_ids) AND tenant_id = $tenant_id` 对比数量），跨租户 → `FORBIDDEN (10201)`
- [x] 2.5 测试：create KB 鉴权集成测试 + tree 按租户过滤测试 + upload 跨租户拒绝测试 + retrieve 跨租户 kb_id 拒绝测试（含重复 kb_id 去重场景）

## Phase 3: 前端适配

- [x] 3.1 `http.ts` 拦截器：请求拦截器读取 `import.meta.env.API_KEY`（空则跳过）自动设置 `Authorization: Bearer`；响应拦截器（success handler）检查 `code === 10200`；错误拦截器（error handler）检查 `error.response?.status === 401` 且 `data?.code === 10200`，两路径统一提示「API Key 无效或未配置，请检查 admin/.env 中的 API_KEY」
- [x] 3.2 环境变量：`admin/.env.example` 含 `VITE_API_BASE_URL` + `API_KEY`，`vite.config.ts` 加 `envPrefix: ['VITE_', 'API_']`，`vite-env.d.ts` 补充 `ImportMetaEnv`；确认 `admin/.gitignore` 包含 `.env`
- [x] 3.3 类型定义：`types/api.ts` 三个 Request 类型移除 `tenant_id`，新增 `AuthMeData` 接口
- [x] 3.4 服务层：`services/api.ts` 修改 createKB/uploadDoc/retrieve/fetchTree 的 payload 不传 `tenant_id`；新增 `services/authService.ts` 提供 `fetchAuthMe()`
- [x] 3.5 上传页：创建 KB 表单去掉 tenant_id 输入（只留 name/description），上传表单去掉 tenant_id（只留 kb_id+文件），tenant_id 改为 Badge 只读展示
- [x] 3.6 列表页：三级树→两级（取 `data[0].knowledge_bases`），标题右侧展示当前租户 name/id Badge（调 /auth/me），搜索改为按 KB 名称模糊搜，跳转 URL 只带 kb_id
- [x] 3.7 检索页：去掉租户下拉筛选（只留 kb_id 选择），`buildRetrievePayload` 不传 tenant_id，检索参数标签旁新增 HelpTooltip 公共组件
- [x] 3.8 测试：拦截器双路径 10200 提示测试 + 上传页无 tenant_id 输入框测试 + 列表页两级渲染测试 + 检索页 HelpTooltip 渲染测试
- [x] 3.9 README 更新：前端章节补充 API_KEY 配置说明（先用 `scripts/create_api_key.py` 生成 Key，再写入 `admin/.env`）；本地免 Key 调试说明（后端 `AUTH_ENABLED=false` + 前端 `API_KEY` 留空）
