# RAGNexus 第一期骨架 — 工程规范

> **第一期目标**：清晰、轻量、可执行的 RAG 中台骨架（纯向量检索版）。
> - 3 个核心接口（Google `:` 语法）
> - 第一期：**纯向量检索**（pgvector）
> - 同步索引（请求阻塞直到完成）
> - 返回检索增强结果，**不生成最终答案**
> - 架构层留好扩展点（向量库切换 / BM25+混合 / rerank / 异步任务 / 权限 / 评测 / 本地 Embedder）

---

## Context

`RAGNexus` 是一个 RAG 中台，从零起步。本规范定义**第一期骨架**：

- 3 个 HTTP 接口（创建 KB / 上传文档 / 检索）
- **第一期只做向量检索**（pgvector + OpenAI 兼容 Embedder）
- BM25、混合检索、rerank、LLM、异步任务、权限、评测 **全部推到第二期**（架构层留好接口）
- 同步索引、硬删除、Docker Compose 一键拉起

**预期产出**：`docker compose up`（推荐）→ 3 个接口在 `/docs` 可调；或 `git clone` → 装 pgvector → 跑 `schema.sql` → `uv pip install -e ".[dev]"` → `pytest` 跑通 → `uv run main.py` 起服务。

---

## 1. 三个核心接口

> 路径风格：**Google `:` 语法**（名词 : 动作），HTTP 动词全用 `POST`。
> 字段命名：**snake_case**。时间：**ISO 8601**（UTC + 毫秒）。

### 1.1 `POST /v1/knowledge-bases:create`

| | |
|---|---|
| 请求 | `application/json`：`{ "name": "产品手册 v1" }` |
| 成功（200）| `{ "code": 0, "data": { "kb_id": "kb_abc12345", "name": "产品手册 v1", "created_at": "2026-06-22T10:00:00.000Z" }, "message": "ok" }` |
| 失败（409）| `{ "code": 1200, "message": "知识库名称已存在", "errors": [{"field": "name", "reason": "..."}] }` |
| 失败（422）| name 为空或超长（1-64 字符） |

### 1.2 `POST /v1/documents:upload`

| | |
|---|---|
| 请求 | `multipart/form-data`：表单字段 `kb_id` + 文件 `file`（`.md` 或 `.txt`），文件大小 ≤ 10MB |
| 成功（201）| `{ "code": 0, "data": { "doc_id": "doc_<hash16>", "kb_id": "kb_abc12345", "chunk_count": 12 }, "message": "ok" }` |
| 失败（404）| `kb_id` 不存在 |
| 失败（409）| 同 doc_id（文件 SHA-256 前 16 位）已存在 |
| 失败（413）| 文件 > 10MB |
| 失败（415）| 文件后缀不是 .md / .txt |
| 失败（422）| 文件为空 / 解析失败 / 多余字段 |

> **同步索引**：`POST` 请求阻塞到所有 chunk 写入 pgvector 才返回。
> **doc_id 策略**：取文件 SHA-256 hash 前 16 位 → 同文件 = 同 doc_id = 409。
> **响应里没有 chunks 列表**（收敛，调用方要查自己调 retrieve）。

### 1.3 `POST /v1/rag:retrieve`

| | |
|---|---|
| 请求 | `application/json`：`{ "query": "产品保修期多久", "kb_ids": ["kb_abc12345"], "top_k": 5 }` |
| 成功（200）| `{ "code": 0, "data": { "total": 3, "hits": [{ "chunk_id": "doc_xyz:3", "kb_id": "kb_abc12345", "doc_id": "doc_xyz", "score": 0.823456, "text": "...", "metadata": {} }] }, "message": "ok" }` |
| 失败（404）| 任意 `kb_id` 不存在 |
| 失败（422）| query 空 / kb_ids 空 / top_k 越界 / 多余字段 |

> **范围**：`kb_ids` 数组 1-5 个 KB；空 → 422。
> **评分**：向量余弦相似度（pgvector `<=>` 距离，**1 - 距离**即 score），6 位小数，**越大越相关**。
> **`filter` 字段**：**完全禁止**（不在 schema 中，传了 → 422，强制 strict 模式）。
> **跨 KB 合并策略**（内部实现）：第一期**全局 top_k**（简单，可接受偏置）。

### 1.4 错误码表

| 码 | HTTP | 含义 |
|---|---|---|
| 0 | 200 | 成功 |
| 1000 | 422 | 参数错误 |
| 1100 | 404 | KB 不存在 |
| 1200 | 409 | KB 重名 |
| 1201 | 409 | doc_id 重复 |
| 1300 | 415 | 文件类型不支持 |
| 1301 | 413 | 文件过大（>10MB）|
| 1400 | 422 | 文件为空 |
| 1500 | 502 | Embedder 失败 |
| 1501 | 502 | 向量库失败 |
| 9999 | 500 | 内部错误 |

`message` 固定中文文案，与 code 绑死。错误响应格式：

```json
{
  "code": 1100,
  "data": null,
  "message": "知识库不存在",
  "errors": [{"field": "kb_id", "reason": "kb_abc 不存在"}]
}
```

**没有 `request_id`**（骨架收敛掉）。

---

## 2. 技术栈

| 类别 | 选择 | 理由 |
|---|---|---|
| **语言** | Python 3.11 | 稳定，主流库全支持 |
| **包管理** | uv | 10-100x 快于 pip，2026 事实标准 |
| **Web 框架** | FastAPI | 异步友好，自动 OpenAPI |
| **ASGI** | uvicorn | FastAPI 标配 |
| **数据验证** | pydantic v2 | FastAPI 同门 |
| **配置** | pydantic-settings | 读 .env |
| **HTTP 客户端** | httpx | 异步调 Embedder |
| **Postgres 驱动** | asyncpg | 异步连接 |
| **向量类型** | pgvector | Python 绑定 |
| **ID 生成** | nanoid | 短而安全 |
| **测试** | pytest + pytest-asyncio | 标准 |

**不引入**：LangChain / LlamaIndex、SQLAlchemy、BM25 库、jieba。

---

## 3. 架构与目录

### 3.1 六边形架构

业务代码（`application/`、`domain/`）**不 import 任何 `adapters/`**。所有依赖通过 `composition.py` 注入。

### 3.2 目录结构

```
RAGNexus/
├── domain/                              # 纯业务
│   ├── models.py                        # KnowledgeBase, Chunk, SearchHit, Section, ParsedDocument
│   ├── ports.py                         # VectorStorePort, EmbedderPort, KnowledgeBasePort, ParserPort, RetrieveLogPort
│   ├── errors.py                        # DomainError + 11 个子类（带 code + http_status）
│   └── chunking.py                      # heading_aware_split + fixed_size_split
│
├── application/                         # 业务用例
│   ├── create_kb_use_case.py
│   ├── upload_doc_use_case.py
│   └── retrieve_use_case.py             # 注入 embedder, store, log_port
│
├── adapters/                            # 外部世界实现
│   ├── http/                            # 入站（FastAPI）
│   │   ├── create_kb_router.py
│   │   ├── upload_doc_router.py
│   │   ├── retrieve_router.py
│   │   └── error_handlers.py            # 全局 exception_handler
│   ├── vector_store/                    # 出站：pgvector
│   │   ├── pgvector.py
│   │   └── registry.py
│   ├── knowledge_base/                  # 出站：pg
│   │   └── pg.py
│   ├── embedder/                        # 出站：OpenAI 兼容
│   │   └── openai_compat.py
│   ├── parsers/                         # 出站：md/txt
│   │   └── md_and_txt.py
│   └── retrieve_log/                    # 出站：pg
│       └── pg.py
│
├── tests/
│   ├── conftest.py
│   ├── unit/                            # use case + domain，mock 全部
│   │   ├── domain/
│   │   ├── application/
│   │   └── adapters/
│   ├── integration/                     # 真实 pgvector + mock embedder
│   │   ├── conftest.py
│   │   ├── test_pg_vector_store.py
│   │   ├── test_pg_kb_repo.py
│   │   ├── test_documents_table.py
│   │   └── test_retrieve_log.py
│   └── e2e/                             # 端到端（替代 scripts/smoke.py）
│       └── test_smoke.py
│
├── docs/
│   └── sql/
│       └── schema.sql
│
├── config.py                            # pydantic-settings
├── composition.py                       # 唯一装配点
├── main.py                              # uvicorn 入口
├── pyproject.toml
├── .env.example
├── Dockerfile                       # python:3.11-slim + uv（无 [dev]）
├── docker-compose.yml               # db + init-db + app 编排
├── docker-compose.test.yml          # test-db + test-init 编排
├── .dockerignore                    # 排除 .env / docs/ / __pycache__
├── .gitignore
└── README.md
```

> 每个 Python 包目录的 `__init__.py` 默认存在。

---

## 4. Domain 模型

```python
# domain/models.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

class KnowledgeBase:
    id: str                # "kb_" + nanoid(8)
    name: str              # 用户输入
    created_at: datetime

@dataclass
class Section:
    heading: str | None    # None 表示无标题（开头游离内容也算）
    level: int             # 1-6，0 表示无标题
    content: str

@dataclass
class ParsedDocument:
    filename: str
    sections: list[Section]
    raw_text: str          # 全量文本（回退切分用）

@dataclass
class Chunk:
    id: str                # "{doc_id}:{index}"
    kb_id: str
    doc_id: str
    text: str
    vector: list[float]    # 长度 == EMBED_DIM
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata 第一期：chunk 级 {chunk_index, heading, heading_level} + doc 级 {filename, file_hash, file_size, content_type}

@dataclass
class SearchHit:
    chunk_id: str
    kb_id: str
    doc_id: str
    score: float           # 越大越相关（1 - cosine distance）
    text: str
    metadata: dict[str, Any]

@dataclass
class UploadResult:
    doc_id: str
    kb_id: str
    chunks: list[Chunk]    # use case 内部用，router 只取 chunk_count
```

---

## 5. Ports（接口合同）

```python
# domain/ports.py
from typing import Protocol
from ragnexus.domain.models import KnowledgeBase, Chunk, SearchHit, ParsedDocument

class VectorStorePort(Protocol):
    """向量存储 + 检索。骨架实现: pgvector。"""
    async def upsert(self, kb_id: str, chunks: list[Chunk]) -> None: ...
    async def search_by_vector(
        self, query_vector: list[float], top_k: int, kb_ids: list[str],
    ) -> list[SearchHit]: ...

class KnowledgeBasePort(Protocol):
    """KB 元数据 CRUD。骨架实现: PgKnowledgeBaseRepository。"""
    async def create(self, name: str, name_key: str) -> KnowledgeBase: ...  # 重名抛 ConflictError
    async def get(self, kb_id: str) -> KnowledgeBase | None: ...
    async def exists(self, kb_id: str) -> bool: ...
    async def doc_exists(self, doc_id: str) -> bool: ...

class EmbedderPort(Protocol):
    """文本 → 向量。骨架实现: OpenAICompatEmbedder（支持通义/OpenAI/Ollama 等）。"""
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

class ParserPort(Protocol):
    """文档解析。骨架实现: MarkdownAndTextParser。"""
    def parse(self, content: bytes, filename: str) -> ParsedDocument: ...

class RetrieveLogPort(Protocol):
    """retrieve 日志（fire-and-forget）。骨架实现: PgRetrieveLogRepository。"""
    async def log(self, *, query: str, kb_ids: list[str], top_k: int,
                  hit_count: int, latency_ms: int) -> None: ...
```

### 5.1 领域异常

```python
# domain/errors.py
class DomainError(Exception):
    code: int = 9999
    http_status: int = 500
    def __init__(self, message: str | None = None, errors: list[dict] | None = None):
        super().__init__(message or self.message)
        self.message_text = message
        self.errors = errors or []

class ValidationError(DomainError):
    code, http_status, message = 1000, 422, "参数错误"

class NotFoundError(DomainError):
    code, http_status, message = 1100, 404, "资源不存在"

class ConflictError(DomainError):
    code, http_status, message = 1200, 409, "资源冲突"

class DuplicateDocumentError(ConflictError):
    code, http_status, message = 1201, 409, "文档已存在"

class UnsupportedMediaTypeError(DomainError):
    code, http_status, message = 1300, 415, "不支持的文件类型"

class PayloadTooLargeError(DomainError):
    code, http_status, message = 1301, 413, "文件过大"

class EmptyFileError(DomainError):
    code, http_status, message = 1400, 422, "文件为空"

class UpstreamError(DomainError):  # Embedder/向量库
    code, http_status, message = 1500, 502, "上游服务异常"

class VectorStoreError(UpstreamError):
    code, http_status, message = 1501, 502, "向量库失败"
```

---

## 6. 业务用例

### 6.1 CreateKnowledgeBaseUseCase

```python
class CreateKnowledgeBaseUseCase:
    def __init__(self, kb_repo: KnowledgeBasePort): ...

    async def execute(self, name: str) -> KnowledgeBase:
        name = name.strip()
        if not (1 <= len(name) <= 64):
            raise ValidationError("name 长度必须在 1-64 之间",
                                  errors=[{"field": "name", "reason": "长度必须在 1-64"}])
        name_key = name.lower()  # 双字段：name 给用户看，name_key 做 UNIQUE
        return await self.kb_repo.create(name=name, name_key=name_key)
```

### 6.2 UploadDocumentUseCase

```python
class UploadDocumentUseCase:
    def __init__(
        self,
        kb_repo: KnowledgeBasePort,
        parser: ParserPort,
        embedder: EmbedderPort,
        chunker: Callable[..., list[str]],  # (parsed, max_chars, overlap) -> list[str]
        store: VectorStorePort,
        max_file_size: int = 10 * 1024 * 1024,   # 10MB
        allowed_exts: tuple = (".md", ".txt"),
        chunk_max_chars: int = 1500,
        chunk_overlap: int = 50,
    ): ...

    async def execute(self, kb_id: str, file_bytes: bytes, filename: str) -> UploadResult:
        # 1. 文件大小
        if len(file_bytes) > self.max_file_size:
            raise PayloadTooLargeError(...)
        # 2. 文件类型
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in self.allowed_exts:
            raise UnsupportedMediaTypeError(...)
        # 3. KB 存在
        if not await self.kb_repo.exists(kb_id):
            raise NotFoundError(f"知识库不存在", errors=[{"field": "kb_id", "reason": f"{kb_id} 不存在"}])
        # 4. 算 doc_id + file_hash
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        doc_id = "doc_" + file_hash[:16]
        if await self.kb_repo.doc_exists(doc_id):
            raise DuplicateDocumentError(f"文档已存在", errors=[{"field": "doc_id", "reason": f"{doc_id} 已存在"}])
        # 5. 解析 + 切分
        parsed = self.parser.parse(file_bytes, filename)
        if not parsed.sections and not parsed.raw_text:
            raise EmptyFileError(...)
        texts = self.chunker(parsed, max_chars=self.chunk_max_chars, overlap=self.chunk_overlap)
        if not texts:
            raise EmptyFileError(...)
        # 6. Embedding（concurrent 5, batch 50, 429 重试 3 次）
        vectors = await self.embedder.embed(texts)
        # 7. 构造 Chunk
        common_meta = {
            "filename": filename,
            "file_hash": file_hash,
            "file_size": len(file_bytes),
            "content_type": "text/markdown" if filename.lower().endswith(".md") else "text/plain",
        }
        chunks = [
            Chunk(
                id=f"{doc_id}:{i}", kb_id=kb_id, doc_id=doc_id,
                text=t, vector=v,
                metadata={**common_meta, "chunk_index": i, "heading": ..., "heading_level": ...},
            )
            for i, (t, v) in enumerate(zip(texts, vectors))
        ]
        # 8. 事务写入（documents + chunks）
        await self.store.upsert(kb_id, chunks)
        return UploadResult(doc_id=doc_id, kb_id=kb_id, chunks=chunks)
```

### 6.3 RetrieveUseCase

```python
class RetrieveUseCase:
    def __init__(
        self,
        embedder: EmbedderPort,
        store: VectorStorePort,
        kb_repo: KnowledgeBasePort,
        log_port: RetrieveLogPort,
    ): ...

    async def execute(
        self, query: str, kb_ids: list[str], top_k: int = 5
    ) -> list[SearchHit]:
        # 1. 校验
        if not query.strip() or len(query) > 2000:
            raise ValidationError(...)
        if not kb_ids or len(kb_ids) > 5:
            raise ValidationError(...)
        if not (1 <= top_k <= 50):
            raise ValidationError(...)
        # 2. 校验所有 KB 存在
        for kb_id in kb_ids:
            if not await self.kb_repo.exists(kb_id):
                raise NotFoundError(...)

        # 3. 检索
        t0 = time.perf_counter()
        try:
            vectors = await self.embedder.embed([query])
            hits = await self.store.search_by_vector(vectors[0], top_k, kb_ids)
            return hits
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            hit_count = len(hits) if "hits" in dir() else 0
            asyncio.create_task(self._safe_log(query, kb_ids, top_k, hit_count, latency_ms))

    async def _safe_log(self, query, kb_ids, top_k, hit_count, latency_ms):
        try:
            await self.log_port.log(query=query, kb_ids=kb_ids, top_k=top_k,
                                    hit_count=hit_count, latency_ms=latency_ms)
        except Exception:
            pass
```

> 日志用 `asyncio.create_task` 异步写，**不阻塞响应**。日志失败被吞掉，不影响主流程。
> （第一期接受"请求结束后日志可能没写完"的风险，第二期用 task queue 改进。）

---

## 7. 切分（`domain/chunking.py`）

```python
def heading_aware_split(parsed: ParsedDocument, max_chars: int = 1500, overlap: int = 50) -> list[str]:
    """按 # 标题切；单段超 max_chars 时回退固定字符重叠切；过滤空 chunk。"""
    if not any(s.heading for s in parsed.sections):
        return [c for c in fixed_size_split(parsed.raw_text, max_chars, overlap) if c.strip()]

    pieces: list[str] = []
    for s in parsed.sections:
        text = (f"# {s.heading}\n\n" if s.heading else "") + s.content
        if len(text) <= max_chars:
            pieces.append(text)
        else:
            pieces.extend(fixed_size_split(text, max_chars, overlap))
    return [p for p in pieces if p.strip()]

def fixed_size_split(text: str, max_chars: int, overlap: int) -> list[str]:
    if not text: return []
    step = max_chars - overlap
    return [text[i:i+max_chars] for i in range(0, max(len(text), 1), step)]
```

---

## 8. Adapter 实现要点

### 8.1 OpenAICompatEmbedder

```python
class OpenAICompatEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str, dim: int,
                 batch_size: int = 50, max_concurrency: int = 5, max_retries: int = 3,
                 request_timeout: float = 30.0, connect_timeout: float = 5.0,
                 retry_backoff_base: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.api_key, self.model, self.dim = api_key, model, dim
        self.batch_size = batch_size
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.request_timeout = request_timeout
        self.connect_timeout = connect_timeout
        self.retry_backoff_base = retry_backoff_base
        self._client: httpx.AsyncClient | None = None
        self._sem = asyncio.Semaphore(max_concurrency)

    async def _ensure_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.request_timeout, connect=self.connect_timeout))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts: return []
        await self._ensure_client()
        # 切批
        batches = [texts[i:i+self.batch_size] for i in range(0, len(texts), self.batch_size)]

        async def embed_one_batch(batch: list[str]) -> list[list[float]]:
            async with self._sem:
                for attempt in range(self.max_retries):
                    try:
                        r = await self._client.post(
                            f"{self.base_url}/embeddings",
                            headers={"Authorization": f"Bearer {self.api_key}"},
                            json={"model": self.model, "input": batch},
                        )
                        if r.status_code == 429 and attempt < self.max_retries - 1:
                            await asyncio.sleep(self.retry_backoff_base ** attempt)
                            continue
                        r.raise_for_status()
                        return [item["embedding"] for item in r.json()["data"]]
                    except httpx.HTTPError as e:
                        if attempt == self.max_retries - 1:
                            raise UpstreamError(f"Embedder 失败: {e}")
                        await asyncio.sleep(self.retry_backoff_base ** attempt)

        # 并发跑
        results = await asyncio.gather(*[embed_one_batch(b) for b in batches])
        flat = [v for batch in results for v in batch]
        # 校验维度
        for v in flat:
            if len(v) != self.dim:
                raise RuntimeError(f"embed dim 失配: 期望 {self.dim}, 实际 {len(v)}")
        return flat
```

**切厂商只改 `.env`**：

```env
# 通义
EMBED_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBED_MODEL=text-embedding-v3
EMBED_DIM=1024

# OpenAI
EMBED_BASE_URL=https://api.openai.com/v1
EMBED_MODEL=text-embedding-3-small
EMBED_DIM=1536

# 本地 Ollama（你的 4060）
EMBED_BASE_URL=http://localhost:11434/v1
EMBED_API_KEY=ollama
EMBED_MODEL=bge-large-zh-v1.5
EMBED_DIM=1024
```

### 8.2 PgVectorStore

```python
import asyncpg
import json
from pgvector.asyncpg import register_vector

class PgVectorStore:
    def __init__(self, dsn: str, dim: int, pool_min: int = 1, pool_max: int = 10,
                 command_timeout: float = 30.0):
        self.dsn, self.dim = dsn, dim
        self.pool: asyncpg.Pool | None = None
        self.pool_min, self.pool_max = pool_min, pool_max
        self.command_timeout = command_timeout

    async def connect(self):
        async def _init_conn(conn):
            await register_vector(conn)
        self.pool = await asyncpg.create_pool(
            self.dsn, min_size=self.pool_min, max_size=self.pool_max,
            command_timeout=self.command_timeout,
            init=_init_conn,
        )

    async def close(self):
        if self.pool: await self.pool.close()

    async def upsert(self, kb_id: str, chunks: list[Chunk]) -> None:
        doc_id = chunks[0].doc_id   # 不变量：一次 upsert 一个 doc
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # 1. 查重（应用层 + UNIQUE 双保险）
                exists = await conn.fetchval("SELECT 1 FROM chunks WHERE doc_id = $1 LIMIT 1", doc_id)
                if exists:
                    raise DuplicateDocumentError(f"doc_id={doc_id} 已存在",
                                        errors=[{"field": "doc_id", "reason": f"{doc_id} 已存在"}])
                # 2. 插入 documents
                first = chunks[0]
                await conn.execute(
                    """INSERT INTO documents (doc_id, kb_id, filename, file_hash, file_size,
                                              content_type, chunk_count)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)
                       ON CONFLICT (doc_id) DO NOTHING""",
                    first.doc_id, first.kb_id, first.metadata.get("filename", ""),
                    first.metadata.get("file_hash", ""), first.metadata.get("file_size", 0),
                    first.metadata.get("content_type"), len(chunks),
                )
                # 3. 批量插入 chunks
                await conn.executemany(
                    """INSERT INTO chunks (id, kb_id, doc_id, text, metadata, embedding)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    [(c.id, c.kb_id, c.doc_id, c.text, json.dumps(c.metadata), c.vector) for c in chunks],
                )

    async def search_by_vector(
        self, query_vector: list[float], top_k: int, kb_ids: list[str]
    ) -> list[SearchHit]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, kb_id, doc_id, text, metadata,
                          1 - (embedding <=> $1) AS score
                   FROM chunks
                   WHERE kb_id = ANY($2)
                   ORDER BY embedding <=> $1
                   LIMIT $3""",
                query_vector, kb_ids, top_k,
            )
        return [
            SearchHit(
                chunk_id=r["id"], kb_id=r["kb_id"], doc_id=r["doc_id"],
                score=float(r["score"]), text=r["text"],
                metadata=json.loads(r["metadata"]),
            )
            for r in rows
        ]
```

### 8.3 PgKnowledgeBaseRepository

```python
class PgKnowledgeBaseRepository:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create(self, name: str, name_key: str) -> KnowledgeBase:
        kb_id = "kb_" + nanoid.generate(size=8)
        try:
            row = await self.pool.fetchrow(
                "INSERT INTO knowledge_bases (id, name, name_key) VALUES ($1, $2, $3) RETURNING id, name, created_at",
                kb_id, name, name_key,
            )
        except asyncpg.UniqueViolationError:
            raise ConflictError(f"知识库名称已存在",
                                errors=[{"field": "name", "reason": f"{name!r} 已存在"}])
        return KnowledgeBase(id=row["id"], name=row["name"], created_at=row["created_at"])

    async def get(self, kb_id: str) -> KnowledgeBase | None:
        row = await self.pool.fetchrow("SELECT id, name, created_at FROM knowledge_bases WHERE id=$1", kb_id)
        return KnowledgeBase(**dict(row)) if row else None

    async def exists(self, kb_id: str) -> bool:
        return bool(await self.pool.fetchval("SELECT 1 FROM knowledge_bases WHERE id=$1", kb_id))

    async def doc_exists(self, doc_id: str) -> bool:
        return bool(await self.pool.fetchval("SELECT 1 FROM documents WHERE doc_id=$1", doc_id))
```

### 8.4 MarkdownAndTextParser

```python
import re
from ragnexus.domain.models import Section, ParsedDocument

class MarkdownAndTextParser:
    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        text = content.decode("utf-8", errors="replace")
        if filename.lower().endswith(".md"):
            return self._parse_markdown(text, filename)
        return ParsedDocument(filename=filename, sections=[], raw_text=text)

    def _parse_markdown(self, text: str, filename: str) -> ParsedDocument:
        sections: list[Section] = []
        current_heading: str | None = None
        current_level: int = 0
        buffer: list[str] = []
        for line in text.splitlines():
            m = re.match(r"^(#{1,6})\s+(.+)$", line)
            if m:
                # 切换标题前，先 flush 当前 section
                if buffer or current_heading is not None:
                    sections.append(Section(current_heading, current_level, "\n".join(buffer).strip()))
                current_level = len(m.group(1))
                current_heading = m.group(2).strip()
                buffer = []
            else:
                buffer.append(line)
        # 文件结尾的最后一个 section
        if buffer or current_heading is not None:
            sections.append(Section(current_heading, current_level, "\n".join(buffer).strip()))
        # 过滤完全空的 section（单标题无内容）
        sections = [s for s in sections if s.content or s.heading]
        return ParsedDocument(filename=filename, sections=sections, raw_text=text)
```


### 8.5 PgRetrieveLogRepository

```python
import asyncpg

class PgRetrieveLogRepository:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def log(self, *, query: str, kb_ids: list[str], top_k: int,
                  hit_count: int, latency_ms: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO retrieve_logs (kb_ids, query, top_k, hit_count, latency_ms)
                   VALUES ($1, $2, $3, $4, $5)""",
                kb_ids, query, top_k, hit_count, latency_ms,
            )
```

### 8.6 HTTP Router（工厂函数 + 严格模式）

```python
# adapters/http/retrieve_router.py
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from ragnexus.application.retrieve_use_case import RetrieveUseCase

class RetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 严格模式
    query: str = Field(..., min_length=1, max_length=2000)
    kb_ids: list[str] = Field(..., min_length=1, max_length=5)
    top_k: int = Field(default=5, ge=1, le=50)

def retrieve_router(uc: RetrieveUseCase) -> APIRouter:
    r = APIRouter()
    @r.post("/v1/rag:retrieve")
    async def retrieve(req: RetrieveRequest) -> dict:
        hits = await uc.execute(req.query, req.kb_ids, req.top_k)
        return {
            "code": 0, "message": "ok",
            "data": {"total": len(hits), "hits": [h.__dict__ for h in hits]},
        }
    return r
```

### 8.7 全局错误处理

```python
# adapters/http/error_handlers.py
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from ragnexus.domain.errors import DomainError

def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request, exc: DomainError):
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "code": exc.code,
                "data": None,
                "message": exc.message_text or exc.__class__.message,
                "errors": exc.errors,
            },
        )
```

### 8.8 集中装配（`composition.py`）

```python
from contextlib import asynccontextmanager
import logging
from ragnexus.domain.errors import ConfigError
from fastapi import FastAPI
from ragnexus.config import get_settings
from ragnexus.application.create_kb_use_case import CreateKnowledgeBaseUseCase
from ragnexus.application.upload_doc_use_case import UploadDocumentUseCase
from ragnexus.application.retrieve_use_case import RetrieveUseCase
from ragnexus.domain.chunking import heading_aware_split
from ragnexus.adapters.vector_store.pgvector import PgVectorStore
from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder
from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
from ragnexus.adapters.retrieve_log.pg import PgRetrieveLogRepository
from ragnexus.adapters.http.create_kb_router import create_kb_router
from ragnexus.adapters.http.upload_doc_router import upload_doc_router
from ragnexus.adapters.http.retrieve_router import retrieve_router
from ragnexus.adapters.http.error_handlers import register_error_handlers

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    store = PgVectorStore(cfg.PG_DSN, cfg.EMBED_DIM, cfg.PG_POOL_MIN, cfg.PG_POOL_MAX, command_timeout=cfg.PG_COMMAND_TIMEOUT)
    logging.basicConfig(level=cfg.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s | %(message)s", datefmt="%H:%M:%S")
    await store.connect()

    # EMBED_DIM 维度失配检测
    actual_dim = await store.pool.fetchval("""
        SELECT atttypmod FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relname = 'chunks' AND a.attname = 'embedding'
    """)
    if actual_dim not in (-1, cfg.EMBED_DIM):
        raise ConfigError(
            f"chunks.embedding 是 vector({actual_dim})，但 EMBED_DIM={cfg.EMBED_DIM}。请重跑 docs/sql/schema.sql",
            errors=[{"field": "EMBED_DIM", "reason": f"实际维度 {actual_dim} 与配置 {cfg.EMBED_DIM} 不一致"}],
        )

    app.state.store = store

    # 装配依赖并注入路由
    kb_repo = PgKnowledgeBaseRepository(store.pool)
    embedder = OpenAICompatEmbedder(
        base_url=cfg.EMBED_BASE_URL, api_key=cfg.EMBED_API_KEY,
        model=cfg.EMBED_MODEL, dim=cfg.EMBED_DIM,
        batch_size=cfg.EMBED_BATCH_SIZE, max_concurrency=cfg.EMBED_MAX_CONCURRENCY,
        max_retries=cfg.EMBED_MAX_RETRIES,
        request_timeout=cfg.EMBED_REQUEST_TIMEOUT, connect_timeout=cfg.EMBED_CONNECT_TIMEOUT,
        retry_backoff_base=cfg.EMBED_RETRY_BACKOFF_BASE,
    )
    log_repo = PgRetrieveLogRepository(store.pool)
    parser = MarkdownAndTextParser()

    app.include_router(create_kb_router(CreateKnowledgeBaseUseCase(kb_repo)))
    app.include_router(upload_doc_router(UploadDocumentUseCase(
        kb_repo=kb_repo, parser=parser, embedder=embedder,
        chunker=heading_aware_split, store=store,
        max_file_size=cfg.MAX_FILE_SIZE, chunk_max_chars=cfg.CHUNK_MAX_CHARS, chunk_overlap=cfg.CHUNK_OVERLAP,
    )))
    app.include_router(retrieve_router(RetrieveUseCase(
        embedder=embedder, store=store, kb_repo=kb_repo, log_port=log_repo,
    )))

    yield
    await store.close()

def build_app() -> FastAPI:
    app = FastAPI(title="RAGNexus", lifespan=lifespan)
    register_error_handlers(app)
    return app
```

### 8.9 main.py

```python
import uvicorn
from ragnexus.config import get_settings

if __name__ == "__main__":
    cfg = get_settings()
    uvicorn.run("ragnexus.composition:build_app", factory=True, host=cfg.HOST, port=cfg.PORT)
```

---

## 9. 配置（`config.py` + `.env.example`）

```python
# config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    PG_DSN: str = "postgresql://ragnexus:ragnexus@localhost:5432/ragnexus"
    PG_POOL_MIN: int = 1
    PG_POOL_MAX: int = 10
    EMBED_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBED_API_KEY: str = ""
    EMBED_MODEL: str = "text-embedding-v3"
    EMBED_DIM: int = 1024
    EMBED_BATCH_SIZE: int = 50
    EMBED_MAX_CONCURRENCY: int = 5
    EMBED_MAX_RETRIES: int = 3
    CHUNK_MAX_CHARS: int = 1500
    CHUNK_OVERLAP: int = 50
    MAX_FILE_SIZE: int = 10 * 1024 * 1024
    EMBED_REQUEST_TIMEOUT: float = 30.0
    EMBED_CONNECT_TIMEOUT: float = 5.0
    EMBED_RETRY_BACKOFF_BASE: float = 2.0
    PG_COMMAND_TIMEOUT: float = 30.0
```
```env
# .env.example
PG_DSN=postgresql://ragnexus:ragnexus@localhost:5432/ragnexus
PG_POOL_MIN=1
PG_POOL_MAX=10

EMBED_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBED_API_KEY=sk-your-key
EMBED_MODEL=text-embedding-v3
EMBED_DIM=1024
EMBED_BATCH_SIZE=50
EMBED_MAX_CONCURRENCY=5
EMBED_MAX_RETRIES=3

CHUNK_MAX_CHARS=1500
CHUNK_OVERLAP=50
MAX_FILE_SIZE=10485760  # 10MB
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO
EMBED_REQUEST_TIMEOUT=30
EMBED_CONNECT_TIMEOUT=5
EMBED_RETRY_BACKOFF_BASE=2
PG_COMMAND_TIMEOUT=30
```

---

## 10. pgvector Schema（`docs/sql/schema.sql`）

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    name_key    TEXT UNIQUE NOT NULL,             -- TRIM(LOWER(name))，做唯一约束
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    kb_id         TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    file_hash     TEXT NOT NULL,                   -- 完整 SHA-256
    file_size     INTEGER NOT NULL,
    content_type  TEXT,
    chunk_count   INTEGER NOT NULL,
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT NOT NULL,                    -- "{doc_id}:{index}"
    kb_id       TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    doc_id      TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding   vector(1024) NOT NULL,            -- 必须跟 .env EMBED_DIM 一致
    PRIMARY KEY (doc_id, id)                      -- 复合主键（防同 doc_id 同 index 重复）
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_kb_id_idx     ON chunks (kb_id);
CREATE INDEX IF NOT EXISTS chunks_doc_id_idx    ON chunks (doc_id);
CREATE INDEX IF NOT EXISTS documents_kb_id_idx  ON documents (kb_id);
CREATE INDEX IF NOT EXISTS documents_uploaded_at_idx ON documents (uploaded_at DESC);

CREATE TABLE IF NOT EXISTS retrieve_logs (
    id           BIGSERIAL PRIMARY KEY,
    kb_ids       TEXT[] NOT NULL,
    query        TEXT NOT NULL,
    top_k        INTEGER NOT NULL,
    hit_count    INTEGER NOT NULL,
    latency_ms   INTEGER NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS retrieve_logs_created_at_idx ON retrieve_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS retrieve_logs_kb_ids_idx     ON retrieve_logs USING GIN (kb_ids);
```

> **修改 EMBED_DIM 必须先 DROP chunks 重建**（vector 维度绑在 schema 里）。

---

## 11. 依赖（`pyproject.toml`）

```toml
[project]
name = "ragnexus"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.27",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "httpx>=0.27",
  "asyncpg>=0.29",
  "pgvector>=0.3",
  "nanoid>=2.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
]
```

---

## 12. 业务流程

### 12.1 创建知识库

1. 用户 POST JSON `{name}`
2. router 校验 name（1-64 字符）
3. use case 计算 `name_key = name.lower().strip()`
4. repository INSERT 到 `knowledge_bases`（重名 → UNIQUE 冲突 → 409）
5. 响应 `{kb_id, name, created_at}`

### 12.2 上传文档

1. 用户 POST multipart `kb_id + file`
2. router 校验 kb_id 格式，file 大小 ≤ 10MB，后缀 .md/.txt
3. use case：
   - 校验 KB 存在（404）
   - 计算 `doc_id = SHA256(file)[:16]`
   - **查重**（`kb_repo.doc_exists(doc_id)` → 409，避免浪费解析+Embedding）
   - 解析 + 切分（heading_aware，chunk_max_chars=1500, chunk_overlap=50，可由 .env 配置）
   - 过滤空 chunk
   - 调 embedder（batch=50, concurrency=5, 429 重试 3 次）
   - 事务内：INSERT documents + INSERT chunks（重复 doc_id → 409）
4. 响应 `{doc_id, kb_id, chunk_count}`

### 12.3 检索

1. 用户 POST JSON `{query, kb_ids, top_k}`
2. router 校验字段
3. use case：
   - 校验所有 kb_ids 存在（任一不存在 → 404）
   - 计时 t0
   - embedder.embed([query])
   - store.search_by_vector(vec, top_k, kb_ids) → list[SearchHit]
   - `finally`：异步 fire-and-forget 写 retrieve_log
4. 响应 `{total, hits[]}`

---

## 13. 6 个扩展点

| 扩展点 | 预留位置 | 加新实现要做什么 |
|---|---|---|
| **BM25 / 混合检索** | `VectorStorePort` 或新 `HybridSearchStore`（组合两个 Port）| 新建 `bm25.py`，RRF 融合；不动 use case 签名 |
| **新向量库**（Milvus / Qdrant）| `adapters/vector_store/` | 新建 `milvus.py`，实现 Port，registry.py 加一行 |
| **异步任务**（重型 ingest 离线化）| `UploadDocumentUseCase.execute` 末尾 | `await self.store.upsert(...)` 换成 `enqueue(...)`；引入 arq/celery |
| **Rerank** | `RetrieveUseCase.execute` search 后 | 插入 `await self.reranker.rerank(query, hits)`，加 `RerankerPort` |
| **权限** | FastAPI `Depends(auth)` | 中间件验证；KB 加 `owner_id` 列 |
| **评测** | `scripts/eval.py` | 不动业务，新增评测脚本调用 `RetrieveUseCase` |
| **本地 Embedder** | `EmbedderPort` | 新建 `bge_local.py`（用 sentence-transformers）；OpenAI 实现仍保留 |
| **`filter` 字段** | `VectorStorePort.search_by_vector` | schema 加 `filter: dict \| None = None`，use case 透传；adapter 实现 metadata 过滤 |

**关键约束**：以上扩展**不改 use case 方法签名**。要改签名 = 拆版本。

---

## 14. 不在第一期范围

- 删除接口（删 KB / 删文档）—— 推到第二期
- BM25 / 关键词检索
- 混合检索（BM25 + 向量融合）
- LLM / Rerank
- 异步任务队列（重型 ingest 离线化）
- 多租户、鉴权、API Key
- 评测脚本
- 监控 / 链路追踪
- 切分算法的 Port 抽象（heading_aware 写死）
- Parser 多格式（PDF / Word / HTML）
- `filter` 字段实现（接口预留但禁止传）
- 列表/更新文档的端点
- 部署运维细节（进程管理、环境分层、CI）

---

## 15. 部署与验证


### 15.0 Docker Compose 部署（推荐）

一条 `docker compose up` 拉起 PostgreSQL + pgvector + 应用：

**Dockerfile**（单阶段，运行时不含 dev 依赖）：
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml .
RUN uv pip install --system -e "."
COPY . .
EXPOSE 8000
CMD ["uv", "run", "main.py"]
```

**docker-compose.yml**（db + init-db 一次性服务 + app）：
```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: ragnexus
      POSTGRES_USER: ragnexus
      POSTGRES_PASSWORD: ragnexus
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ragnexus -d ragnexus"]
      interval: 2s
      timeout: 3s
      retries: 30

  init-db:
    image: postgres:16
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./docs/sql/schema.sql:/schema.sql:ro
    entrypoint: ["sh", "-c"]
    command: ["psql postgresql://ragnexus:ragnexus@db:5432/ragnexus -f /schema.sql"]
    restart: "no"

  app:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      init-db:
        condition: service_completed_successfully

volumes:
  pgdata:
```

**.dockerignore**（避免镜像膨胀 + 排除 .env 密钥）：
```
.git
.venv
__pycache__
*.pyc
.env
.pytest_cache
docs/
```

> **关键约束**（不满足则初始化失败）：
> 1. **schema 幂等性**：`init-db` 每次 `docker compose up` 都会跑 `psql -f /schema.sql`，§10 所有 DDL 已使用 `IF NOT EXISTS`
> 2. **`.env` 覆盖 `PG_DSN`**：Compose 内 DNS 把 `db` 解析为目标，`.env` 应写 `PG_DSN=postgresql://ragnexus:ragnexus@db:5432/ragnexus`
> 3. **测试在主机跑**：`uv run pytest` 不放在容器内（镜像无 `[dev]` 依赖，保持精简）

### 15.1 安装 Postgres + pgvector（一次性，手动）

**macOS**：
```bash
brew install postgresql@16
brew services start postgresql@16
psql postgres -c "CREATE DATABASE ragnexus;"
psql ragnexus -c "CREATE EXTENSION vector;"
psql ragnexus < docs/sql/schema.sql
```

**Ubuntu**：
```bash
sudo apt install postgresql-16 postgresql-16-pgvector
sudo -u postgres psql -c "CREATE DATABASE ragnexus;"
sudo -u postgres psql ragnexus -c "CREATE EXTENSION vector;"
sudo -u postgres psql ragnexus < docs/sql/schema.sql
```

**Windows**：EDB Postgres + pgvector Windows 包放到 `lib/`，重启服务。

### 15.2 装项目

```bash
uv venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
cp .env.example .env             # 填 EMBED_API_KEY
```

### 15.3 跑测试

```bash
# 单测（快，不依赖 pgvector）
uv run pytest tests/unit/ -v

# 集成测（需要 pgvector）
uv run pytest tests/integration/ -v

# E2E（端到端）
uv run pytest tests/e2e/ -v

# 全部
uv run pytest -v
```

### 15.4 启动服务

```bash
uv run main.py
# → http://localhost:8000/docs （Swagger UI）
```

### 15.5 curl 三连

```bash
# 1. 创建 KB
KB=$(curl -s -X POST localhost:8000/v1/knowledge-bases:create \
  -H 'Content-Type: application/json' \
  -d '{"name":"smoke-test"}' | jq -r .data.kb_id)
echo "KB=$KB"

# 2. 上传文件
echo "# Hello\n\nThis is a test document about RAGNexus." > /tmp/test.md
curl -s -X POST localhost:8000/v1/documents:upload \
  -F "kb_id=$KB" -F "file=@/tmp/test.md"

# 3. 检索
curl -s -X POST localhost:8000/v1/rag:retrieve \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"hello\",\"kb_ids\":[\"$KB\"],\"top_k\":3}"
```

### 15.6 验收清单

按你选择的部署路径走对应清单（curl + 错误场景部分两者相同）：

#### A. Docker Compose 路径（推荐）

- [ ] `docker compose up` 退出码 0，`docker compose ps` 显示 `db` healthy、`app` running
- [ ] `curl http://localhost:8000/docs` 返回 200，Swagger 看到 3 个接口
- [ ] `.env` 填入 `EMBED_API_KEY`，`PG_DSN` 指向 `db:5432`（§15.0 约束 #2）
- [ ] `docker compose -f docker-compose.test.yml up -d` 拉起 test-db（用于集成测试）
- [ ] 在主机上 `uv pip install -e ".[dev]"` 后 `uv run pytest` 三层全过（§15.0 约束 #3）

#### B. 手动安装路径（alternative）

- [ ] Postgres + pgvector 安装成功，`docs/sql/schema.sql` 执行无报错
- [ ] `uv pip install -e ".[dev]"` 装好无报错
- [ ] `.env` 填入 `EMBED_API_KEY`（通义 key）
- [ ] `uv run pytest tests/unit/`、`tests/integration/`、`tests/e2e/` 三层全过
- [ ] `uv run main.py` 启动，`/docs` 看到 3 个接口

#### C. 端到端 curl + 错误场景（两路径都跑）

- [ ] 15.5 的 curl 三连全部返回 200/201
- [ ] 重复上传同文件 → 409
- [ ] 上传时 kb_id 不存在 → 404
- [ ] 上传 .pdf → 415
- [ ] 上传 > 10MB 文件 → 413
- [ ] retrieve 时传不存在的 kb_id → 404
- [ ] retrieve 多余字段 `filter` → 422（strict mode）

## 16. 一页速览

| 项 | 决定 |
|---|---|
| 语言 / 版本 | Python 3.11 |
| 包管理 | uv |
| Web 框架 | FastAPI + uvicorn |
| 架构 | 六边形（domain / application / adapters）|
| 3 个核心接口 | `POST /v1/knowledge-bases:create` · `POST /v1/documents:upload` · `POST /v1/rag:retrieve` |
| 路径风格 | Google `:` 语法 |
| 响应格式 | B 业务信封 `{code, data, message}` + errors 数组，snake_case，ISO 8601，6 位小数 |
| 严格模式 | 多余字段 → 422（filter 字段直接禁止）|
| 第一期检索 | 纯向量（pgvector），跨 KB 用全局 top_k |
| Embedder | OpenAI 兼容（默认通义 text-embedding-v3 1024 维；可换 Ollama 本地 BGE）|
| Embedder 参数 | batch=50, concurrency=5, 429 重试 3 次 |
| KB 重名 | 双字段（name + name_key=LOWER(TRIM(name))）|
| 切分 | heading_aware（chunk=1500, overlap=50, 过滤空）|
| 解析 | MarkdownAndTextParser（.md + .txt）|
| 错误流 | FastAPI 全局 exception_handler，领域异常带 code+http_status |
| 数据建模 | 4 张表：knowledge_bases, documents, chunks, retrieve_logs；硬删除；CASCADE |
| 资源生命周期 | asyncpg pool min=1 max=10, lifespan 优雅关闭，schema 不自动跑（缺表报错）|
| 测试 | 完整金字塔（unit + integration + e2e）|
| retrieve_log | fire-and-forget 异步写，第一期可丢失 |
| 多租户 / 鉴权 | 不在第一期 |
| Docker Compose | 第一期（推荐路径，一键启动 PG + app）|
| 依赖 | fastapi / uvicorn / pydantic / pydantic-settings / httpx / asyncpg / pgvector / nanoid + (dev) pytest / pytest-asyncio |
| 推到第二期 | BM25、混合、rerank、LLM、异步任务、权限、评测、删除接口、PDF/Word、filter 实现 |
