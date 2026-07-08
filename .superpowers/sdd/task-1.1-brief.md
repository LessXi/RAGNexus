# Task 1.1: 新增 `cross_kb_rrf_fuse` 函数

## 文件
`src/ragnexus/domain/retrieval/fusion.py` —— 在该文件末尾新增函数

## 实现要点

### 函数签名
```python
def cross_kb_rrf_fuse(
    kb_hits_groups: list[list[SearchHit]],
    k: int = 60,
) -> list[SearchHit]:
    """跨库 RRF 融合：基于 per-KB rank 重新计算分数并合并。"""
```

### 输入输出
- **输入**: `list[list[SearchHit]]` — 每组是一个 KB 的库内 RRF 后 rank-ordered hits（rank 从 1 开始，即 `hits[0]` 在该 KB 中排第 1）
- **输出**: `list[SearchHit]` — 按 `rrf_score` 降序排列的融合结果

### 算法
对每组内的每条 hit：
- `rrf_score = 1 / (k + rank_in_kb)`，其中 rank_in_kb 从 1 开始

### 去重聚合
在累计 RRF 分数前，按 `(doc_id, chunk_id)` 二元组去重聚合（**不含** kb_id，以支持跨 KB 累加）。聚合时：
- RRF 分数 SUM（同一 chunk 出现在多个 KB 中各库 rank 贡献累加）
- kb_id 保留第一个出现的
- metadata 保留第一个出现的
- 聚合后转换回 `list[SearchHit]`

### 边界
- 空组（`kb_hits_groups` 为空或所有子列表为空）→ 返回 `[]`
- 单组 → 每条 hit 携带正确的 `rrf_score`，按分数降序排列
- 不同 KB 的 hits 数量不一 → 正常处理

### 最终返回
按 `rrf_score` 降序排序返回

### 参考
文件已有的 `rrf_fuse` 函数（约第 39 行附近）实现了两路 RRF 融合（vector + BM25 两组），提供了 `_merge_metadata` 辅助函数。新函数 `cross_kb_rrf_fuse` 是多组泛化版本，输入逻辑不同（基于 rank 而非 score），但 RRF 公式和辅助函数可参考。

### 导入
需要从 `src.ragnexus.domain.models` 导入 `SearchHit`（如果尚未导入）：
```python
from src.ragnexus.domain.models import SearchHit
```

## 验证
- 函数被定义且可被 import
- `rrf_score` 正确赋值到 `hit.score` 字段
- 去重逻辑正确（`list` → `dict` 聚合 → `list`）
- 空输入、单组输入、多组输入的边界行为正确
