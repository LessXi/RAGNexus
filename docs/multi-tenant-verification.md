# 多租户鉴权验收

> 最后验证：2026-07-05 ✅ 20/20 全部通过

## 前置条件

- Docker Desktop 运行中，`docker compose up -d db elasticsearch`
- PostgreSQL `localhost:15432`，Elasticsearch `localhost:9200`
- `.env` 中 `AUTH_ENABLED=true`
- 后端 `uv run python main.py`（端口 8000）
- 前端 `cd admin && npx vite --port 5173 --host 0.0.0.0`

---

## 一、后端基础设施

### 1.1 数据库迁移

```bash
uv run alembic upgrade head
```

**预期**：`tenants`、`api_keys` 两张表创建成功。

### 1.2 创建测试租户

```bash
uv run python scripts/create_tenant.py --id tenant_a --name "租户A"
uv run python scripts/create_tenant.py --id tenant_b --name "租户B"
# 重复创建应报错
uv run python scripts/create_tenant.py --id tenant_a --name "重复测试"
```

**预期**：前两条成功；第三条 `code 10301 RESOURCE_CONFLICT`。

### 1.3 创建 API Key

```bash
uv run python scripts/create_api_key.py --tenant-id tenant_a --name "Key A"
# → rk_live_xxx...（仅出现一次，记下）
uv run python scripts/create_api_key.py --tenant-id tenant_b --name "Key B"
# → rk_live_xxx...
```

**预期**：明文 Key 仅在终端打印一次。租户不存在时创建报错。

---

## 二、后端鉴权验证

### 2.1 带正确 Key 调 `/v1/auth/me`

```bash
curl -s http://127.0.0.1:8000/v1/auth/me \
  -H "Authorization: Bearer $KEY_A" | python -m json.tool
```

**预期**：`code 0`，`data` 含 `tenant_id: "tenant_a"`、`tenant_name: "租户A"`、`key_prefix`。

### 2.2 不带 Key

```bash
curl -s http://127.0.0.1:8000/v1/auth/me | python -m json.tool
```

**预期**：`code 10200`，`message: "缺少 Authorization 请求头"`。

### 2.3 带错误 Key

```bash
curl -s http://127.0.0.1:8000/v1/auth/me \
  -H "Authorization: Bearer rk_live_<64位无效hex>" \
  | python -m json.tool
```

**预期**：`code 10200`，`message: "API Key 无效"`。

> **注意**：Key 必须是 `rk_live_` + 64 位 hex 的正确格式，否则后端不会走到哈希查表逻辑，会返回 500。

### 2.4 关闭鉴权降级

```bash
# 1. 改 .env：AUTH_ENABLED=false
# 2. 重启后端
curl -s http://127.0.0.1:8000/v1/auth/me | python -m json.tool
```

**预期**：`tenant_id: "default"`，`key_id: "fallback"`，`key_prefix: "none"`。

> 测试完后恢复 `AUTH_ENABLED=true` 并重启。

---

## 三、业务 API 隔离

以下测试前提：`AUTH_ENABLED=true`，两个租户和 Key 已创建。

### 3.1 Key A 创建知识库

```bash
curl -s -X POST http://127.0.0.1:8000/v1/knowledge-bases:create \
  -H "Authorization: Bearer $KEY_A" \
  -H "Content-Type: application/json" \
  -d '{"name":"A的知识库","description":""}' | python -m json.tool
```

**预期**：`code 0`，`data.tenant_id: "tenant_a"`。记下返回的 `kb_id`（下文以 `$KB_ID_A` 代替）。

### 3.2 Key A 上传文档

```bash
echo "测试内容——用于检索验证" > /tmp/test_doc.txt
curl -s -X POST http://127.0.0.1:8000/v1/documents:upload \
  -H "Authorization: Bearer $KEY_A" \
  -F "kb_id=$KB_ID_A" \
  -F "file=@/tmp/test_doc.txt" | python -m json.tool
```

**预期**：`code 0`，返回 `doc_id` 和 `chunk_count`。

> **注意**：上传接口是 **multipart**（`-F`），不是 JSON body。

### 3.3 Key A 检索

```bash
curl -s -X POST http://127.0.0.1:8000/v1/rag:retrieve \
  -H "Authorization: Bearer $KEY_A" \
  -H "Content-Type: application/json" \
  -d "{\"kb_ids\":[\"$KB_ID_A\"],\"query\":\"检索验证\",\"top_k\":3}" \
  | python -m json.tool
```

**预期**：`code 0`，`data.hits` 非空，召回内容匹配上传文档。

### 3.4 Key A 调 tree — 只能看到自己的数据

```bash
curl -s http://127.0.0.1:8000/v1/knowledge-bases/tree \
  -H "Authorization: Bearer $KEY_A" | python -m json.tool
```

**预期**：结果中只有 `tenant_id: "tenant_a"` 的知识库，不含 `tenant_b` 的数据。

### 3.5 Key B 调 tree — 看不到 A 的数据

```bash
curl -s http://127.0.0.1:8000/v1/knowledge-bases/tree \
  -H "Authorization: Bearer $KEY_B" | python -m json.tool
```

**预期**：`data: []`（空数组），不含 A 的知识库。

### 3.6 Key B 用 A 的 kb_id 检索 — 应失败

```bash
curl -s -X POST http://127.0.0.1:8000/v1/rag:retrieve \
  -H "Authorization: Bearer $KEY_B" \
  -H "Content-Type: application/json" \
  -d "{\"kb_ids\":[\"$KB_ID_A\"],\"query\":\"测试\",\"top_k\":3}" \
  | python -m json.tool
```

**预期**：`code 10201`（FORBIDDEN），`message: "部分知识库不属于当前租户（请求 1 个，归属 0 个）"`。

> 这是最关键的隔离防线——即使攻击者猜到了别人的 `kb_id`，检索时也会被 `validate_kb_ownership()` 拦截。

### 3.7 不带 Key 调业务接口

```bash
curl -s -X POST http://127.0.0.1:8000/v1/knowledge-bases:create \
  -H "Content-Type: application/json" \
  -d '{"name":"test","description":""}' | python -m json.tool
```

**预期**：`code 10200`（UNAUTHORIZED）。

---

## 四、前端链路

`admin/.env` 配置：

```
VITE_API_BASE_URL=http://localhost:8000
API_KEY=<KEY_A 明文>
```

> `API_KEY` 能被 Vite 暴露给客户端是因为 `vite.config.ts` 中 `envPrefix: ['VITE_', 'API_']`。

### 4.1 列表页 — 租户展示与两级结构

打开 `http://localhost:5173/knowledge-bases`：

- 标题右侧 Badge 显示 **"租户A (tenant_a)"** ✅
- 表格为两级：知识库 → 文档，无租户展开层 ✅
- 「去上传」跳转 URL 只带 `kb_id` ✅
- 「去检索」跳转 URL 只带 `kb_id` ✅

### 4.2 上传页 — 无 tenant_id 输入框

打开 `http://localhost:5173/knowledge-bases` → 点「去上传」：

- 页面上不存在 `tenant_id` 输入框 ✅
- KB 选择通过 URL 参数 `kb_id` 或下拉列表选择 ✅

### 4.3 检索页 — 无 tenant_id，租户自动识别

打开 `http://localhost:5173/retrieve?kb_id=$KB_ID_A`：

- 知识库下拉旁提示文案 **"通过 API Key 自动识别租户，无需手动选择"** ✅
- 下拉选项格式：`知识库名 (tenant_id)` ✅
- 检索范围区只有 `kb_id` 选择，无 `tenant_id` 输入 ✅

### 4.4 Key 无效提示

将 `admin/.env` 的 `API_KEY` 改为 `rk_live_` + 64 个 `0`（格式正确但不存在的 Key），重启 Vite dev server：

```bash
printf 'VITE_API_BASE_URL=http://localhost:8000\nAPI_KEY=rk_live_<64位无效hex>\n' > admin/.env
```

打开任意页面触发 API 请求：

**预期**：页面出现 **"加载失败：Request failed with status code 401"** 错误提示和重试按钮。

---

## 五、设计原理摘要

### 鉴权链路

```
Authorization: Bearer rk_live_xxx
        ↓ extract_token()
   原始 Key 明文
        ↓ hash_key() SHA-256
   哈希（不可逆）
        ↓ api_key_repo.get_by_hash()
   查数据库 → JOIN tenants
        ↓ 8 步校验（缺失/格式/不存在/吊销/过期/租户禁用）
   TenantContext(tenant_id, tenant_name, key_id, key_prefix)
        ↓ FastAPI Depends 注入路由
   所有业务操作从 current_tenant.tenant_id 获取身份
```

### 租户隔离防线（三层）

| 层 | 位置 | 机制 |
|----|------|------|
| 鉴权层 | `core/auth.py` | Key → TenantContext，8 步校验 |
| 业务层 | `retrieve_use_case.py:290` | `validate_kb_ownership()` SQL 级过滤 |
| 前端层 | `admin/src/lib/axios.ts` | Key 自动附加，页面无 tenant_id 输入框 |

### 关键设计决策

- **Key 只存哈希**：数据库泄露也无法反推原始 Key（SHA-256 不可逆）
- **Key 只打印一次**：`create_api_key.py` 生成后仅 `print` 一次，不落盘
- **错误码不区分**：缺失/格式错误/不存在/吊销/过期统一返回 `10200`，防止信息泄漏
- **tenant_id 不可伪造**：请求体中不传 `tenant_id`，身份 100% 来自 Key
- **双重隔离**：tree 接口过滤（看不到别人的 KB）+ retrieve 接口校验（猜到了也搜不到）
