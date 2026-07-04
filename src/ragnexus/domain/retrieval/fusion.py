"""RRF (Reciprocal Rank Fusion) 融合算法 — 混合检索的分数重算与去重合并。

将向量检索和关键词检索两路结果按 RRF 公式重新计算分数，
合并去重后返回按 RRF score 降序排列的结果列表。
"""

from __future__ import annotations

from ragnexus.domain.models import SearchHit


def _merge_metadata(vec_meta: dict, kw_meta: dict) -> dict:
    """合并向量和 BM25 两路 metadata，保留各自的分数标记。

    合并策略：
    1. 以关键词路 metadata 为底
    2. 保留向量路的 _vector_score
    3. 保留关键词路的 _bm25_score
    4. 向量路的非下划线字段覆盖关键词路

    Args:
        vec_meta: 向量检索结果的 metadata
        kw_meta: 关键词检索结果的 metadata

    Returns:
        合并后的 metadata 字典（新 dict，不修改输入）
    """
    merged = dict(kw_meta)
    if "_vector_score" in vec_meta:
        merged["_vector_score"] = vec_meta["_vector_score"]
    if "_bm25_score" in kw_meta:
        merged["_bm25_score"] = kw_meta["_bm25_score"]
    for k, v in vec_meta.items():
        if not k.startswith("_"):
            merged[k] = v
    return merged


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

    同一 chunk_id 同时出现在两路中时，取两路贡献之和作为最终分数，
    并通过 _merge_metadata 合并两路的 metadata。

    Args:
        vector_hits: 向量检索结果（rank 按列表顺序，rank 1 = 最高原始分）
        kw_hits: 关键词检索结果（rank 按列表顺序，rank 1 = 最高原始分）
        k: RRF 平滑参数，默认 60。k 越小，rank 差异对分数影响越大。

    Returns:
        按 RRF score 降序排列的 SearchHit 列表，每个 hit 的 score 已替换为 RRF 分数。
        共享 chunk 的 metadata 包含两路的分数标记。
        返回的是新 SearchHit 对象，不会修改输入。
    """
    # 预建关键词路 chunk_id → metadata 映射（步骤 1）
    kw_meta_map: dict[str, dict] = {h.chunk_id: h.metadata for h in kw_hits}

    # 收集每个 chunk_id 的 RRF 累计分和对应的 SearchHit 引用
    rrf_scores: dict[str, float] = {}
    chunk_map: dict[str, SearchHit] = {}
    # 共享 chunk 的合并 metadata 缓存（不修改输入 hit）
    merged_meta_cache: dict[str, dict] = {}

    # 处理向量检索结果（步骤 2）
    for rank, hit in enumerate(vector_hits, start=1):
        contrib = 1.0 / (k + rank)
        chunk_id = hit.chunk_id
        if chunk_id in rrf_scores:
            rrf_scores[chunk_id] += contrib
        else:
            rrf_scores[chunk_id] = contrib
            chunk_map[chunk_id] = hit
            # 共享 chunk：预计算合并 metadata
            if chunk_id in kw_meta_map:
                merged_meta_cache[chunk_id] = _merge_metadata(
                    hit.metadata, kw_meta_map[chunk_id]
                )

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
            metadata=merged_meta_cache.get(cid, chunk_map[cid].metadata),
        )
        for cid in sorted_ids
    ]
