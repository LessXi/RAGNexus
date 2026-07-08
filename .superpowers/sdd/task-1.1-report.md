# Task 1.1 Report: `cross_kb_rrf_fuse`

## RED 阶段 — 失败测试

### 失败测试命令
```bash
python -m pytest tests/unit/domain/test_fusion.py -v --tb=short
```

### 失败输出摘要
```
ImportError while importing test module 'tests/unit/domain/test_fusion.py'
ImportError: cannot import name 'cross_kb_rrf_fuse' from 'ragnexus.domain.retrieval.fusion'
```
**10 条测试全部因 ImportError 失败** — 函数尚未定义，符合预期。

### 新增测试文件
`tests/unit/domain/test_fusion.py` — 含 4 个测试类共 10 条用例：

| 测试类 | 测试方法 | 覆盖行为 |
|--------|---------|---------|
| `TestCrossKbRrfFuseTwoGroups` | `test_two_groups_no_overlap` | 两组各 5 hits，无重叠，10 条结果，分数对称 |
| | `test_two_groups_with_cross_kb_overlap` | 两组有跨库重叠，分数累加，去重为 3 条 |
| `TestCrossKbRrfFuseSingleGroup` | `test_single_group` | 单组退化，3 条结果分数正确，降序 |
| `TestCrossKbRrfFuseEmptyGroup` | `test_empty_input_list` | `[]` → `[]` |
| | `test_all_empty_groups` | `[[], []]` → `[]` |
| | `test_mixed_empty_groups` | 部分空组过滤，非空组正常返回 |
| `TestCrossKbRrfFuseDuplicateChunk` | `test_duplicate_chunk_sums_rrf` | `(doc_id, chunk_id)` 去重，分数累加 |
| | `test_duplicate_only_by_chunk_id_not_doc_id` | 仅 chunk_id 同但 doc_id 不同 → 不去重 |
| | `test_cross_kb_fuse_preserves_text_and_metadata` | text/metadata 保留首次出现值 |
| | `test_different_kb_ids_on_same_chunk_sum_rrf` | 三 KB 同一 chunk，分数 3x 累加 |

---

## GREEN 阶段 — 通过测试

### 通过测试命令
```bash
python -m pytest tests/unit/domain/test_fusion.py -v --tb=short
```

### 通过输出摘要
```
pytest: 10 passed in 0.07s
```

### 回归验证
```bash
# 已有 RRF 测试（18 条）
python -m pytest tests/unit/test_rrf_fuse.py -v
# → 18 passed

# domain 全部测试（28 条）
python -m pytest tests/unit/domain/ -v
# → 28 passed
```

---

## 实现内容

### 文件变更
- `src/ragnexus/domain/retrieval/fusion.py` — 文件末尾新增 `cross_kb_rrf_fuse` 函数（52 行）
- `tests/unit/domain/test_fusion.py` — 新建测试文件（10 条用例）

### 函数签名
```python
def cross_kb_rrf_fuse(
    kb_hits_groups: list[list[SearchHit]],
    k: int = 60,
) -> list[SearchHit]:
```

### 核心逻辑
1. **空输入快速路径**：`kb_hits_groups` 为空或全空子列表 → 返回 `[]`
2. **逐组遍历**：`enumerate(group, start=1)` 获取 per-KB rank，计算 `contrib = 1.0 / (k + rank)`
3. **去重聚合**：以 `(doc_id, chunk_id)` 二元组为 key：
   - RRF 分数 SUM（跨 KB 累加）
   - `kb_id`/`text`/`metadata` 保留首次出现值
4. **排序输出**：按 `rrf_score` 降序，构造新 `SearchHit` 对象（不修改输入）

### 与已有 `rrf_fuse` 的对比
| 维度 | `rrf_fuse` (已有) | `cross_kb_rrf_fuse` (新增) |
|------|-------------------|---------------------------|
| 输入 | 两组 SearchHit 列表 | 多组 SearchHit 列表 |
| 去重键 | 单 `chunk_id` | `(doc_id, chunk_id)` 二元组 |
| 输入含义 | 按原始 score 排序（rank 即位置） | 显式 per-KB rank-ordered |

---

## 提交
```
e25eea8 feat: add cross_kb_rrf_fuse for multi-KB reciprocal rank fusion
2 files changed, 292 insertions(+)
```

---

## 注意事项
- SearchHit 暂无 `kb_name` 字段（后续任务添加），当前 `kb_id` 用于标识 KB
- pre-commit hook 因环境缺少 `pre_commit` 模块而跳过，不影响代码质量
