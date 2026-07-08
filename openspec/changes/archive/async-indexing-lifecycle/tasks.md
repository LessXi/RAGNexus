## 1. 基础设施

- [ ] 1.1 docker-compose.yml 增加 Redis 服务 + Celery worker 服务（worker depends_on: redis, db, elasticsearch 均为 healthy）
- [ ] 1.2 Dockerfile 增加 worker target 或 compose 覆盖 worker command 为 `celery -A src.ragnexus.celery_app worker`
- [ ] 1.3 pyproject.toml 增加 celery[redis]>=5.4.0 + redis>=5.0.0 依赖
- [ ] 1.4 Settings 增加 CELERY_BROKER_URL / CELERY_RESULT_BACKEND / INDEX_TIMEOUT_MINUTES
- [ ] 1.5 确认 Alembic 环境可用（`alembic current` 可执行），若未初始化则执行 `alembic init` + 配置
- [ ] 1.6 Alembic migration: documents 表加 status INT, content TEXT, error_message TEXT, updated_at TIMESTAMPTZ 列
- [ ] 1.7 更新 docs/sql/schema.sql 对齐实际表结构（同步 knowledge_bases 已有列 tenant_id/description/settings）
## 2. 领域层

- [ ] 2.1 models.py: 新增 Document dataclass + DocStatus IntEnum
- [ ] 2.2 models.py: UploadResult 增加 status 字段
- [ ] 2.3 models.py: DocNode / KBNode 增加 error_message + status 适配
- [ ] 2.4 ports.py: 新增 DocumentPort Protocol
- [ ] 2.5 ports.py: KnowledgeBasePort 扩展 update/delete/has_processing 方法
- [ ] 2.6 新增 adapters/document/pg.py → PgDocumentRepository
- [ ] 2.7 重构 PgKnowledgeBaseRepository: kb update/delete，移除嵌入的文档操作
- [ ] 2.8 调整 composition.py DI 注入新的 document_repo + 更新的 kb_repo

## 3. 异步索引核心

- [ ] 3.1 新增 celery_app.py: Celery 实例 + task_acks_late=True + beat schedule（超时检测）；task 内部 asyncio.run() 中临时创建 asyncpg Pool（min_size=1, max_size=3），用完即关
- [ ] 3.2 新增 application/indexing_service.py: 复用 parser/chunker/embedder/store
- [ ] 3.3 新增 tasks/indexing.py: index_document_task（asyncio.run 桥接）+ 超时检测 task
- [ ] 3.4 重构 UploadDocumentUseCase: 拆分为 create_document_record + task.delay()
- [ ] 3.5 新增 purge_document_chunks 工具方法（PG CASCADE + ES delete）
- [ ] 3.6 调整 SynonymSyncUploadUseCase 触发时机：upload 创建记录后暂不触发，索引 SUCCESS 后触发

## 4. 运维 API

- [ ] 4.1 新增 GET /v1/documents/{doc_id} 路由 + DocumentQueryUseCase
- [ ] 4.2 新增 DELETE /v1/documents/{doc_id} 路由 + DocumentDeleteUseCase
- [ ] 4.3 新增 POST /v1/documents/{doc_id}/reindex 路由 + DocumentReindexUseCase
- [ ] 4.4 新增 GET /v1/knowledge-bases/{kb_id} 路由 + KnowledgeBaseDetailUseCase
- [ ] 4.5 新增 PATCH /v1/knowledge-bases/{kb_id} 路由 + KnowledgeBaseUpdateUseCase
- [ ] 4.6 新增 DELETE /v1/knowledge-bases/{kb_id} 路由 + KnowledgeBaseDeleteUseCase
- [ ] 4.7 tree 接口适配: DocNode 增加 status + error_message，三种状态全部返回

## 5. 前端适配

- [ ] 5.1 types/api.ts: 新增 DocStatus 枚举, DocumentDetail, UpdateKBRequest 等类型
- [ ] 5.2 documentService.ts: 新增 deleteDocument / reindexDocument
- [ ] 5.3 knowledgeBaseService.ts: 新增 fetchDetail / updateKB / deleteKB
- [ ] 5.4 上传页: 适配 PROCESSING 响应（"已提交，正在后台索引" Toast）
- [ ] 5.5 列表页: 三种状态 StatusBadge（黄/绿/红）+ PROCESSING 时 3s 轮询
- [ ] 5.6 列表页: 文档删除/重试按钮 + KB 编辑/删除入口
- [ ] 5.7 新增 ConfirmDialog 组件（删文档/删 KB 复用）
- [ ] 5.8 新增 EditKnowledgeBaseDialog 组件（name + description + settings JSON）
- [ ] 5.9 集成测试: 三页导航正常，完整操作路径验证

## 6. 测试与文档

- [ ] 6.1 单元测试: IndexingService、DocumentRepository、KnowledgeBaseRepository
- [ ] 6.2 集成测试: 异步上传→轮询→检索命中 完整链路
- [ ] 6.3 集成测试: ES 不可用→FAILED→恢复→reindex→SUCCESS
- [ ] 6.4 集成测试: knowledge-base CRUD 完整覆盖
- [ ] 6.5 集成测试: 跨租户隔离（GET/PATCH/DELETE 均返回 NOT_FOUND）
- [ ] 6.6 E2E 测试: PROCESSING 文档 DELETE/delete-KB 被拒绝
- [ ] 6.7 更新 README.md 补充 Worker 启动命令和异步索引说明
