# Task 2: Domain — models.py 扩展 + rrf_fuse 改造

## 依赖
- 无（可与 Task 1 并行）

## 目标
1. `models.py`: KnowledgeBase dataclass 加 `tenant_id` 字段，新增 `RetrieveResult`，新增 Tree API 响应类型
2. `fusion.py`: rrf_fuse 改造——预建 `kw_meta_map`，合并两路 `_vector_score`/`_bm25_score`

## 文件
- **MOD**: `src/ragnexus/domain/models.py`
- **MOD**: `src/ragnexus/domain/retrieval/fusion.py`

## 具体需求

### 2.1 models.py — KnowledgeBase
给 `KnowledgeBase` dataclass 加 `tenant_id: str = ""` 字段（所有现有字段之后）。

### 2.2 models.py — RetrieveResult
新增 dataclass:
```python
@dataclass
class RetrieveResult:
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
```

### 2.3 models.py — Tree API 响应类型
```python
@dataclass
class DocNode:
    doc_id: str
    filename: str
    status: str
    uploaded_at: str

@dataclass
class KBNode:
    kb_id: str
    name: str
    description: str
    document_count: int
    total_chunks: int
    created_at: str
    documents: list[DocNode]

@dataclass
class TenantKBTree:
    tenant_id: str
    knowledge_bases: list[KBNode]
```

### 2.4 fusion.py — rrf_fuse 改造
重构为三步（参考 design doc §6）：

**步骤 1**：在进入主循环前，预建 `kw_meta_map`：
```python
kw_meta_map: dict[str, dict] = {h.chunk_id: h.metadata for h in kw_hits}
```

**步骤 2**：向量检索结果处理时，从 `kw_meta_map` 获取对应 chunk 的 BM25 元信息：
```python
if chunk_id in kw_meta_map:
    merged_meta = _merge_metadata(hit.metadata, kw_meta_map[chunk_id])
else:
    merged_meta = dict(hit.metadata)
```

**步骤 3**：新增 `_merge_metadata()` helper：
```python
def _merge_metadata(vec_meta: dict, kw_meta: dict) -> dict:
    """合并向量和 BM25 两路 metadata，保留各自的分数标记。"""
    merged = dict(kw_meta)
    if "_vector_score" in vec_meta:
        merged["_vector_score"] = vec_meta["_vector_score"]
    if "_bm25_score" in kw_meta:
        merged["_bm25_score"] = kw_meta["_bm25_score"]
    for k, v in vec_meta.items():
        if not k.startswith("_"):
            merged[k] = v
    return merged
```

`rrf_fuse` 函数签名**不变**，只改内部实现。所有现有调用方不受影响。

## 验证
```bash
pytest tests/unit/test_rrf_fuse.py -v
```
需要适配 19 个现有测试 + 新增 3-4 个分数合并用例。

## 全局约束
- Python 3.11 + FastAPI Clean Architecture
- 中文注释、docstring
- 不修改 adapter 层
- `score` 领域字段不进 router（字段收缩原则）
- `rrf_fuse` 函数签名不变，只改内部实现
