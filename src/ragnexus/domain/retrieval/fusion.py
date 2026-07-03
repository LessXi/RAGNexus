"""RRF (Reciprocal Rank Fusion) 融合算法 — 混合检索的分数重算与去重合并。

将向量检索和关键词检索两路结果按 RRF 公式重新计算分数，
合并去重后返回按 RRF score 降序排列的结果列表。
"""

from __future__ import annotations

from ragnexus.domain.models import SearchHit


def rrf_fuse(
    vector_hits: list[SearchHit],
    kw_hits: list[SearchHit],
    k: int = 60,
) -> list[SearchHit]:
    """RRF (Reciprocal Rank Fusion) 融合向量检索和关键词检索结果。

    对两路召回结果按 RRF 公式重新计算分数并合并去重。
    RRF 公式:
        score(chunk) = Σ_{来源 i} 1 / (k + rank_i(chunk))
    其中 rank 从 1 开始（按列表顺序），k 为平滑参数，默认 60。

    同一 chunk_id 同时出现在两路中时，取两路贡献之和作为最终分数。

    Args:
        vector_hits: 向量检索结果（rank 按列表顺序，rank 1 = 最高原始分）
        kw_hits: 关键词检索结果（rank 按列表顺序，rank 1 = 最高原始分）
        k: RRF 平滑参数，默认 60。k 越小，rank 差异对分数影响越大。

    Returns:
        按 RRF score 降序排列的 SearchHit 列表，每个 hit 的 score 已替换为 RRF 分数。
        返回的是新 SearchHit 对象，不会修改输入。
    """
    # 收集每个 chunk_id 的 RRF 累计分和对应的 SearchHit 引用
    rrf_scores: dict[str, float] = {}
    chunk_map: dict[str, SearchHit] = {}

    # 处理向量检索结果
    for rank, hit in enumerate(vector_hits, start=1):
        contrib = 1.0 / (k + rank)
        chunk_id = hit.chunk_id
        if chunk_id in rrf_scores:
            rrf_scores[chunk_id] += contrib
        else:
            rrf_scores[chunk_id] = contrib
            chunk_map[chunk_id] = hit

    # 处理关键词检索结果
    for rank, hit in enumerate(kw_hits, start=1):
        contrib = 1.0 / (k + rank)
        chunk_id = hit.chunk_id
        if chunk_id in rrf_scores:
            rrf_scores[chunk_id] += contrib
        else:
            rrf_scores[chunk_id] = contrib
            chunk_map[chunk_id] = hit

    # 按 RRF score 降序排列
    sorted_ids = sorted(rrf_scores, key=lambda cid: rrf_scores[cid], reverse=True)

    # 构造新的 SearchHit 列表（不修改输入）
    return [
        SearchHit(
            chunk_id=chunk_map[cid].chunk_id,
            kb_id=chunk_map[cid].kb_id,
            doc_id=chunk_map[cid].doc_id,
            score=rrf_scores[cid],
            text=chunk_map[cid].text,
            metadata=chunk_map[cid].metadata,
        )
        for cid in sorted_ids
    ]
