# 验收标准

## 一、后端接口

### 1.1 POST `/api/v1/knowledge-bases:create`

|#|场景|Given|When|Then|
|---|---|---|---|---|
|AC1.1|正常创建|—|POST `{"name":"技术岗","tenant_id":"tech"}`|返回 201，含 `kb_id`、`name`、`tenant_id`|
|AC1.2|名称重复|已有 KB 叫"技术岗"|再次 POST `{"name":"技术岗","tenant_id":"tech2"}`|返回 409，`errors[].field === "name"`|
|AC1.3|名称超长|—|POST `name` 超过 64 字符|返回 422|
|AC1.4|tenant_id 超长|—|POST `tenant_id` 超过 64 字符|返回 422|
|AC1.5|必填缺失|—|POST 缺少 `name` 或 `tenant_id`|返回 422|
|AC1.6|tenant_id 可任意值|—|POST `tenant_id:"a"` 和 `tenant_id:"a"`|两个 KB 分组在同一租户下|

### 1.2 GET `/api/v1/knowledge-bases/tree`

|#|场景|Given|When|Then|
|---|---|---|---|---|
|AC2.1|空数据库|无任何 KB|GET `/tree`|返回 `{"data":[]}`|
|AC2.2|单租户单 KB 无文档|1 个 KB，0 文档|GET `/tree`|返回 1 租户，1 KB，`documents:[]`|
|AC2.3|单租户多 KB 多文档|2 个 KB，各 2 个文档|GET `/tree`|三级结构正确展开|
|AC2.4|多租户|2 个租户各含 KB|GET `/tree`|租户按 `tenant_id` 字典序排列|
|AC2.5|KB 排序|同一租户下 2 个 KB|GET `/tree`|KB 按 `created_at` 倒序|
|AC2.6|keyword 过滤|tenant_id 含 `tech` 和 `demo`|GET `/tree?keyword=tech`|仅返回 `tech` 开头的租户|
|AC2.7|keyword 大小写|—|GET `/tree?keyword=TECH`|模糊匹配不区分大小写|
|AC2.8|keyword 无匹配|—|GET `/tree?keyword=nonexist`|返回 `{"data":[]}`|
|AC2.9|文档返回全量|—|—|文档层返回所有已上传文档（同步模式无 pending/failed 状态，不做过滤）|

### 1.3 POST `/api/v1/rag/retrieve`

|#|场景|Given|When|Then|
|---|---|---|---|---|
|AC3.1|hybrid 模式正常检索|KB 有 chunk 数据|POST `mode:"hybrid"`|返回 `hits` + `meta`，`meta.mode="hybrid"`|
|AC3.2|vector 模式|同上|POST `mode:"vector"`|仅向量检索，`bm25_score` 全 `null`，`meta.bm25_count=0`|
|AC3.3|bm25 模式|同上|POST `mode:"bm25"`|仅 BM25，`vector_score` 全 `null`，`meta.vector_count=0`|
|AC3.4|per-hit 分数|hybrid 模式|检索|每个 hit 含 `score`、`vector_score`、`bm25_score`|
|AC3.5|rerank 启用|rerank 配置正常|POST `rerank.enabled:true`|`rerank_score` 非 null，`meta.rerank_model` 非 null|
|AC3.6|rerank 禁用|—|POST `rerank.enabled:false`|`rerank_score` 全 `null`，请求不传 `rerank.top_n`|
|AC3.7|latency_ms|—|检索|`meta.latency_ms` > 0，为服务端真实耗时|
|AC3.8|ES 降级|ES 不可用|POST `mode:"hybrid"`|`meta.degraded=true`，降级为纯向量，不报错|
|AC3.9|KB 不存在|—|POST `kb_ids:["kb_nonexist"]`|返回 404|
|AC3.10|query 为空|—|POST `query:""`|返回 422|
|AC3.11|mode 非法值|—|POST `mode:"invalid"`|返回 422|
|AC3.12|向后兼容|旧客户端|POST 仅 `query`+`kb_ids`+`top_k`|正常返回，默认 mode=hybrid|
|AC3.13|hybrid 参数仅在 hybrid 生效|mode="vector"|POST 含 `vector_top_k`|该参数被忽略，不影响结果|

---

## 二、前端页面

### 2.1 AppHeader 组件

|#|场景|Given|When|Then|
|---|---|---|---|---|
|AC4.1|三页面皆渲染|—|访问 `/`、`/knowledge-bases`、`/retrieve`|顶栏显示"RAGNexus 调试控制台"品牌名，右侧无导航|
|AC4.2|高度固定|—|—|52px，sticky 置顶|

### 2.2 `/` 首页（创建 KB + 上传文档）

|#|场景|Given|When|Then|
|---|---|---|---|---|
|AC5.1|创建 KB 成功|—|填写 tenant_id + name，点创建|显示成功 toast，含 kb_id|
|AC5.2|创建 KB 失败（重复）|已有同名 KB|创建同名|显示错误提示|
|AC5.3|上传文档成功|已选 KB + 文件|点上传|进度条→结果表格，显示 chunk 数|
|AC5.4|上传无 KB|未选 KB|点上传|按钮 disabled|
|AC5.5|创建 KB 和上传独立|—|先创建 KB，不点上传|上传区域不受影响|
|AC5.6|不使用 localStorage|—|刷新页面|KB 列表从 `/tree` API 获取，不依赖缓存|

### 2.3 `/knowledge-bases` 列表页

|#|场景|Given|When|Then|
|---|---|---|---|---|
|AC6.1|三级树展示|有租户、KB、文档|访问页面|租户→KB→文档三级可展开|
|AC6.2|默认展开第一层|—|首次加载|租户层展开|
|AC6.3|展开/收起|—|点租户行箭头|切换该租户下 KB 可见性|
|AC6.4|搜索过滤|多租户|输入"tech"搜索|仅显示匹配 tenant_id 的租户|
|AC6.5|复制 kb_id|—|hover KB 行，点"复制"|kb_id 写入剪贴板|
|AC6.6|跳转上传|—|点 KB 行"去上传"|跳转 `/`，且上传区域自动选中该 KB|
|AC6.7|跳转检索|—|点 KB 行"检索"|跳转 `/retrieve?tenant_id=xxx&kb_id=xxx`|
|AC6.8|空状态|无数据|访问页面|显示空状态提示|

### 2.4 `/retrieve` 检索调试页

|#|场景|Given|When|Then|
|---|---|---|---|---|
|AC7.1|URL 预填|从列表页跳转带 `?tenant_id=xx&kb_id=xx`|页面加载|tenant_id 和 KB 下拉自动预填|
|AC7.2|检索成功|填好参数+query|点检索|显示召回结果列表，每项含分数和内容|
|AC7.3|切换检索模式|当前 hybrid|点 bm25|hybrid 参数行隐藏，mode 发送 `"bm25"`|
|AC7.4|hybrid 参数仅 hybrid 显示|当前 vector|—|`vector_top_k`/`bm25_top_k`/`rrf_k` 不可见|
|AC7.5|rerank 切换|rerank 启用|关闭 rerank|`rerank top_n` 隐藏，请求不含 `rerank` 字段|
|AC7.6|运行摘要展示|检索完成|查看底部卡片|`latency_ms`、`mode`、counts、`degraded` 正确显示|
|AC7.7|检索配置可折叠|—|点卡片标题|配置区域折叠/展开|
|AC7.8|chunk 内容可折叠|检索完成|点结果条目|内容展开/收起|
|AC7.9|必填校验|未填 query 或 KB|点检索|内联错误提示|
|AC7.10|不使用 localStorage|—|刷新页面|表单状态不保留（清除重新来）|

---

## 三、集成 & 非功能

|#|场景|Given|When|Then|
|---|---|---|---|---|
|AC8.1|首页上传统计不变|已有上传逻辑|上传文档|首页计数、结果表不受列表页/检索页影响|
|AC8.2|路由互不干扰|—|在三个页面间切换|浏览器的前进/后退正常|
|AC8.3|无鉴权|—|直接访问所有路由和 API|无 401/403|
|AC8.4|不分页|超 50 个租户/KB|tree API|返回全部数据，不做 limit/offset|
## 四、端到端流程验收

在本地拉起真实环境（PostgreSQL + pgvector + ES + LLM），通过 API 序列或浏览器完成全链路。

|#|流程步骤|预期结果|
|---|---|---|
|E2E.1|`docker compose up -d`，`GET /health` → 200|全服务健康|
|E2E.2|POST 创建 KB `{"name":"技术岗位知识库","tenant_id":"tech_position"}`|201，返回 kb_id|
|E2E.3|上传 backend_engineer.md（含代码+中文 ~50KB）|chunk_count ≥ 3|
|E2E.4|上传 frontend_engineer.md 到同一 KB|成功|
|E2E.5|访问 `/knowledge-bases`|树：`tech_position → 技术岗位知识库 → 2 文件`|
|E2E.6|点 KB 行「检索」|URL 变为 `/retrieve?tenant_id=tech_position&kb_id=xxx`，表单预填|
|E2E.7|默认配置检索 query "Go 后端技能"|5 hits，每项含 score/vector/bm25/rerank，meta 含 latency_ms|
|E2E.8|切 mode=vector 检索|bm25_score 全 null|
|E2E.9|切 mode=bm25 检索|vector_score 全 null|
|E2E.10|关闭 rerank 检索|rerank_score 全 null|
|E2E.11|查看运行摘要|latency_ms > 0，counts 正确|
|E2E.12|回首页创建第二个 KB（同租户）并上传|成功|
|E2E.13|回列表页确认树刷新为 2 KB|结构正确|
|E2E.14|折叠/展开 / 搜索过滤|交互流畅|
