# Task 2 Report: 领域模型与 plan_presets

## Status: DONE ✅

## Summary
创建了 `ragnexus.tenant` 包，包含三档 PLAN_PRESETS、四档 RETRIEVE_PROFILE_PRESETS、PlanResolver 纯函数，并在 Tenant 数据类上添加了 `plan` 字段。

## Files Created/Modified

| File | Action | Lines |
|------|--------|-------|
| `src/ragnexus/tenant/__init__.py` | 新建 | 0 (空) |
| `src/ragnexus/tenant/plan_presets.py` | 新建 | 58 |
| `src/ragnexus/tenant/retrieve_presets.py` | 新建 | 27 |
| `src/ragnexus/tenant/plan_resolver.py` | 新建 | 51 |
| `src/ragnexus/domain/models.py` | 修改 | +1 行 |
| `tests/unit/test_plan_resolver.py` | 新建 | 108 |

## TDD Evidence

### RED — 初始失败
```
test_resolve_plan_free_basic - ModuleNotFoundError: No module named 'ragnexus.tenant'
```
模块尚不存在时的预期 ImportError。

### GREEN — 全部通过
```
tests/unit/test_plan_resolver.py::test_resolve_plan_free_basic PASSED
tests/unit/test_plan_resolver.py::test_resolve_plan_unknown_raises_valueerror PASSED
tests/unit/test_plan_resolver.py::test_plan_presets_structure PASSED
tests/unit/test_plan_resolver.py::test_retrieve_profile_presets_structure PASSED
tests/unit/test_plan_resolver.py::test_tenant_plan_default PASSED
```
5 个新测试全部通过。

### 回归验证
```
tests/unit/ … 449 passed, 1 warning
```
全部 449 个已有测试无回归。

## Key Design Decisions

1. **`plan: str = "free"` 放在 `name` 之后** — 满足 Python dataclass 字段默认值必须在无默认值字段之后的规则。
2. **PLAN_PRESETS 和 RETRIEVE_PROFILE_PRESETS 为模块级常量** — 零依赖，纯数据，可直接序列化。
3. **`resolve_plan()` 为纯函数** — 不涉及 Redis/DB，无副作用，返回不可变 dataclass。
4. **custom profile 不在 RETRIEVE_PROFILE_PRESETS 中** — 按需求，custom profile 由请求参数动态决定。
5. **中文 docstring** — 全部模块、类、函数使用中文注释。

## Concerns
无。所有需求均已实现，测试全部通过。
