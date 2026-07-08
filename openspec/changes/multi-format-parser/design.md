## Context

RAGNexus 采用 Clean Architecture 分层：`domain`（ports + models）→ `application`（use cases + indexing service）→ `adapters`（parsers, http, vector_store, keyword_search 等）→ `composition`（DI 组装）。

当前文档处理链路：`multipart upload → UTF-8 decode → Document(content=text) → Celery task → IndexingService.execute()`，其中 IndexingService 内 `ParserPort.parse()` → `heading_aware_split()` → embed → ES + pgvector 双写。

`adapters/parsers/` 目录已存在，包含 `MarkdownAndTextParser`（实现 `ParserPort`）。`ParsedDocument` 输出 `sections: list[Section]` + `raw_text`，供 `heading_aware_split` 按标题分块。

本次变更在该目录下新增 Word 和 PDF 解析器，并扩展上传和索引编排以支持二进制文件。

## Goals / Non-Goals

**Goals:**
- 使 RAGNexus 直接接收 `.docx` 和 `.pdf` 文件，自动解析后进入现有索引流水线
- 保持现有 `.md`/`.txt` 上传行为零破坏
- Parser 架构可插拔，后续新增格式只需写新 Parser 并注册
- 支持从原始文件重新解析（reparse）
- 上传接口同时支持 JSON 文本和 multipart 二进制两种模式

**Non-Goals:**
- OCR 扫描件 PDF 识别
- 旧版 `.doc` 格式支持
- HTML、Excel、PPT 等格式
- 修改切块（chunking）、embedding、向量存储、关键词检索、retrieve 逻辑
- 修改知识库管理、租户系统、配额/限流系统

## Decisions

### 决策 1：Parser 输出保持 sections 模型，扩展而非替换

**选型**：保持 `ParsedDocument(sections=..., raw_text=...)` 结构，增加 `source_type` 和 `metadata` 字段。

**替代方案**：改为扁平 Markdown 字符串输出（需求文档建议方案）。

**理由**：
- RAGNexus 的 `heading_aware_split` 已基于 sections 结构验证有效，改为扁平字符串需重写 splitter，引入不必要的回归风险
- sections 结构比 Markdown 字符串更精确：标题层级、表格结构等信息不会因 Markdown 序列化/反序列化丢失
- Word/PDF Parser 只需将解析结果转换为 sections 即可无缝接入，实现成本更低
- `source_type` 和 `metadata` 字段向后兼容（有默认值），不影响现有 consumer

**ParsedDocument 扩展后结构**：
```python
@dataclass
class ParsedDocument:
    filename: str
    sections: list[Section]
    raw_text: str
    source_type: str = "text"        # 新增: text | markdown | docx | pdf
    metadata: dict = field(default_factory=dict)  # 新增: parser_name, page_count, warnings
```

### 决策 2：Parser 注册机制 — 在现有 adapters/parsers 下新增 registry

**选型**：在 `adapters/parsers/registry.py` 实现按扩展名选择 Parser。

**替代方案**：在 DI 层（composition.py）硬编码条件分支。

**理由**：
- 与项目已有的 Provider 模式一致（embedder、llm、rerank 均有 adapter 注册）
- 新增格式只需：写一个 Parser 类 + `registry.register(ext, parser)`，零侵入
- Registry 返回 ParserPort 协议，调用方无感知

**Registry 接口**：
```python
# adapters/parsers/registry.py
_parsers: dict[str, ParserPort] = {}

def register(ext: str, parser: ParserPort) -> None: ...
def get_parser(filename: str) -> ParserPort:  # 按扩展名匹配，未匹配抛 UNSUPPORTED_FORMAT
```

### 决策 3：上传双模式 — 同一路径，按 Content-Type 分发

**选型**：新增 `POST /v1/documents:upload-text`（JSON body），原有 `POST /v1/documents:upload` 扩展支持二进制 multipart。

**替代方案**：单一路由内根据 Content-Type header 分发。

**理由**：
- FastAPI 的 `Form + UploadFile` 依赖注入与 `Body(BaseModel)` 无法在同一端点共存
- 独立路由更清晰，且符合项目已有路由命名风格（`:upload`、`:create`、`:retrieve`）
- JSON 路由与现有前端 uploadDoc 调用解耦，便于渐进迁移

### 决策 4：二进制文件延迟解析 — 上传时暂存，Worker 中解析

**选型**：上传阶段保存原始文件到磁盘，`content` 先置空，`source_type` 标记格式。Worker 中 IndexingService 在切块前从文件读取并解析。

**理由**：
- Word/PDF 解析是 CPU 密集型操作，不应阻塞 HTTP 响应
- 与现有 Celery 异步架构一致，IndexingService 已有幂等保护（非 PROCESSING 跳过）
- 原文件保留在磁盘，支持未来的 reparse 和格式升级

**上传流水线调整**：
```
multipart upload（二进制文件）
  → 文件大小/扩展名校验
  → KB 存在+归属校验
  → 去重检查
  → LocalFileStorage.save() → 写入 DOCUMENT_STORAGE_PATH/{tenant_id}/{doc_id}/{filename}
  → Document(content='', source_file_path=path, source_filename=filename, source_type='docx'|'pdf')
  → Celery index_document_task

multipart upload（文本文件 .md/.txt）
  → 行为与现在一致（UTF-8 decode → content 写入）

JSON upload（/v1/documents:upload-text）
  → {kb_id, title, content} → Document(content=content, source_type='text')
  → Celery index_document_task
```

### 决策 5：IndexingService 扩展 — 增加 prepare_document_content 步骤

在现有 `execute()` 的 parse 步骤前增加内容准备逻辑：

```
execute(doc_id):
  1. 获取 Document
  2. 【新增】如果 source_file_path 存在且 content 为空：
     a. 从磁盘读取原文件
     b. 通过 registry 选择 Parser
     c. 解析 → 更新 Document.content + source_type
  3. 现有流程：ParserPort.parse(content) → heading_aware_split → embed → 双写
```

### 决策 6：文件存储适配器

**选型**：新增 `adapters/file_storage/local.py`，实现 `FileStoragePort`。

**接口**：
```python
class FileStoragePort(Protocol):
    async def save(self, tenant_id: str, doc_id: str, filename: str, content: bytes) -> str: ...
    async def read(self, path: str) -> bytes: ...
    async def delete(self, path: str) -> None: ...
```

存储路径：`{DOCUMENT_STORAGE_PATH}/{tenant_id}/{doc_id}/{filename}`

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| mammoth 对中文 Word 文档的标题/表格转换质量不确定 | 验收阶段用真实中文制度文档实测；不合格时评估替代方案（python-docx） |
| PDF 解析大文件耗时可能导致 Celery 任务超时 | 设置合理的 task soft/hard time limit；PyMuPDF 按页流式读取，内存可控 |
| `ParsedDocument` 扩展后，所有现有 parser consumer 需要兼容新字段 | 新字段有默认值，向后兼容；运行现有测试套件验证零回归 |
| 磁盘存储增长（原文件保留） | 后续可增加文件清理策略（文档删除时同步删除文件） |
| 多格式 Parser 的维护成本 | 插件化架构降低耦合；每种格式独立文件，互不影响 |

## Migration Plan

1. **数据库迁移**：Alembic migration 新增 3 列（`source_file_path`、`source_filename`、`source_type`），均为可空或有默认值，不锁表
2. **依赖安装**：`pip install -e ".[parsers]"` 或 Dockerfile 增加 `parsers` extra
3. **配置**：`.env` 新增 `DOCUMENT_STORAGE_PATH` 和 `DOCUMENT_MAX_SIZE_MB`，均有合理默认值
4. **部署顺序**：先跑 migration → 部署新代码 → 前端更新
5. **回滚**：新增字段可空，旧代码忽略新字段无影响；移除 parsers extra 后回退到仅 .md/.txt 行为

## Open Questions

- mammoth 对中文「标题 1/2」样式的转换准确率？（需用真实文档实测）
- PDF 多栏排版的处理策略？（本期不做特殊处理，按页抽取文字）
- 是否需要文件清理的定时任务？（本期暂不，后续迭代考虑）
