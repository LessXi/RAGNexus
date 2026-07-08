# Brainstorm Summary

- Change: retrieval-robustness
- Date: 2026-07-08

## 确认的技术方案

1. **`_retrieve_per_kb` 返回值扩展**：从 `tuple[list[SearchHit], int, int]` 改为 dataclass `PerKbRetrieveResult`，携带 `degraded` 和 `degraded_reason` 标记
2. **`empty_reason` 精度**：一步到位实现两级区分（`no_indexed_chunks` / `no_chunks_matched`），通过 DB count 查询在 `chunks=[]` 时触发
3. **API 响应结构**：保持扁平 `meta` 结构，新增字段直接挂在 `meta` 下，不引入嵌套 breaking change
4. **测试策略**：新建 `test_retrieve_robustness.py`（7 场景 mock）+ `verify_robustness_retrieve.py`（集成验证）

## 关键取舍与风险

- **不嵌套 meta**：避免 BREAKING CHANGE，前端和 eval 脚本零影响
- **一步到位 empty_reason**：COUNT 查询仅在空结果时触发，成本毫秒级
- **dataclass 替换元组**：改动 ~20 行，compile-time 即可发现所有调用点

## 测试策略

- 单测 7 场景：hybrid 降级 ×3、多库容错 ×2、query 边界 ×2
- 集成脚本：停 ES 验证降级，无 ES 时 SKIP
- 回归：319 现有 tests + happy path 不变

## Spec Patch

无 — delta spec 已在 open 阶段创建完整，无需回写
