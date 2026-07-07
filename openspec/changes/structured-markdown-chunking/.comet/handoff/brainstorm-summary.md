# Brainstorm Summary

- Change: structured-markdown-chunking
- Date: 2026-07-07

## 确认的技术方案

**方案 A: structchunk 集成** — 将 `.tmp/structchunk_audit/src/structchunk/` 拷贝到 `src/ragnexus/infra/structchunk/`，封装 `chunk_markdown()` bridge 函数。

- `.md` 文档：绕过 MarkdownAndTextParser，直连 structchunk（hierarchical 算法）
- `.txt` 文档：保留 Parser → `fixed_size_split` 回退路径
- `table_part`：bridge 层后处理，对连续 `chunk_type='table'` 的 chunk 自增编号
- metadata 映射：`header_breadcrumb` → `heading_path`（去 `#` 后 `/` 连接），`source_element_type` → `chunk_type`（paragraph→section, table→table, code→code, list→list）
- 保留 `heading` 和 `heading_level` 向后兼容
- `chunkmax_chars` 默认 1500，新增 `TABLE_MAX_ROWS_PER_CHUNK` 默认 10
- reindex：SUCCESS 状态允许强制重建，PROCESSING 拒绝
- 调试台：chunk 卡片新增「所属章节」和「块类型」展示行

## 关键取舍与风险

- **取舍**: 用 structchunk 而非自建 MarkdownStructuredSplitter。已有 300+ 测试覆盖，零开发成本获得全部能力
- **风险**: structchunk 可能有不兼容依赖 → 纯 Python 无 C 扩展，拷贝核心文件即可
- **风险**: chunk 数量突增 → reindex 后对比 chunk_count，必要时调整 CHUNK_MAX_CHARS
- **风险**: reindex 期间文档不可检索 → 低峰期执行，单篇失败不阻断

## 测试策略

- 单元：bridge metadata 映射、indexing 分流逻辑、reindex 状态检查
- 集成：上传含标题/表格 .md → 验证 chunks.metadata
- E2E：上传 → 检索 → 确认 API 响应含 heading_path/chunk_type

## Spec Patch

无（delta spec 在 open 阶段已完整，brainstorming 未发现缺口）
