# Task 2.2: router 入口校验 + Task 2.3: 响应体扩展

## 文件
`src/ragnexus/adapters/http/retrieve_router.py`

## 子任务 A (2.2): 入口校验

在 `resolve_plan` 之后插入校验：
```python
max_kb = plan_ctx.limits.get("max_kb_per_retrieve", 5)
if len(req.kb_ids) > max_kb:
    raise AppError(
        ErrorCode.FEATURE_NOT_ALLOWED,
        f"当前套餐最多支持 {max_kb} 个库联合检索",
    )
```

## 子任务 B (2.3): 响应体扩展

### data 根级新增 kb_ids
```python
"data": {
    "query": req.query,
    "kb_ids": req.kb_ids,  # 新增
    "hits": [...],
    ...
}
```

### meta 新增多库元信息
```python
"meta": {
    ...
    "multi_kb": len(req.kb_ids) > 1,
    "kb_count": len(req.kb_ids),
    "per_kb_top_k": per_kb_top_k,
    "fusion": "rrf",
    "rrf_k": req.rrf_k,
}
```

### _serialize_hit 输出 kb_name
```python
def _serialize_hit(hit: SearchHit) -> dict:
    return {
        ...
        "kb_name": hit.kb_name,  # 新增
    }
```

## 注意
- `plan_ctx` 来自 `resolve_plan` 的返回值
- `ErrorCode.FEATURE_NOT_ALLOWED` 对应 20013
- FEATURE_NOT_ALLOWED 需确认在 error_codes 中已定义
- 保持 MULTI_KB_MAX=5 硬上限作为天花板

## 验证
- free 租户传 2 库 → 20013
- standard 租户传 3 库 → 通过
- 响应中 kb_ids/kb_name/multi_kb 正确输出
