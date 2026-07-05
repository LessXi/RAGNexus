# Task 3.4 — UploadDocumentUseCase 异步拆分 + di.py

**完成时间**: 2026-07-05

## 变更概览

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/ragnexus/di.py` | **新建** | 共享 DI 工厂 — `build_indexing_services()` / `build_indexing_services_async()` |
| `src/ragnexus/application/upload_doc_use_case.py` | **重构** | 添加 `doc_repo: DocumentPort`；execute() 保留校验（Steps 1-5），替换解析→嵌入→双写为 `doc_repo.create()` + `task.delay()` |
| `src/ragnexus/adapters/http/upload_doc_router.py` | **修改** | 响应体新增 `status` 字段 |
| `src/ragnexus/composition.py` | **修改** | UploadDocumentUseCase 构造添加 `doc_repo=document_repo` |
| `src/ragnexus/tasks/indexing.py` | **修复** | 修复 event loop 问题：使用 `build_indexing_services_async()` 在单个 `asyncio.run()` 中完成构建+执行 |
| `tests/unit/application/test_upload_doc.py` | **适配** | 添加 `mock_doc_repo` fixture，更新所有 UploadDocumentUseCase 构造 |
| `tests/unit/application/test_upload_dual_write.py` | **适配** | 同上；测试断言仍待重写以匹配新异步模型 |

## 关键设计决策

### di.py — 异步构建器
`build_indexing_services()` 内部调用 `asyncio.run()`，会关闭 event loop。为解决 Worker 任务中 asyncpg 连接池无法跨越 loop 的问题，额外暴露了 `build_indexing_services_async()` 协程，供 `tasks/indexing.py` 在单个 `asyncio.run()` 中完成构建→执行→清理。

### UploadDocumentUseCase — 同步校验 + 异步触发
- **保留**: 文件大小/扩展名检查、KB 存在性+归属校验、去重（Steps 1-5）
- **新增**: 通过 `DocumentPort.create()` 持久化 Document 记录（状态 PROCESSING），然后 `index_document_task.delay(doc_id)` 提交 Celery 任务
- **移除**: 解析、分块、嵌入、双写逻辑（移至 `IndexingService.execute()` 由 Worker 异步执行）
- 返回体改为 `status=DocStatus.PROCESSING, chunk_count=0`

### 已知影响
- 单元测试和集成测试中构造 `UploadDocumentUseCase` 的代码已添加 `doc_repo` 参数，但测试断言（如验证 chunk 内容、双写行为）仍需按新异步模型重写
- `SynonymSyncUploadUseCase` 的词表同步在 Worker 进程中尚未触发（需后续任务补充）

## 验收结果
```bash
python -c "from ragnexus.di import build_indexing_services; print('di imports OK')"  # ✅
```
- `UploadDocumentUseCase.__init__` 包含 `doc_repo` 参数 ✅
- `execute()` 使用 `self._doc_repo.create()` + `index_document_task.delay()` ✅
