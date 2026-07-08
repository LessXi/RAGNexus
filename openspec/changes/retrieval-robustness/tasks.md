## 1. 数据模型扩展

- [x] 1.1 `RetrieveResult` 新增字段：`failed_kb_ids`、`partial_kb_success`、`empty_reason`
- [x] 1.2 定义 `PerKbRetrieveResult` dataclass 替换 `_retrieve_per_kb` 的三元组返回值

## 2. 核心逻辑改造

- [ ] 2.1 `_retrieve_per_kb` 返回值改为 `PerKbRetrieveResult`，包含降级标记 `degraded` 和 `degraded_reason`
- [ ] 2.2 `execute` 中 per-KB 降级标记聚合：汇总 `degraded`、设置 `partial_kb_success`
- [ ] 2.3 `execute` 中区分 `failed_kb_ids`（异常）和 `degraded_kb_ids`（降级/空）语义
- [ ] 2.4 `execute` 中计算 `empty_reason`：chunks=[] 时标记原因
- [ ] 2.5 `execute` 中 query 长度校验改用 `QUERY_MAX_LENGTH` 环境变量

## 3. API 响应透传

- [ ] 3.1 `retrieve_router.py` 响应 meta 中透传 `degraded_kb_ids`（已有字段，当前未透传）、`failed_kb_ids`（新增）、`partial_kb_success`（新增）、`empty_reason`（新增）
- [ ] 3.2 确保 Happy path 向后兼容：单库 balanced 检索 `chunks>0` 时，meta 中 `degraded=false`，`degraded_kb_ids=[]`，`failed_kb_ids=[]`，`partial_kb_success=false`，`empty_reason=null`——现有 E2E 响应结构不破坏

## 4. 测试
