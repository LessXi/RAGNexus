## Why

当前文档上传在单个 HTTP 连接内同步完成解析→分块→Embedding→双写(pgvector+ES)，大文档导致超时。同时知识库和文档只能创建不能管理——传错了删不掉，索引失败无法重试，缺乏完整生命周期运维能力。

## What Changes

- **BREAKING**: `POST /v1/documents:upload` 返回 `status=PROCESSING` 而非同步等待索引完成，`chunk_count` 在索引完成前为 0
- **BREAKING**: `GET /v1/knowledge-bases/tree` 的 `documents[].status` 从 `"completed"` 扩展为三种状态（PROCESSING/SUCCESS/FAILED），新增 `error_message` 字段
- 引入 Celery + Redis 架构，upload 秒回后由后台 Worker 执行索引
- `documents` 表新增 `status`/`content`/`error_message` 列
- 新增 `DocumentPort` + `PgDocumentRepository`，解除 KB 仓库的文档操作耦合
- 拆分 `UploadUseCase`，抽取 `IndexingService`（复用现有索引代码）
- 新增 6 个 HTTP 端点：文档状态查询、删除、重试索引；知识库详情、更新、删除
- `tree` 接口适配三种文档状态，支持前端轮询
- admin 前端适配：上传页异步响应、列表页状态展示/轮询/操作入口、编辑/确认弹窗

## Capabilities

### New Capabilities

- `async-indexing`: 异步文档索引——Celery Worker 后台执行解析/分块/Embedding/双写，文档状态机（PROCESSING→SUCCESS/FAILED），失败重试
- `doc-lifecycle`: 文档生命周期管理——状态查询（GET /documents/{id}）、删除（DELETE，级联清理 pgvector+ES）、失败重试（POST reindex）
- `kb-lifecycle`: 知识库生命周期管理——详情查询（GET /knowledge-bases/{id}，含完整 settings）、更新（PATCH name/description/settings）、级联删除（DELETE，含 PROCESSING 保护）

### Modified Capabilities

<!-- 无已有 spec 受影响 -->
