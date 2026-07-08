# Phase 4: Eval & 脚本适配 — 完成报告

## 概述

完成 eval 脚本的多知识库（multi-KB）适配，包括 dataset 扩展、run script 适配、golden cases 新增、Langfuse 导出适配和文档更新。

## 变更清单

### 4.1 eval dataset 扩展

- `eval/utils.py` — 新增纯逻辑工具模块 `resolve_kb_ids(case, default_kb_ids)`
  - 三阶回退：`case.kb_ids` → `case.kb_id` → CLI 默认值
  - 零外部依赖，可被测试直接导入
- 现有 `eval/datasets/_seed_ecommerce.json` 不受影响（无 kb_ids 字段时自动回退到 CLI `--kb-ids`）

### 4.2 run_retrieval_eval.py 适配

- `scripts/run_retrieval_eval.py`
  - 导入 `resolve_kb_ids` from `eval.utils`
  - `run_eval()` 逐条解析 case 时调用 `resolve_kb_ids(item, args.kb_ids)` 替代原先硬编码的 `args.kb_ids`
  - CLI 参数 `--kb-ids` 仍为必填，作为兜底默认值

### 4.3 新增跨库 golden cases

- `eval/datasets/multi_kb_cases.json` — 3 条必须跨库才能答全的测例

| # | 场景 | 涉及 KB |
|---|------|---------|
| 1 | 退货政策 + 跨境订单退款流程区别 | kb_ecommerce_policy, kb_cross_border |
| 2 | 手机保修范围 + 延保购买流程 | kb_ecommerce_policy, kb_product_catalog |
| 3 | 会员权益在跨境购物中的适用性 | kb_ecommerce_policy, kb_membership, kb_cross_border |

### 4.4 Langfuse 导出适配

- `scripts/export_eval_cases_from_langfuse.py`
  - `_extract_kb_ids()` 新增 `metadata.kb_id` 回退（旧 trace 单库场景）
  - 回退顺序：`metadata.kb_ids`（列表）→ `metadata.kb_ids`（字符串）→ `metadata.kb_id` → `[]`
  - `main()` 输出 case 时携带 `kb_ids` 字段（若 trace 中存在）

### 4.5 文档更新

- `docs/tenant-onboarding.md`
  - 套餐对照表新增「单次检索最大 KB 数」行
  - 表下新增 `max_kb_per_retrieve` 说明段落
  - Free→Standard 和 Standard→Pro 升级对比表同步更新

## 测试

- `tests/unit/test_retrieval_eval.py` — 7 个测试覆盖 `resolve_kb_ids` 全部回退路径：
  - `kb_ids` 列表直接使用
  - `kb_id` 单字符串包装
  - 两者均无时回退 CLI 默认
  - `kb_ids` 优先于 `kb_id`（同时存在时）
  - 空 `kb_ids` 回退到默认值
  - 空 `kb_ids` + `kb_id` 使用 `kb_id`
  - CLI 默认值为空列表

```
tests/unit/test_retrieval_eval.py: 7 passed
```

## 验证

```bash
# 语法检查
python -c "from eval.utils import resolve_kb_ids"  # OK
python -c "import ast; ast.parse(open('scripts/run_retrieval_eval.py').read())"  # OK
python -c "import ast; ast.parse(open('scripts/export_eval_cases_from_langfuse.py').read())"  # OK
python -c "import json; json.load(open('eval/datasets/multi_kb_cases.json'))"  # OK

# 单元测试
pytest tests/unit/test_retrieval_eval.py -v  # 7 passed
```
