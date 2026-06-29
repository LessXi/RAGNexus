"""LLM 重排适配器 — LLMRerankProvider。

基于 LLMProvider 对向量召回候选进行相关性重排序，支持：
- 向量相似度缓存（cosine ≥ 阈值）
- 候选截断和文本截断
- JSON 4 层防御解析
- 降级返回原始排序（永不抛异常）
- BIZ_EVENT 结构化日志
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any

from ragnexus.adapters.llm.base import LLMProvider
from ragnexus.domain.models import SearchHit

logger = logging.getLogger("ragnexus")


# ============================================================================
# CacheEntry
# ============================================================================


@dataclass
class CacheEntry:
    """重排缓存条目。

    存储一次 LLM 重排的全量结果，包括：
    - query_embedding: 用于余弦相似度匹配
    - query_text: 原始 query，用于日志
    - rankings: {chunk_id: rerank_score} 全量打分映射
    - timestamp: 写入时间，用于 TTL 过期
    """

    query_embedding: list[float]
    query_text: str
    rankings: dict[str, float]
    timestamp: float


# ============================================================================
# System Prompt
# ============================================================================

SYSTEM_PROMPT = (
    "你是 RAG 检索重排器。你的任务是根据用户问题，对候选知识片段进行相关性打分和排序。\n\n"
    "要求：\n"
    "1. 只判断候选片段是否有助于回答用户问题。\n"
    "2. 不要回答用户问题。\n"
    "3. 不要编造候选片段中不存在的信息。\n"
    "4. 每个候选片段给出 0 到 1 之间的 rerank_score。\n"
    "5. 分数越高表示越相关、越适合作为 RAG 上下文。\n"
    "6. 只返回 JSON，不要返回 Markdown，不要返回解释性文字。\n"
    "7. reference_scores 中的候选已有最终相关性分数。请在相同评分体系下为 candidates 打分，"
    "保持分数的一致性和可比性。不要更改或质疑 reference_scores 中的分数。"
)


# ============================================================================
# 内部辅助函数
# ============================================================================


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _build_content_preview(text: str, heading: str | None, max_chars: int) -> str:
    """构造 content_preview：前置 heading，截取前几个完整句子 ≤ max_chars。

    用于缓存部分命中时的 reference_scores 标尺。
    """
    prefix = f"{heading}: " if heading else ""
    available = max_chars - len(prefix)
    if available <= 0:
        return prefix[:max_chars]

    # 截取前几个完整句子
    if len(text) <= available:
        return prefix + text

    # 找最后一个句号/问号/感叹号/换行在 available 内的位置
    truncated = text[:available]
    for sep in ("。", "！", "？", "\n", ". ", "! ", "? "):
        idx = truncated.rfind(sep)
        if idx > 0:
            return prefix + truncated[: idx + len(sep.rstrip())]
    # 没找到句子边界 → 硬截断
    return prefix + truncated


def _extract_rankings_from_dict(d: dict[str, Any]) -> list[dict[str, Any]] | None:
    """从解析后的 dict 中提取 rankings 列表。返回 None 表示无法提取。

    支持两种格式:
    - 标准: {"rankings": [{"chunk_id": ..., "rerank_score": ...}, ...]}
    - 扁平: {"chunk_id_1": 0.95, "chunk_id_2": 0.3, ...}
    """
    if not isinstance(d, dict) or not d:
        return None
    # 嵌套格式: {"rankings": [...]} / {"rerank_scores": [...]} / {"scores": [...]} / {"results": [...]}
    for key in ("rankings", "rerank_scores", "scores", "results"):
        rankings = d.get(key)
        if isinstance(rankings, list) and rankings:
            return rankings
    # 兼容扁平 dict {chunk_id: rerank_score}
    if all(isinstance(v, (int, float)) for v in d.values()):
        return [{"chunk_id": str(k), "rerank_score": float(v)} for k, v in d.items()]
    return None


def _parse_rankings_json(raw: Any) -> list[dict[str, Any]]:
    """JSON 4 层防御解析。

    0. API 层 response_format: json_object（LLMProvider 处理）
    1. 已经是 dict/list → 直接提取
    2. json.loads — 纯 JSON 字符串
    3. 正则提取 ```json ... ``` — Markdown 代码块
    4. 正则提取最外层 {...} — 文本夹杂 JSON
    5. 全失败返回空列表

    返回 rankings 列表，每个元素为 {"chunk_id": str, "rerank_score": float, ...}
    """
    # Layer 1: 已经是 dict/list
    if isinstance(raw, dict):
        result = _extract_rankings_from_dict(raw)
        if result is not None:
            return result
        return []
    if isinstance(raw, list):
        return raw

    # 确保是字符串
    if not isinstance(raw, str):
        return []

    content = raw.strip()
    if not content:
        return []

    # Layer 2: 直接 json.loads
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            result = _extract_rankings_from_dict(parsed)
            if result is not None:
                return result
        elif isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Layer 3: 提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group(1).strip())
            if isinstance(parsed, dict):
                result = _extract_rankings_from_dict(parsed)
                if result is not None:
                    return result
            elif isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Layer 4: 提取最外层 {...}
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, dict):
                result = _extract_rankings_from_dict(parsed)
                if result is not None:
                    return result
            elif isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    return []


def _clamp_score(score: float) -> float:
    """将分数 clamp 到 [0, 1] 区间。"""
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


# ============================================================================
# LLMRerankProvider
# ============================================================================


class LLMRerankProvider:
    """LLM 驱动的重排提供者。

    对向量召回候选 chunk 进行 LLM 相关性打分重排序。
    降级安全：任意步骤失败时返回原始向量排序，永不抛异常。
    """

    def __init__(
        self,
        llm: LLMProvider,
        max_candidates: int = 20,
        chunk_max_chars: int = 1000,
        cache_similarity_threshold: float = 0.95,
        cache_max_entries: int = 100,
        cache_ttl_seconds: int = 300,
        cache_preview_max_chars: int = 150,
        temperature: float = 0.0,
    ):
        """初始化 LLM 重排提供者。

        参数:
            llm: LLMProvider 实例，用于调用大模型
            max_candidates: 最多送 LLM 的候选数（超出部分截断）
            chunk_max_chars: 每个 chunk 文本的最大字符数
            cache_similarity_threshold: 缓存命中的余弦相似度阈值
            cache_max_entries: 每个 KB 最多缓存的条目数
            cache_ttl_seconds: 缓存 TTL（秒）
            cache_preview_max_chars: content_preview 的最大字符数
            temperature: LLM 采样温度
        """
        self.llm = llm
        self.max_candidates = max_candidates
        self.chunk_max_chars = chunk_max_chars
        self.cache_similarity_threshold = cache_similarity_threshold
        self.cache_max_entries = cache_max_entries
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_preview_max_chars = cache_preview_max_chars
        self.temperature = temperature
        self._cache: dict[frozenset[str], list[CacheEntry]] = {}
        self._lock = asyncio.Lock()

    # ========================================================================
    # rerank — 主入口
    # ========================================================================

    async def rerank(
        self,
        *,
        query: str,
        query_vector: list[float],
        kb_ids: list[str],
        chunks: list[SearchHit],
        top_n: int,
    ) -> list[SearchHit]:
        """对向量召回候选重排序。

        参数:
            query: 用户原始问题
            query_vector: 查询向量（用于缓存余弦相似度匹配）
            kb_ids: 检索目标 KB 列表（用于缓存分区）
            chunks: 向量召回的 SearchHit 列表（按 score 降序）
            top_n: 最终返回数

        返回:
            排好序的 SearchHit 列表，score 字段保持向量原始分
        """
        start_time = time.time()
        try:
            return await self._rerank_impl(
                query=query,
                query_vector=query_vector,
                kb_ids=kb_ids,
                chunks=chunks,
                top_n=top_n,
                start_time=start_time,
            )
        except Exception as exc:
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            logger.warning(
                "rerank LLM 调用失败，降级为向量排序",
                extra={
                    "event_type": "BIZ_EVENT",
                    "event": "rerank_degraded",
                    "kb_ids": kb_ids,
                    "query": query[:200],
                    "candidate_count": len(chunks),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:500],
                    "rerank_latency_ms": elapsed_ms,
                },
            )
            return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_n]

    async def _rerank_impl(
        self,
        *,
        query: str,
        query_vector: list[float],
        kb_ids: list[str],
        chunks: list[SearchHit],
        top_n: int,
        start_time: float,
    ) -> list[SearchHit]:
        """rerank 内部实现（不含降级 try/except）。"""
        if not chunks:
            return []

        now = time.time()

        # --- 步骤 a: 查缓存 ---
        matched_rankings: dict[str, float] = {}
        unmatched_chunks = list(chunks)
        cache_hit_entry: CacheEntry | None = None
        cache_max_sim = 0.0
        async with self._lock:
            _cache_key = frozenset(kb_ids)
            entries = self._cache.get(_cache_key, [])
            for entry in entries:
                # TTL 过期检查
                if now - entry.timestamp > self.cache_ttl_seconds:
                    continue
                sim = _cosine_similarity(query_vector, entry.query_embedding)
                if sim >= self.cache_similarity_threshold and sim > cache_max_sim:
                    cache_max_sim = sim
                    cache_hit_entry = entry

        if cache_hit_entry is not None:
            cached_rankings = cache_hit_entry.rankings
            matched_ids = set()
            for chunk in chunks:
                if chunk.chunk_id in cached_rankings:
                    matched_rankings[chunk.chunk_id] = cached_rankings[chunk.chunk_id]
                    matched_ids.add(chunk.chunk_id)

            unmatched_chunks = [c for c in chunks if c.chunk_id not in matched_ids]

            if not unmatched_chunks:
                # 全命中：直接按缓存分排序返回
                sorted_chunks = sorted(
                    chunks,
                    key=lambda c: matched_rankings.get(c.chunk_id, 0.0),
                    reverse=True,
                )
                elapsed_ms = round((time.time() - start_time) * 1000, 2)
                logger.info(
                    "",
                    extra={
                        "event_type": "BIZ_EVENT",
                        "event": "rerank_cache_hit",
                        "kb_ids": kb_ids,
                        "query": query[:200],
                        "similarity": round(cache_max_sim, 4),
                        "cached_query": cache_hit_entry.query_text[:200],
                        "matched_count": len(matched_rankings),
                        "unmatched_count": 0,
                        "rerank_latency_ms": elapsed_ms,
                    },
                )
                return sorted_chunks[:top_n]

            # 部分命中时记录日志
            logger.info(
                "",
                extra={
                    "event_type": "BIZ_EVENT",
                    "event": "rerank_cache_hit",
                    "kb_ids": kb_ids,
                    "query": query[:200],
                    "similarity": round(cache_max_sim, 4),
                    "cached_query": cache_hit_entry.query_text[:200],
                    "matched_count": len(matched_rankings),
                    "unmatched_count": len(unmatched_chunks),
                },
            )

        # --- 步骤 b: 候选截断 ---
        unmatched_candidates = unmatched_chunks[: self.max_candidates]

        # --- 步骤 c: 文本截断 ---
        truncated_candidates: list[dict[str, Any]] = []
        for chunk in unmatched_candidates:
            heading = chunk.metadata.get("heading") if chunk.metadata else None
            truncated_candidates.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.doc_id,
                    "title": heading if heading else "",
                    "content": chunk.text[: self.chunk_max_chars],
                    "vector_score": chunk.score,
                }
            )

        # --- 步骤 d: 构造 JSON payload ---
        payload: dict[str, Any] = {
            "query": query,
            "candidates": truncated_candidates,
            "top_n": top_n,
        }

        # 部分命中：添加 reference_scores 标尺
        if matched_rankings and cache_hit_entry is not None:
            ref_scores: list[dict[str, Any]] = []
            for cid, rscore in matched_rankings.items():
                # 找到原始 chunk 信息
                orig_chunk = next((c for c in chunks if c.chunk_id == cid), None)
                heading = (
                    orig_chunk.metadata.get("heading")
                    if orig_chunk and orig_chunk.metadata
                    else None
                )
                text = orig_chunk.text if orig_chunk else ""
                preview = _build_content_preview(
                    text, heading, self.cache_preview_max_chars
                )
                ref_scores.append(
                    {
                        "chunk_id": cid,
                        "rerank_score": rscore,
                        "content_preview": preview,
                    }
                )
            payload["reference_scores"] = ref_scores

        # --- 步骤 e: LLM 调用 ---
        try:
            llm_response = await self.llm.chat_json(
                system_prompt=SYSTEM_PROMPT,
                user_payload=payload,
                temperature=self.temperature,
            )
        except Exception:
            # LLM 调用失败，但仍在 _rerank_impl 中
            # 如果有缓存匹配部分，用缓存分 + 原始排序
            if matched_rankings:
                return self._merge_and_sort(chunks, matched_rankings, {}, top_n)
            raise  # 让外层 catch 降级

        # --- 步骤 f: 解析 rankings ---
        rankings_list = _parse_rankings_json(llm_response)
        if not rankings_list and not matched_rankings:
            # 解析全失败且无缓存匹配 → 触发降级
            return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_n]

        # 构建 LLM 打分映射
        llm_rankings: dict[str, float] = {}
        for item in rankings_list:
            cid = item.get("chunk_id")
            if not cid:
                continue
            score = _clamp_score(float(item.get("rerank_score", 0.0)))
            llm_rankings[str(cid)] = score

        # --- 合并缓存分 + LLM 分 → 排序 → 裁回 top_n ---
        result = self._merge_and_sort(chunks, matched_rankings, llm_rankings, top_n)

        # --- 步骤 g: 写入缓存 ---
        # 合并全量映射（matched + llm），缺失的默认 0
        full_rankings: dict[str, float] = dict(matched_rankings)
        for chunk in chunks:
            if chunk.chunk_id not in full_rankings:
                full_rankings[chunk.chunk_id] = llm_rankings.get(chunk.chunk_id, 0.0)

        cache_entry = CacheEntry(
            query_embedding=list(query_vector),
            query_text=query,
            rankings=full_rankings,
            timestamp=time.time(),
        )

        async with self._lock:
            entries = self._cache.setdefault(frozenset(kb_ids), [])
            entries.append(cache_entry)
            # 超限踢最旧
            while len(entries) > self.cache_max_entries:
                entries.pop(0)

        # --- 日志 ---
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        logger.info(
            "",
            extra={
                "event_type": "BIZ_EVENT",
                "event": "rerank_completed",
                "kb_ids": kb_ids,
                "query": query[:200],
                "candidate_count": len(chunks),
                "kept_count": len(result),
                "rerank_latency_ms": elapsed_ms,
            },
        )

        # DEBUG 级别打分详情
        logger.debug(
            "rerank 打分详情",
            extra={
                "event_type": "RERANK_DEBUG",
                "kb_ids": kb_ids,
                "query": query[:200],
                "rankings": [
                    {
                        "chunk_id": item.get("chunk_id", ""),
                        "rerank_score": item.get("rerank_score", 0.0),
                        "reason": item.get("reason", ""),
                    }
                    for item in rankings_list
                ],
            },
        )

        return result

    # ========================================================================
    # 内部辅助方法
    # ========================================================================

    def _merge_and_sort(
        self,
        chunks: list[SearchHit],
        matched_rankings: dict[str, float],
        llm_rankings: dict[str, float],
        top_n: int,
    ) -> list[SearchHit]:
        """合并缓存分和 LLM 分，按 rerank_score 降序排序，裁回 top_n。

        缓存分优先（已经过 LLM 验证），LLM 分补充未命中 chunk。
        score 字段保持向量原始分不变。
        """
        # 为每个 chunk 确定 rerank_score
        chunk_scores: dict[str, float] = {}
        for chunk in chunks:
            cid = chunk.chunk_id
            if cid in matched_rankings:
                chunk_scores[cid] = matched_rankings[cid]
            elif cid in llm_rankings:
                chunk_scores[cid] = llm_rankings[cid]
            else:
                chunk_scores[cid] = 0.0

        sorted_chunks = sorted(
            chunks, key=lambda c: chunk_scores.get(c.chunk_id, 0.0), reverse=True
        )
        return sorted_chunks[:top_n]

    # ========================================================================
    # clear_cache
    # ========================================================================

    async def clear_cache(self, kb_id: str) -> None:
        """清空包含指定 KB 的所有缓存条目。"""
        async with self._lock:
            keys_to_delete = [key for key in self._cache if kb_id in key]
            for key in keys_to_delete:
                del self._cache[key]
