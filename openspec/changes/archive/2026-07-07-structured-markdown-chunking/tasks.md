# Tasks: 结构化 Markdown 切块

## 1. structchunk 集成

- [x] 1.1 将 `.tmp/structchunk_audit/src/structchunk/` 拷贝到 `src/ragnexus/infra/structchunk/`，验证其单测通过
- [x] 1.2 新建 `src/ragnexus/infra/__init__.py` 和 `src/ragnexus/infra/structchunk_bridge.py`，封装 `chunk_markdown(content, max_chars, **kwargs) -> list[dict]`
- [x] 1.3 `chunk_markdown` 实现 metadata 映射逻辑：`header_breadcrumb` → `heading_path`，`source_element_type` → `chunk_type`，保留 `heading`/`heading_level` 向后兼容
- [x] 1.4 配置新增变量 `TABLE_MAX_ROWS_PER_CHUNK`（默认 10）到 `Settings` 和 `.env`

## 2. 切块器替换

- [x] 2.1 `src/ragnexus/domain/chunking.py`：保留 `fixed_size_split`，`heading_aware_split` 标记废弃
- [x] 2.2 `src/ragnexus/application/indexing_service.py`：按扩展名分流（.md → structchunk，.txt → fixed_size_split），metadata 构建含 `heading_path`/`chunk_type`
- [x] 2.3 `src/ragnexus/di.py`：chunker 依赖注入从 `heading_aware_split` 切换到 `chunk_markdown`，max_chars 参数对齐

## 3. 单文档 reindex 扩展

- [x] 3.1 `src/ragnexus/application/document_reindex_uc.py`：状态检查从 `!= FAILED` 改为 `== PROCESSING` 拒绝，允许 SUCCESS 状态
- [x] 3.2 `src/ragnexus/adapters/http/document_router.py`：扩展 `POST /documents/{id}/reindex` 的接口描述和响应说明

## 4. 批量 reindex 脚本

- [x] 4.1 新建 `scripts/reindex_knowledge_base.py`：支持 `--kb-id`（必填）、`--tenant-id`（可选）、`--document-id`（可多次传入）
- [x] 4.2 脚本实现 purge + PROCESSING 置状态 + Celery task 提交，按文档逐条执行
- [x] 4.3 单篇失败不阻断其余文档，结束时打印 success/failed/skipped 三项统计

## 5. 调试台展示

- [x] 5.1 `admin/src/pages/retrieve.tsx`：chunk 卡片 content 折叠区上方新增「所属章节」和「块类型」展示行
- [x] 5.2 仅在 `heading_path` 或 `chunk_type` 有值时显示，无值时不影响现有布局

## 6. 测试

- [x] 6.1 `tests/unit/infra/test_structchunk_bridge.py`：测试 metadata 映射（heading_path 格式、chunk_type 映射、向后兼容字段）
- [x] 6.2 `tests/unit/application/test_indexing_service.py`：更新 chunker mock，验证 .md 走 structchunk、.txt 走 fixed_size_split
- [x] 6.3 `tests/unit/application/test_document_reindex_uc.py`：SUCCESS 文档可 reindex，PROCESSING 文档拒绝
- [x] 6.4 `tests/unit/domain/test_chunking.py`：fixed_size_split 行为不变，heading_aware_split 弃用标记验证

## 7. 文档

- [x] 7.1 `README.md` 新增「切块策略升级后 reindex」小节，说明脚本用法和执行时机
- [x] 7.2 `AGENTS.md` 补充结构化切块相关诊断信息（chunk_type 查询、reindex 常见问题）
