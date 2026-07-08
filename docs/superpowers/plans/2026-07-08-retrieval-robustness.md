---
change: retrieval-robustness
design-doc: docs/superpowers/specs/2026-07-08-retrieval-robustness-design.md
base-ref: b82404f7dddf07d7caa8dc59495b623cfa110b90
---

# 检索鲁棒性 — 实施计划

## 概述

完善 RAGNexus 检索链路的降级标记和 metadata 透传。**核心逻辑已就位**（双向降级、多库容错），本计划补齐 metadata 标记的"最后一公里"。

改动面：3 个现有文件 + 2 个新增文件，预估 ~80 行逻辑 + ~150 行测试。

## 任务

### 1. 数据模型扩展

- [x] 1.1 `RetrieveResult` 新增字段：`failed_kb_ids: list[str]`、`partial_kb_success: bool`、`empty_reason: str | None`
  - 文件: `src/ragnexus/domain/models.py`
  - 验证: 类型检查通过，无 import 错误

- [x] 1.2 定义 `PerKbRetrieveResult` dataclass
  - 文件: `src/ragnexus/domain/models.py`
  - 字段: `hits`, `vec_count`, `kw_count`, `degraded: bool = False`, `degraded_reason: str | None = None`
  - 验证: 类型检查通过

### 2. 核心逻辑改造

- [x] 2.1 `_retrieve_per_kb` 返回 `PerKbRetrieveResult` 而非元组
  - 文件: `src/ragnexus/application/retrieve_use_case.py` (L399-462)
  - 改动: 在 try/except 中设置 `degraded`/`degraded_reason`，返回 dataclass 实例
  - 验证: `pytest tests/unit/application/test_retrieve_hybrid.py -x -q` 通过

- [ ] 2.2 `execute` 中聚合 per-KB 降级标记
  - 文件: `src/ragnexus/application/retrieve_use_case.py` (L229-246)
  - 改动: 从 `PerKbRetrieveResult` 提取降级标记，设置 `partial_kb_success`
  - 验证: 单测能断言降级标记

- [ ] 2.3 区分 `failed_kb_ids`（异常）和 `degraded_kb_ids`（降级/空）
  - 文件: `src/ragnexus/application/retrieve_use_case.py`
  - 逻辑: `isinstance(result, Exception)` → `failed_kb_ids`；`result.degraded` → 聚合 degraded 标记
  - 验证: mock 异常路径单测通过

- [ ] 2.4 计算 `empty_reason`（两级区分）
  - 文件: `src/ragnexus/application/retrieve_use_case.py`
  - 逻辑: `chunks=[]` 时对每个 kb_id 分别 COUNT，任一 KB 有 chunk → `no_chunks_matched`，全为 0 → `no_indexed_chunks`
  - 验证: 单测覆盖空结果场景

- [ ] 2.5 query 长度校验改用 `QUERY_MAX_LENGTH` 环境变量
  - 文件: `src/ragnexus/application/retrieve_use_case.py` (L97)
  - 改动: `max_len = int(os.getenv("QUERY_MAX_LENGTH", "2000"))`
  - 验证: 已有单测对空/超长 query 的断言仍通过

### 3. API 响应透传

- [ ] 3.1 router 响应 meta 中透传 4 个新字段
  - 文件: `src/ragnexus/adapters/http/retrieve_router.py` (L274-311)
  - 新增: `degraded_kb_ids`、`failed_kb_ids`、`partial_kb_success`、`empty_reason`
  - 验证: `pytest tests/unit/adapters/test_http.py -x -q` 通过

- [ ] 3.2 Happy path 向后兼容
  - 验证: 现有 `tests/unit/adapters/test_http_schema_invariance.py` 通过（如有），或手动确认 single-KB balanced 响应不出现降级字段

### 4. 测试

- [ ] 4.1 新建 `tests/test_retrieve_robustness.py`
  - **8 个 mock 场景**:
    1. mock vector 失败 → hybrid 降为 BM25，degraded=true
    2. mock BM25 失败 → hybrid 降为 vector（回归）
    3. mock embedding 失败（embed_query 抛异常）→ hybrid 降为 BM25，degraded=true
    4. mock 双路都失败 → RETRIEVAL_FAILED
    5. mock 多库一库失败 → 另一库 chunk 仍在，failed_kb_ids 非空
    6. mock 多库全部失败 → RETRIEVAL_FAILED
    7. 空 query → PARAM_ERROR
    8. 超长 query → PARAM_ERROR
  - 验证: `pytest tests/test_retrieve_robustness.py -v` 全部 PASSED
- [ ] 4.2 新建 `scripts/verify_robustness_retrieve.py`
  - 停 ES → hybrid retrieve → 断言 200 + degraded
  - ES 不可用时 SKIP
  - 验证: 手动运行输出各 case OK/SKIP

### 5. 配置

- [ ] 5.1 `.env.example` 补充 `QUERY_MAX_LENGTH=2000`
  - 文件: `.env.example`
  - 内容: 注释说明用途 + 默认值
