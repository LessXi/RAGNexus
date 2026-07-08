# Batch 1 复验报告 (Review Round 2)

**审查范围**: commit 76ad1a4 (fix: batch 1 review — vector/bm25 counts, degraded kb ids, per-pathway exception handling)  
**基准**: batch1-review.md 报告的 3 个问题 (1 Critical + 2 Important)  
**方法**: 对比 diff `50e75ca..76ad1a4` 的实际变更与要求

---

## 验证清单

### Critical #1 ✅ — vector_count / bm25_count 始终为 0

| 检查项 | 状态 | 证据 |
|--------|------|------|
| `_retrieve_per_kb` 返回类型改为三元组 | ✅ | `retrieve_use_case.py:377`: `-> tuple[list[SearchHit], int, int]` |
| 空返回点返回 `([], 0, 0)` | ✅ | `retrieve_use_case.py:428` |
| 有结果返回 `(fused_hits, vec_count, kw_count)` | ✅ | `retrieve_use_case.py:431` |
| `vec_count`/`kw_count` 在函数内计算 | ✅ | `retrieve_use_case.py:423-424`: `vec_count = len(vec_hits)` / `kw_count = len(kw_hits)` |
| ~~旧的 `vec_hits_raw`/`kw_hits = []` 初始化~~ | ✅ 已删除 | diff 显示 `-    kw_hits: list[SearchHit] = []` / `-    vec_hits_raw: list[SearchHit] = []`，替换为 `total_vec_count = 0` / `total_kw_count = 0` (L141-142) |
| execute 中解包三元组 | ✅ | `retrieve_use_case.py:216`: `per_kb_hits, vc, kc = result` |
| 聚合计数 | ✅ | `retrieve_use_case.py:217-218`: `total_vec_count += vc` / `total_kw_count += kc` |
| RetrieveResult 使用聚合值 | ✅ | `retrieve_use_case.py:255-256`: `vector_count=total_vec_count` / `bm25_count=total_kw_count` |
| _safe_log 使用聚合值 | ✅ | `retrieve_use_case.py:275-276`: `vector_hit_count=total_vec_count` / `keyword_hit_count=total_kw_count` |
| 测试覆盖 | ✅ | `test_retrieve_per_kb_returns_vector_and_bm25_counts`, `test_retrieve_per_kb_counts_zero_when_disabled`, `test_execute_aggregates_vector_bm25_counts`, 以及所有旧测试已更新解包 |

**结论**: 修复完整。旧变量 `vec_hits_raw`/`kw_hits` 已删除，`total_vec_count`/`total_kw_count` 通过 per-KB 三元组聚合得到实际值，`RetrieveResult` 和 `_safe_log` 均使用聚合值。

---

### Important #1 ✅ — degraded_kb_ids 未被使用

| 检查项 | 状态 | 证据 |
|--------|------|------|
| per-KB 异常日志 (Exception) | ✅ | `retrieve_use_case.py:210-214`: `logger.warning("KB 召回异常，已跳过", …)` |
| per-KB 空结果日志 | ✅ | `retrieve_use_case.py:219-221`: `logger.info("KB 召回为空", …)` |
| 汇总 warning 日志 | ✅ | `retrieve_use_case.py:226-227`: `logger.warning(f"部分 KB 召回异常或为空，已跳过: {degraded_kb_ids}")` |
| 传入 RetrieveResult | ✅ | `retrieve_use_case.py:261`: `degraded_kb_ids=degraded_kb_ids` |
| RetrieveResult 模型有对应字段 | ✅ | `models.py:111`: `degraded_kb_ids: list[str] = field(default_factory=list)` |
| 测试覆盖 | ✅ | `test_execute_kb_exception_not_blocking` 验证 `"kb1" in result.degraded_kb_ids`; `test_execute_surfaces_degraded_kb_ids` 专门覆盖 |

**结论**: 修复完整。`degraded_kb_ids` 现在有 per-KB 日志 + 汇总 warning + 写入 `RetrieveResult` + 模型字段。

---

### Important #2 ✅ — _retrieve_per_kb 内缺少 per-pathway 异常处理

| 检查项 | 状态 | 证据 |
|--------|------|------|
| `search_by_vector` 有 try/except | ✅ | `retrieve_use_case.py:389-404` |
| 异常时回退到 `vec_hits = []` | ✅ | `retrieve_use_case.py:404` |
| `search_by_keyword` 有 try/except | ✅ | `retrieve_use_case.py:406-421` |
| 异常时回退到 `kw_hits = []` | ✅ | `retrieve_use_case.py:421` |
| 两路独立，不互相影响 | ✅ | 两路各自的 try/except 独立，一失败不传播 |
| 异常日志 | ✅ | `logger.warning("向量检索异常，降级", …)` / `logger.warning("BM25检索异常，降级", …)` |
| docstring 更新 | ✅ | `retrieve_use_case.py:381`: "单路检索异常（网络错误等）→ 捕获后该路返回空列表，不中断另一路" |
| 测试覆盖 | ✅ | `test_retrieve_per_kb_catches_per_pathway_exception`: vector 异常 → BM25 不中断; `test_retrieve_per_kb_catches_both_pathway_exceptions`: 两路异常 → `([], 0, 0)` |

**结论**: 修复完整。每个 `search_by_*` 调用都被 try/except 包裹，异常时该路回退到空列表、记录 warning、不中断另一路。

---

## 总体评估

### 修复质量

- **3/3 问题均已修复**，无遗漏。
- 所有修改通过现有测试 + 新增 6 个专门测试覆盖：
  - `test_retrieve_per_kb_returns_vector_and_bm25_counts`
  - `test_retrieve_per_kb_counts_zero_when_disabled`
  - `test_execute_aggregates_vector_bm25_counts`
  - `test_execute_surfaces_degraded_kb_ids`
  - `test_retrieve_per_kb_catches_per_pathway_exception`
  - `test_retrieve_per_kb_catches_both_pathway_exceptions`
- 旧测试均已更新以匹配新的三元组返回签名。

### 评估: ✅ Approved for next batch

所有 Critical 和 Important 问题均已正确修复，有测试覆盖，可以进行下一批次的合并。
