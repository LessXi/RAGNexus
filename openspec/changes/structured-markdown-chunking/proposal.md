# Proposal: 结构化 Markdown 切块

## Why

当前索引侧已落后于检索侧：无论上传什么文档，都按固定 800 字符滑动窗口一刀切。这导致标题被截断、跨节内容混入同一 chunk、表格被拦腰切断丢失表头——三个问题直接拉低召回质量和 RAGAS 分数。检索侧（调试台、词表、query 改写、profile、RAGAS 测评）的优化已接近天花板，**索引侧的切块精度是当前最大的检索质量瓶颈**。

## What Changes

- **替换切块器**：`heading_aware_split` → `structchunk` 库的结构化切块（按 `#`/`##` 分节、表格整块保留表头、代码块不截断），`###` 三级标题归入上级节
- **新增 chunk 元数据**：每个 chunk 记录 `heading_path`（标题层级路径）和 `chunk_type`（section/table/code/list）
- **扩展单文档 reindex**：`POST /documents/{id}/reindex` 从仅允许 FAILED 状态扩展为允许 SUCCESS 状态强制重建
- **新增批量 reindex 脚本**：`scripts/reindex_knowledge_base.py`，一条命令对指定知识库下所有已索引文档重建索引
- **调试台增强**：`/retrieve` 页面的 chunk 卡片显示「所属章节」和「块类型」
- **保留 .txt 回退**：纯文本文件仍走接近旧行为的分块方式，不阻塞

## Capabilities

### New Capabilities

- `retrieve-api-chunk-metadata`: 检索响应 chunk metadata 新增 heading_path 和 chunk_type 字段，调试台据此展示章节和块类型
- `structured-chunking`: 结构化 Markdown 切块能力 — 沿标题边界分节、表格整块保留表头、每 chunk 携带 `heading_path` 和 `chunk_type` 元数据
- `batch-reindex`: 批量重建索引能力 — 脚本对指定知识库下所有已索引文档跑 purge + 重新索引，打印进度和统计

### Modified Capabilities


## Impact

| 维度 | 影响 |
|------|------|
| 代码 | `src/ragnexus/infra/structchunk_bridge.py`（新建）、`domain/chunking.py`（废弃旧 chunker）、`indexing_service.py`（分流逻辑）、`document_reindex_uc.py`（状态检查）、`di.py`（注入切换）、`document_router.py`（文档更新） |
| 依赖 | 新增 `structchunk` 库（已存在于 `.tmp/structchunk_audit/`，需集成到项目） |
| API | `POST /documents/{id}/reindex` 行为变更（**BREAKING**: 现在 SUCCESS 文档也可调用），`POST /v1/rag:retrieve` 响应 metadata 新增字段（向下兼容） |
| 数据库 | chunks.metadata JSONB 新增 `heading_path`、`chunk_type`、`table_part` 字段，已有数据需 reindex 后更新 |
| 前端 | `admin/src/pages/retrieve.tsx` chunk 卡片展示逻辑变更 |
