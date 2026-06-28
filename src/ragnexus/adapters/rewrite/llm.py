"""LLM 查询改写适配器 — LLMRewriteProvider。

基于 LLM 的查询改写实现，包含：
- 向量相似度缓存（cosine ≥ 阈值）
- 一次 LLM 调用完成判断+改写
- JSON 5 层防御解析
- 二次精炼（>200 字时压缩）
- 降级返回原始 query（永不抛异常）
- BIZ_EVENT 结构化日志
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from dataclasses import dataclass

from ragnexus.adapters.llm.base import LLMProvider
from ragnexus.core.logger import logger
from ragnexus.domain.ports import EmbedderPort, RewriteResult

# ============================================================================
# System Prompt
# ============================================================================

SYSTEM_PROMPT = (
    "你是 RAG 检索查询优化器。分析用户的原始查询，判断是否需要改写为更适合向量检索的形式，"
    "如果需要则直接给出改写结果。\n\n"
    "判断标准：\n"
    "- 如果查询包含明确的关键词、名词、专业术语，且语义清晰 → 不需要改写\n"
    "- 如果查询存在以下问题 → 需要改写：\n"
    '  · 过于口语化（"上次那个"、"怎么搞的"）\n'
    '  · 包含指代词（"这个"、"那个"、"它"）\n'
    "  · 过于简短（缺少关键词）\n"
    "  · 表述模糊\n\n"
    "改写要求：\n"
    "- 展开缩写和指代，补充隐含的上下文关键词\n"
    "- 保留用户的核心意图，不要添加用户未提及的信息\n"
    "- 改写后长度控制在 5-50 字\n"
    "- 改写结果更适合中文向量检索\n\n"
    "只返回 JSON，不要返回 Markdown，不要返回解释性文字。"
)

REFINE_SYSTEM_PROMPT = (
    "请将以下查询改写结果压缩到 50 字以内，保持核心关键词和语义。"
    '只返回 JSON：{"rewritten_query": "..."}'
)

# ============================================================================
# CacheEntry
# ============================================================================


@dataclass
class CacheEntry:
    """改写缓存条目。"""

    query_embedding: list[float]
    query_text: str
    rewrite_result: RewriteResult
    timestamp: float


# ============================================================================
# 内部辅助函数
# ============================================================================


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _parse_rewrite_json(raw: object) -> dict:
    """JSON 5 层防御解析 — 从原始 LLM 响应中提取改写结果。

    层级:
    0 — API 层 response_format: json_object（chat_json 已处理）
    1 — 已是 dict → 直接使用
    1 — 是 str → json.loads
    2 — 正则提取 ```json ... ```
    3 — 正则提取最外层 {...}
    4 — Schema 校验（needs_rewrite 存在 + bool；needs_rewrite=true 时 rewritten_query 非空）
    返回 dict 包含原始字段；降级时附加 _degraded: True。
    """
    obj: object = raw

    # Layer 1: 已是 dict → 直接使用
    if isinstance(obj, dict):
        pass
    elif isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except (json.JSONDecodeError, TypeError, ValueError):
            # Layer 2: 正则提取 ```json ... ```
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", obj, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group(1))
                except (json.JSONDecodeError, TypeError, ValueError):
                    # Layer 3: 正则提取最外层 {...}
                    m2 = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", obj)
                    if m2:
                        try:
                            obj = json.loads(m2.group())
                        except (json.JSONDecodeError, TypeError, ValueError):
                            return _degraded("JSON 解析全部失败")
                    else:
                        return _degraded("无法提取 JSON")
            else:
                # Layer 3: 直接尝试提取 {...}
                m2 = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", obj)
                if m2:
                    try:
                        obj = json.loads(m2.group())
                    except (json.JSONDecodeError, TypeError, ValueError):
                        return _degraded("JSON 解析全部失败")
                else:
                    return _degraded("无法提取 JSON")
    else:
        return _degraded(f"不支持的类型: {type(obj).__name__}")

    # 此时 obj 应为 dict
    if not isinstance(obj, dict):
        return _degraded(f"解析结果不是 dict: {type(obj).__name__}")

    # Layer 4: Schema 校验
    if "needs_rewrite" not in obj:
        return _degraded("缺少 needs_rewrite 字段")

    needs = obj["needs_rewrite"]
    if not isinstance(needs, bool):
        return _degraded(f"needs_rewrite 不是布尔值: {type(needs).__name__}")

    if needs:
        rq = obj.get("rewritten_query")
        if not rq or not isinstance(rq, str) or not rq.strip():
            return _degraded("needs_rewrite=true 但 rewritten_query 为空")

    # 确保 reason 存在
    if "reason" not in obj:
        obj["reason"] = ""
    if not isinstance(obj.get("reason"), str):
        obj["reason"] = str(obj.get("reason", ""))

    return obj


def _degraded(reason: str) -> dict:
    """构造降级标记 dict。"""
    return {"_degraded": True, "reason": reason}


def _parse_refine_json(raw: object) -> str | None:
    """解析二次精炼的 JSON 响应，提取 rewritten_query。失败返回 None。"""
    obj: object = raw
    if isinstance(obj, dict):
        pass
    elif isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except (json.JSONDecodeError, TypeError, ValueError):
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", obj, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group(1))
                except (json.JSONDecodeError, TypeError, ValueError):
                    return None
            else:
                m2 = re.search(r"\{[^{}]*\}", obj)
                if m2:
                    try:
                        obj = json.loads(m2.group())
                    except (json.JSONDecodeError, TypeError, ValueError):
                        return None
                else:
                    return None
    else:
        return None

    if not isinstance(obj, dict):
        return None
    rq = obj.get("rewritten_query")
    if isinstance(rq, str) and rq.strip():
        return rq.strip()
    return None


# ============================================================================
# LLMRewriteProvider
# ============================================================================


class LLMRewriteProvider:
    """LLM 驱动的查询改写提供者。

    一次 LLM 调用同时完成"判断是否需要改写"和"执行改写"。
    内部维护向量相似度缓存，与 Rerank 缓存策略一致。

    降级责任在内部：rewrite 永不抛异常，失败返回原始 query。
    reason 字段仅日志使用，不影响业务逻辑。
    """

    def __init__(
        self,
        *,
        llm: LLMProvider,
        embedder: EmbedderPort,
        cache_similarity_threshold: float = 0.95,
        cache_max_entries: int = 100,
        cache_ttl_seconds: int = 300,
        temperature: float = 0.0,
    ) -> None:
        self.llm = llm
        self.embedder = embedder
        self.cache_similarity_threshold = cache_similarity_threshold
        self.cache_max_entries = cache_max_entries
        self.cache_ttl_seconds = cache_ttl_seconds
        self.temperature = temperature
        self._cache: dict[str, list[CacheEntry]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def rewrite(
        self,
        *,
        query: str,
        kb_ids: list[str],
    ) -> RewriteResult:
        """改写查询 — 永不抛异常。

        流程:
        a) 查缓存（向量余弦相似度 ≥ 阈值）
        b) LLM 调用（判断 + 改写一次完成）
        c) 5 层防御解析
        d) Layer 5 内容合理性检查（含二次精炼）
        e) 写入缓存
        f) 降级时返回原始 query
        """
        try:
            return await self._rewrite_impl(query=query, kb_ids=kb_ids)
        except Exception as exc:
            reason = f"rewrite 失败，降级为原始 query: {type(exc).__name__}: {exc}"
            self._log_degraded(kb_ids, query, type(exc).__name__, str(exc))
            return RewriteResult(
                original_query=query,
                rewritten_query=query,
                needs_rewrite=False,
                reason=reason,
            )

    async def clear_cache(self, kb_id: str) -> None:
        """清空指定 KB 的改写缓存。文档上传后由 composition.py 调用。"""
        async with self._lock:
            self._cache.pop(kb_id, None)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    async def _rewrite_impl(
        self,
        *,
        query: str,
        kb_ids: list[str],
    ) -> RewriteResult:
        """rewrite 核心实现 — 含缓存、LLM、防御、精炼。"""
        # Step a) 查缓存
        for kb_id in kb_ids:
            cached = await self._check_cache(kb_id, query)
            if cached is not None:
                return cached

        # Step b) LLM 调用
        try:
            parsed = await self._call_llm(query)
        except Exception as exc:
            reason = f"LLM 调用失败: {type(exc).__name__}: {exc}"
            self._log_degraded(kb_ids, query, type(exc).__name__, str(exc))
            return RewriteResult(
                original_query=query,
                rewritten_query=query,
                needs_rewrite=False,
                reason=reason,
            )

        # 降级检查
        if parsed.get("_degraded"):
            reason = f"JSON 解析降级: {parsed.get('reason', '未知原因')}"
            self._log_degraded(kb_ids, query, "ParseError", reason)
            return RewriteResult(
                original_query=query,
                rewritten_query=query,
                needs_rewrite=False,
                reason=reason,
            )

        needs_rewrite: bool = parsed["needs_rewrite"]
        rewritten_query: str = parsed.get("rewritten_query") or query
        llm_reason: str = parsed.get("reason", "")

        # Layer 5: 内容合理性检查
        result = self._layer5_checks(query, needs_rewrite, rewritten_query, llm_reason)
        if result is not None:
            return result

        # 二次精炼：rewritten_query > 200 字时触发
        if needs_rewrite and len(rewritten_query) > 200:
            refined_query, llm_reason = await self._refine_if_needed(
                query, rewritten_query, llm_reason
            )
            if refined_query == query:
                # 精炼失败降级
                return RewriteResult(
                    original_query=query,
                    rewritten_query=query,
                    needs_rewrite=False,
                    reason=llm_reason,
                )
            rewritten_query = refined_query

        # Step e) 写入缓存
        final_result = RewriteResult(
            original_query=query,
            rewritten_query=rewritten_query if needs_rewrite else query,
            needs_rewrite=needs_rewrite,
            reason=llm_reason,
        )
        await self._write_cache(kb_ids, query, final_result)

        # 日志
        try:
            logger.info(
                "",
                extra={
                    "event_type": "BIZ_EVENT",
                    "event": "rewrite_completed",
                    "kb_ids": kb_ids,
                    "original_query": query[:200],
                    "rewritten_query": final_result.rewritten_query[:200],
                    "needs_rewrite": needs_rewrite,
                    "reason": llm_reason,
                },
            )
        except Exception:
            logger.debug("BIZ_EVENT 日志写入失败", exc_info=True)

        return final_result

    async def _call_llm(self, query: str) -> dict:
        """调用 LLM 完成判断+改写，返回解析后的 dict。"""
        llm_response = await self.llm.chat_json(
            system_prompt=SYSTEM_PROMPT,
            user_payload={"query": query},
            temperature=self.temperature,
        )
        return _parse_rewrite_json(llm_response)

    def _layer5_checks(
        self,
        query: str,
        needs_rewrite: bool,
        rewritten_query: str,
        llm_reason: str,
    ) -> RewriteResult | None:
        """Layer 5 内容合理性检查。返回 RewriteResult 表示降级，None 表示通过。"""
        # 不需要改写 → 直接通过
        if not needs_rewrite:
            return None

        # 为空 → 降级
        if not rewritten_query or not rewritten_query.strip():
            return RewriteResult(
                original_query=query,
                rewritten_query=query,
                needs_rewrite=False,
                reason="Layer 5: rewritten_query 为空",
            )

        # 与原始相同 → 降级
        if rewritten_query.strip() == query.strip():
            return RewriteResult(
                original_query=query,
                rewritten_query=query,
                needs_rewrite=False,
                reason="Layer 5: rewritten_query 与原始相同",
            )

        # None of the above triggered → passed
        return None

    async def _refine_if_needed(
        self,
        query: str,
        rewritten_query: str,
        llm_reason: str,
    ) -> tuple[str, str]:
        """如果 rewritten_query > 200 字，触发二次精炼。返回 (final_query, reason)。"""
        if len(rewritten_query) <= 200:
            return rewritten_query, llm_reason

        try:
            refined_response = await self.llm.chat_json(
                system_prompt=REFINE_SYSTEM_PROMPT,
                user_payload={"query": rewritten_query},
                temperature=self.temperature,
            )
            refined = _parse_refine_json(refined_response)
            if refined and refined.strip():
                return refined, f"{llm_reason}（二次精炼）"
        except Exception:
            pass

        # 精炼失败 → 降级
        return query, "二次精炼失败，降级为原始 query"

    # ------------------------------------------------------------------
    # 缓存
    # ------------------------------------------------------------------

    async def _check_cache(self, kb_id: str, query: str) -> RewriteResult | None:
        """检查缓存是否命中。命中返回缓存结果，否则返回 None。

        缓存查找需要 embed query 以计算余弦相似度。
        embed 失败时不阻断流程，返回 None 走 LLM 路径。
        """
        try:
            vectors = await self.embedder.embed([query])
            query_vector = vectors[0]
        except Exception:
            return None  # embed 失败 → 缓存未命中，继续走 LLM

        now = time.monotonic()
        async with self._lock:
            entries = self._cache.get(kb_id, [])
            best_sim = -1.0
            best_entry: CacheEntry | None = None

            for entry in entries:
                # TTL 过期检查
                if now - entry.timestamp > self.cache_ttl_seconds:
                    continue
                sim = _cosine_similarity(query_vector, entry.query_embedding)
                if sim >= self.cache_similarity_threshold and sim > best_sim:
                    best_sim = sim
                    best_entry = entry

            if best_entry is not None:
                # 日志：缓存命中
                try:
                    logger.info(
                        "",
                        extra={
                            "event_type": "BIZ_EVENT",
                            "event": "rewrite_cache_hit",
                            "kb_ids": [kb_id],
                            "query": query[:200],
                            "similarity": round(best_sim, 4),
                        },
                    )
                except Exception:
                    logger.debug("BIZ_EVENT 日志写入失败", exc_info=True)

                return best_entry.rewrite_result

        return None

    async def _write_cache(
        self, kb_ids: list[str], query: str, result: RewriteResult
    ) -> None:
        """将改写结果写入所有 KB 的缓存。"""
        try:
            vectors = await self.embedder.embed([query])
            query_vector = vectors[0]
        except Exception:
            return  # embed 失败 → 跳过缓存写入

        now = time.monotonic()
        entry = CacheEntry(
            query_embedding=query_vector,
            query_text=query,
            rewrite_result=result,
            timestamp=now,
        )

        async with self._lock:
            for kb_id in kb_ids:
                entries = self._cache.setdefault(kb_id, [])
                # 清理过期条目
                entries[:] = [
                    e for e in entries if now - e.timestamp <= self.cache_ttl_seconds
                ]
                # 添加入口
                entries.append(entry)
                # 超限踢最旧
                while len(entries) > self.cache_max_entries:
                    entries.pop(0)

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------

    def _log_degraded(
        self,
        kb_ids: list[str],
        query: str,
        error_type: str,
        error_message: str,
    ) -> None:
        """记录降级日志。"""
        try:
            logger.warning(
                "rewrite 失败，降级为原始 query",
                extra={
                    "event_type": "BIZ_EVENT",
                    "event": "rewrite_degraded",
                    "kb_ids": kb_ids,
                    "query": query[:200],
                    "error_type": error_type,
                    "error_message": error_message,
                },
            )
        except Exception:
            logger.debug("BIZ_EVENT 日志写入失败", exc_info=True)
