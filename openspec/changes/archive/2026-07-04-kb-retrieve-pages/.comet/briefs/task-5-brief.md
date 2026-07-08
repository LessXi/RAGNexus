# Task 5: Retrieve Router 升级

## 依赖
- Task 4 (RetrieveUseCase 返回 RetrieveResult + 新签名)

## 目标
升级 `retrieve_router.py`：请求 schema 扩展 + 响应序列化重构

## 文件
- **MOD**: `src/ragnexus/adapters/http/retrieve_router.py`

## 具体需求

### 5.1 请求模型
```python
class _RerankOptions(BaseModel):
    enabled: bool = False
    top_n: int = Field(default=5, ge=1, le=20)

class _RetrieveRequest(BaseModel):
    model_config = {"extra": "forbid"}
    query: str = Field(...)
    kb_ids: list[str] = Field(...)
    top_k: int = Field(default=5, ge=1, le=50)
    mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
    vector_top_k: int = Field(default=20, ge=1, le=200)
    bm25_top_k: int = Field(default=20, ge=1, le=200)
    rrf_k: int = Field(default=60, ge=1, le=200)
    rerank: _RerankOptions | None = None
```

### 5.2 响应序列化
`_serialize_hit` 使用 `.get()` 非 `.pop()`（保持 metadata 完整）：
- `vector_score` = metadata.get("_vector_score")
- `bm25_score` = metadata.get("_bm25_score")
- `rerank_score` = metadata.get("_rerank_score")
- `title` = metadata.get("filename", "")  # filename 映射到 title
- 保留 metadata 中的所有字段（包括 `_` 前缀的）

### 5.3 响应 meta 块
```json
{
  "data": {
    "hits": [...],
    "meta": {
      "total": 10,
      "latency_ms": 42,
      "mode": "hybrid",
      "vector_count": 15,
      "bm25_count": 12,
      "fused_count": 10,
      "rerank_model": "gpt-4o-mini",
      "degraded": false,
      "degraded_reason": null
    }
  }
}
```

### 5.4 Router 内部适配
- 从 `RetrieveResult` 提取 hits + meta 字段
- `composition.py` 装配不变（router factory 自包含）
- file_name → title 映射

## 验证
```bash
pytest tests/unit/adapters/test_http_schema_invariance.py -v
```

## 全局约束
- Python 3.11 + FastAPI + Pydantic
- Factory 模式创建 router
- 中文注释、docstring
- `score` 字段不进 router（字段收缩原则）
- API 响应 `{"code": 0, "data": {...}}`
