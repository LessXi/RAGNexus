"""领域模型 — 纯 dataclass，无框架依赖。"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any


class DocStatus(IntEnum):
    """文档索引状态枚举 — 与数据库 INTEGER 字段映射。"""

    SUCCESS = 1  # 索引成功
    PROCESSING = 2  # 索引中（默认值）
    FAILED = 3  # 索引失败


@dataclass
class KnowledgeBase:
    id: str  # "kb_" + nanoid(8)
    name: str  # user input
    created_at: datetime
    description: str = ""  # KB 描述，用于改写器 kb_context
    tenant_id: str = ""  # 租户ID，默认为空字符串（兼容旧数据）
    settings: dict = field(default_factory=dict)  # KB 级配置: synonyms、rewrite_hint 等


@dataclass
class Section:
    heading: str | None  # None means no heading
    level: int  # 1-6, 0 means no heading
    content: str


@dataclass
class ParsedDocument:
    filename: str
    sections: list[Section]
    raw_text: str  # full text for fallback splitting
    source_type: str = "text"  # 新增: text | markdown | docx | pdf
    metadata: dict = field(default_factory=dict)  # 新增: parser 元信息


@dataclass
class Chunk:
    id: str  # "{doc_id}:{index}"
    kb_id: str
    doc_id: str
    text: str
    vector: list[float]  # length == EMBED_DIM
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchHit:
    chunk_id: str
    kb_id: str
    doc_id: str
    score: float  # higher = more relevant (1 - cosine distance)
    text: str
    metadata: dict[str, Any]


@dataclass
class UploadResult:
    doc_id: str
    kb_id: str
    status: DocStatus
    chunks: list[Chunk] = field(
        default_factory=list
    )  # used internally by use case; router should use chunk_count
    chunk_count: int = 0


@dataclass
class Document:
    """文档领域模型 — 对应 documents 表完整行。"""

    doc_id: str
    kb_id: str
    filename: str
    file_hash: str
    file_size: int
    content_type: str
    content: str
    status: DocStatus = DocStatus.PROCESSING
    chunk_count: int = 0
    source_file_path: str | None = None  # 新增 — 原文件磁盘路径
    source_filename: str | None = None  # 新增 — 原始文件名
    error_message: str | None = None
    uploaded_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class RetrieveResult:
    """检索结果 — 封装一次检索操作的完整响应。

    包含多路检索的计数统计、融合信息、延迟和降级标记。
    """

    hits: list[SearchHit]
    total: int
    latency_ms: int
    mode: str
    vector_count: int
    bm25_count: int
    fused_count: int
    rerank_model: str | None
    degraded: bool
    degraded_reason: str | None
    degraded_kb_ids: list[str] = field(default_factory=list)
    log_id: str | None = None
    trace_id: str | None = None
    # query processing pipeline result (stage 6)
    query_processing: dict | None = None


@dataclass
class DocNode:
    """文档节点 — Tree API 中文档的轻量表示。"""

    doc_id: str
    filename: str
    status: str
    uploaded_at: str
    error_message: str | None = None


@dataclass
class KBNode:
    """知识库节点 — Tree API 中知识库的树节点，包含下属文档列表。"""

    kb_id: str
    name: str
    description: str
    document_count: int
    total_chunks: int
    created_at: str
    documents: list[DocNode]


@dataclass
class TenantKBTree:
    """租户知识库树 — 单个租户下所有知识库的树形结构。"""

    tenant_id: str
    knowledge_bases: list[KBNode]


@dataclass
class Tenant:
    """租户——多租户体系的顶层实体，代表一个独立的使用方。"""

    id: str
    name: str
    plan: str = "free"  # 租户套餐: free | standard | pro
    status: str = "active"  # active | disabled
    created_at: datetime | None = None


@dataclass
class ApiKey:
    """API 密钥——属于某个租户，用于鉴权。密钥原文不存储，只存 SHA-256 哈希。"""

    id: str  # UUID
    tenant_id: str
    key_hash: str
    key_prefix: str  # "rk_xxxx"
    name: str
    status: str = "active"  # active | revoked
    expires_at: datetime | None = None
    created_at: datetime | None = None
