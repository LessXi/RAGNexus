# Task 2.1: plan_presets 新增 max_kb_per_retrieve

## 文件
`src/ragnexus/tenant/plan_presets.py`

## 改动
在三个套餐的 `"limits"` 下新增 `max_kb_per_retrieve` 字段：
```python
# free
"max_kb_per_retrieve": 1,

# standard
"max_kb_per_retrieve": 3,

# pro
"max_kb_per_retrieve": 5,
```

## 参考
- 现有 `PLAN_PRESETS` dict 在 plan_presets.py:6 附近
- 每个 preset 有 `"limits"` dict，内含 `max_knowledge_bases`、`max_documents` 等
- 在同级新增 `max_kb_per_retrieve`

## 验证
- free/standard/pro 值分别为 1/3/5
- 字段可被 `plan_ctx.limits.get("max_kb_per_retrieve")` 读取
