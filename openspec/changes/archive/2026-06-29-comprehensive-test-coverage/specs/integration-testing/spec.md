## ADDED Requirements

### Requirement: Composition 生命周期集成测试

系统 SHALL Composition 生命周期集成测试。

composition.py 的 lifespan 启动/关闭流程可通过集成测试验证。

#### Scenario: 正常启动
- **WHEN** 测试数据库可用且 schema 已创建
- **THEN** build_app() 返回的 FastAPI 实例在 TestClient 中正常启动，所有路由已注册
- **AND** /health 返回 200

#### Scenario: 正常关闭
- **WHEN** TestClient 上下文退出
- **THEN** 连接池正确关闭，embedder/LLM HTTP client 正确关闭
- **AND** 后台清理任务被取消

#### Scenario: 迁移未执行时告警
- **WHEN** alembic_version 表不存在或为空
- **THEN** lifespan 打印 WARNING 级别日志但不阻塞启动

### Requirement: RetrieveUseCase 全链路集成测试

系统 SHALL RetrieveUseCase 全链路集成测试。

检索全链路可在真实 PostgreSQL + pgvector 上验证（外部 HTTP 用 mock）。

#### Scenario: 单 KB 检索
- **WHEN** 向已有 chunks 的 KB 发起检索请求
- **THEN** 返回按 cosine 相似度排序的 SearchHit 列表

#### Scenario: 多 KB 检索
- **WHEN** 同时检索 2 个 KB
- **THEN** 返回跨 KB 合并排序的结果

#### Scenario: Rerank 启用时候选放大
- **WHEN** RERANK_ENABLED=true 且配置了 candidate_multiplier
- **THEN** 向量搜索使用 candidate_k = top_k × candidate_multiplier 召回

### Requirement: UploadDocumentUseCase 全链路集成测试

系统 SHALL UploadDocumentUseCase 全链路集成测试。

上传全链路可在真实 PostgreSQL + pgvector 上验证。

#### Scenario: Markdown 上传成功
- **WHEN** 上传一个多标题 Markdown 文件
- **THEN** 文件被解析、分块、向量化、存储
- **AND** 返回 chunk_count >= 分块数

#### Scenario: 上传后立即可检索
- **WHEN** 上传成功后立即检索
- **THEN** 返回至少 1 个命中结果

### Requirement: Alembic 迁移验证

系统 SHALL Alembic 迁移验证。

迁移脚本可在真实数据库上执行和回滚。

#### Scenario: upgrade head 成功
- **WHEN** 对空白测试库运行 alembic upgrade head
- **THEN** 所有表被创建，包含 chunks.embedding vector 列

#### Scenario: downgrade 成功
- **WHEN** 对已迁移库运行 alembic downgrade -1
- **THEN** 所有表被删除，回到空白状态
