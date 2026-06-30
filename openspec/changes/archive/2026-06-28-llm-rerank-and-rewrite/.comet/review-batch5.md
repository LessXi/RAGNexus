5316fe2 feat(rewrite): 实现 LLMRewriteProvider
5e27ce6 feat(rewrite): 创建 NoopRewriteProvider 直通实现
62eb920 feat(domain): 新增 RewritePort Protocol + RewriteResult dataclass

 src/ragnexus/adapters/rewrite/__init__.py |   6 +
 src/ragnexus/adapters/rewrite/llm.py      | 537 ++++++++++++++++++++++++++++++
 src/ragnexus/adapters/rewrite/noop.py     |  32 ++
 src/ragnexus/domain/ports.py              |  29 ++
 tests/unit/test_llm_rewrite.py            | 476 ++++++++++++++++++++++++++
 tests/unit/test_noop_rewrite.py           | 115 +++++++
 tests/unit/test_rewrite_port.py           | 140 ++++++++
 7 files changed, 1335 insertions(+)

diff --git a/src/ragnexus/adapters/rewrite/__init__.py b/src/ragnexus/adapters/rewrite/__init__.py
new file mode 100644
index 0000000..a59cd8a
--- /dev/null
+++ b/src/ragnexus/adapters/rewrite/__init__.py
@@ -0,0 +1,6 @@
+"""查询改写适配器包。"""
+
+from ragnexus.adapters.rewrite.llm import LLMRewriteProvider
+from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
+
+__all__ = ["LLMRewriteProvider", "NoopRewriteProvider"]
diff --git a/src/ragnexus/adapters/rewrite/llm.py b/src/ragnexus/adapters/rewrite/llm.py
new file mode 100644
index 0000000..3dc7710
--- /dev/null
+++ b/src/ragnexus/adapters/rewrite/llm.py
@@ -0,0 +1,537 @@
+"""LLM 查询改写适配器 — LLMRewriteProvider。
+
+基于 LLM 的查询改写实现，包含：
+- 向量相似度缓存（cosine ≥ 阈值）
+- 一次 LLM 调用完成判断+改写
+- JSON 5 层防御解析
+- 二次精炼（>200 字时压缩）
+- 降级返回原始 query（永不抛异常）
+- BIZ_EVENT 结构化日志
+"""
+
+from __future__ import annotations
+
+import asyncio
+import json
+import math
+import re
+import time
+from dataclasses import dataclass
+
+from ragnexus.adapters.llm.base import LLMProvider
+from ragnexus.core.logger import logger
+from ragnexus.domain.ports import EmbedderPort, RewriteResult
+
+# ============================================================================
+# System Prompt
+# ============================================================================
+
+SYSTEM_PROMPT = (
+    "你是 RAG 检索查询优化器。分析用户的原始查询，判断是否需要改写为更适合向量检索的形式，"
+    "如果需要则直接给出改写结果。\n\n"
+    "判断标准：\n"
+    "- 如果查询包含明确的关键词、名词、专业术语，且语义清晰 → 不需要改写\n"
+    "- 如果查询存在以下问题 → 需要改写：\n"
+    '  · 过于口语化（"上次那个"、"怎么搞的"）\n'
+    '  · 包含指代词（"这个"、"那个"、"它"）\n'
+    "  · 过于简短（缺少关键词）\n"
+    "  · 表述模糊\n\n"
+    "改写要求：\n"
+    "- 展开缩写和指代，补充隐含的上下文关键词\n"
+    "- 保留用户的核心意图，不要添加用户未提及的信息\n"
+    "- 改写后长度控制在 5-50 字\n"
+    "- 改写结果更适合中文向量检索\n\n"
+    "只返回 JSON，不要返回 Markdown，不要返回解释性文字。"
+)
+
+REFINE_SYSTEM_PROMPT = (
+    "请将以下查询改写结果压缩到 50 字以内，保持核心关键词和语义。"
+    '只返回 JSON：{"rewritten_query": "..."}'
+)
+
+# ============================================================================
+# CacheEntry
+# ============================================================================
+
+
+@dataclass
+class CacheEntry:
+    """改写缓存条目。"""
+
+    query_embedding: list[float]
+    query_text: str
+    rewrite_result: RewriteResult
+    timestamp: float
+
+
+# ============================================================================
+# 内部辅助函数
+# ============================================================================
+
+
+def _cosine_similarity(a: list[float], b: list[float]) -> float:
+    """计算两个向量的余弦相似度。"""
+    if not a or not b or len(a) != len(b):
+        return 0.0
+    dot = sum(x * y for x, y in zip(a, b, strict=True))
+    na = math.sqrt(sum(x * x for x in a))
+    nb = math.sqrt(sum(y * y for y in b))
+    if na == 0.0 or nb == 0.0:
+        return 0.0
+    return dot / (na * nb)
+
+
+def _parse_rewrite_json(raw: object) -> dict:
+    """JSON 5 层防御解析 — 从原始 LLM 响应中提取改写结果。
+
+    层级:
+    0 — API 层 response_format: json_object（chat_json 已处理）
+    1 — 已是 dict → 直接使用
+    1 — 是 str → json.loads
+    2 — 正则提取 ```json ... ```
+    3 — 正则提取最外层 {...}
+    4 — Schema 校验（needs_rewrite 存在 + bool；needs_rewrite=true 时 rewritten_query 非空）
+    返回 dict 包含原始字段；降级时附加 _degraded: True。
+    """
+    obj: object = raw
+
+    # Layer 1: 已是 dict → 直接使用
+    if isinstance(obj, dict):
+        pass
+    elif isinstance(obj, str):
+        try:
+            obj = json.loads(obj)
+        except (json.JSONDecodeError, TypeError, ValueError):
+            # Layer 2: 正则提取 ```json ... ```
+            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", obj, re.DOTALL)
+            if m:
+                try:
+                    obj = json.loads(m.group(1))
+                except (json.JSONDecodeError, TypeError, ValueError):
+                    # Layer 3: 正则提取最外层 {...}
+                    m2 = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", obj)
+                    if m2:
+                        try:
+                            obj = json.loads(m2.group())
+                        except (json.JSONDecodeError, TypeError, ValueError):
+                            return _degraded("JSON 解析全部失败")
+                    else:
+                        return _degraded("无法提取 JSON")
+            else:
+                # Layer 3: 直接尝试提取 {...}
+                m2 = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", obj)
+                if m2:
+                    try:
+                        obj = json.loads(m2.group())
+                    except (json.JSONDecodeError, TypeError, ValueError):
+                        return _degraded("JSON 解析全部失败")
+                else:
+                    return _degraded("无法提取 JSON")
+    else:
+        return _degraded(f"不支持的类型: {type(obj).__name__}")
+
+    # 此时 obj 应为 dict
+    if not isinstance(obj, dict):
+        return _degraded(f"解析结果不是 dict: {type(obj).__name__}")
+
+    # Layer 4: Schema 校验
+    if "needs_rewrite" not in obj:
+        return _degraded("缺少 needs_rewrite 字段")
+
+    needs = obj["needs_rewrite"]
+    if not isinstance(needs, bool):
+        return _degraded(f"needs_rewrite 不是布尔值: {type(needs).__name__}")
+
+    if needs:
+        rq = obj.get("rewritten_query")
+        if not rq or not isinstance(rq, str) or not rq.strip():
+            return _degraded("needs_rewrite=true 但 rewritten_query 为空")
+
+    # 确保 reason 存在
+    if "reason" not in obj:
+        obj["reason"] = ""
+    if not isinstance(obj.get("reason"), str):
+        obj["reason"] = str(obj.get("reason", ""))
+
+    return obj
+
+
+def _degraded(reason: str) -> dict:
+    """构造降级标记 dict。"""
+    return {"_degraded": True, "reason": reason}
+
+
+def _parse_refine_json(raw: object) -> str | None:
+    """解析二次精炼的 JSON 响应，提取 rewritten_query。失败返回 None。"""
+    obj: object = raw
+    if isinstance(obj, dict):
+        pass
+    elif isinstance(obj, str):
+        try:
+            obj = json.loads(obj)
+        except (json.JSONDecodeError, TypeError, ValueError):
+            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", obj, re.DOTALL)
+            if m:
+                try:
+                    obj = json.loads(m.group(1))
+                except (json.JSONDecodeError, TypeError, ValueError):
+                    return None
+            else:
+                m2 = re.search(r"\{[^{}]*\}", obj)
+                if m2:
+                    try:
+                        obj = json.loads(m2.group())
+                    except (json.JSONDecodeError, TypeError, ValueError):
+                        return None
+                else:
+                    return None
+    else:
+        return None
+
+    if not isinstance(obj, dict):
+        return None
+    rq = obj.get("rewritten_query")
+    if isinstance(rq, str) and rq.strip():
+        return rq.strip()
+    return None
+
+
+# ============================================================================
+# LLMRewriteProvider
+# ============================================================================
+
+
+class LLMRewriteProvider:
+    """LLM 驱动的查询改写提供者。
+
+    一次 LLM 调用同时完成"判断是否需要改写"和"执行改写"。
+    内部维护向量相似度缓存，与 Rerank 缓存策略一致。
+
+    降级责任在内部：rewrite 永不抛异常，失败返回原始 query。
+    reason 字段仅日志使用，不影响业务逻辑。
+    """
+
+    def __init__(
+        self,
+        *,
+        llm: LLMProvider,
+        embedder: EmbedderPort,
+        cache_similarity_threshold: float = 0.95,
+        cache_max_entries: int = 100,
+        cache_ttl_seconds: int = 300,
+        temperature: float = 0.0,
+    ) -> None:
+        self.llm = llm
+        self.embedder = embedder
+        self.cache_similarity_threshold = cache_similarity_threshold
+        self.cache_max_entries = cache_max_entries
+        self.cache_ttl_seconds = cache_ttl_seconds
+        self.temperature = temperature
+        self._cache: dict[str, list[CacheEntry]] = {}
+        self._lock = asyncio.Lock()
+
+    # ------------------------------------------------------------------
+    # 公共接口
+    # ------------------------------------------------------------------
+
+    async def rewrite(
+        self,
+        *,
+        query: str,
+        kb_ids: list[str],
+    ) -> RewriteResult:
+        """改写查询 — 永不抛异常。
+
+        流程:
+        a) 查缓存（向量余弦相似度 ≥ 阈值）
+        b) LLM 调用（判断 + 改写一次完成）
+        c) 5 层防御解析
+        d) Layer 5 内容合理性检查（含二次精炼）
+        e) 写入缓存
+        f) 降级时返回原始 query
+        """
+        try:
+            return await self._rewrite_impl(query=query, kb_ids=kb_ids)
+        except Exception as exc:
+            reason = f"rewrite 失败，降级为原始 query: {type(exc).__name__}: {exc}"
+            self._log_degraded(kb_ids, query, type(exc).__name__, str(exc))
+            return RewriteResult(
+                original_query=query,
+                rewritten_query=query,
+                needs_rewrite=False,
+                reason=reason,
+            )
+
+    async def clear_cache(self, kb_id: str) -> None:
+        """清空指定 KB 的改写缓存。文档上传后由 composition.py 调用。"""
+        async with self._lock:
+            self._cache.pop(kb_id, None)
+
+    # ------------------------------------------------------------------
+    # 内部实现
+    # ------------------------------------------------------------------
+
+    async def _rewrite_impl(
+        self,
+        *,
+        query: str,
+        kb_ids: list[str],
+    ) -> RewriteResult:
+        """rewrite 核心实现 — 含缓存、LLM、防御、精炼。"""
+        # Step a) 查缓存
+        for kb_id in kb_ids:
+            cached = await self._check_cache(kb_id, query)
+            if cached is not None:
+                return cached
+
+        # Step b) LLM 调用
+        try:
+            parsed = await self._call_llm(query)
+        except Exception as exc:
+            reason = f"LLM 调用失败: {type(exc).__name__}: {exc}"
+            self._log_degraded(kb_ids, query, type(exc).__name__, str(exc))
+            return RewriteResult(
+                original_query=query,
+                rewritten_query=query,
+                needs_rewrite=False,
+                reason=reason,
+            )
+
+        # 降级检查
+        if parsed.get("_degraded"):
+            reason = f"JSON 解析降级: {parsed.get('reason', '未知原因')}"
+            self._log_degraded(kb_ids, query, "ParseError", reason)
+            return RewriteResult(
+                original_query=query,
+                rewritten_query=query,
+                needs_rewrite=False,
+                reason=reason,
+            )
+
+        needs_rewrite: bool = parsed["needs_rewrite"]
+        rewritten_query: str = parsed.get("rewritten_query") or query
+        llm_reason: str = parsed.get("reason", "")
+
+        # Layer 5: 内容合理性检查
+        result = self._layer5_checks(query, needs_rewrite, rewritten_query, llm_reason)
+        if result is not None:
+            return result
+
+        # 二次精炼：rewritten_query > 200 字时触发
+        if needs_rewrite and len(rewritten_query) > 200:
+            refined_query, llm_reason = await self._refine_if_needed(
+                query, rewritten_query, llm_reason
+            )
+            if refined_query == query:
+                # 精炼失败降级
+                return RewriteResult(
+                    original_query=query,
+                    rewritten_query=query,
+                    needs_rewrite=False,
+                    reason=llm_reason,
+                )
+            rewritten_query = refined_query
+
+        # Step e) 写入缓存
+        final_result = RewriteResult(
+            original_query=query,
+            rewritten_query=rewritten_query if needs_rewrite else query,
+            needs_rewrite=needs_rewrite,
+            reason=llm_reason,
+        )
+        await self._write_cache(kb_ids, query, final_result)
+
+        # 日志
+        try:
+            logger.info(
+                "",
+                extra={
+                    "event_type": "BIZ_EVENT",
+                    "event": "rewrite_completed",
+                    "kb_ids": kb_ids,
+                    "original_query": query[:200],
+                    "rewritten_query": final_result.rewritten_query[:200],
+                    "needs_rewrite": needs_rewrite,
+                    "reason": llm_reason,
+                },
+            )
+        except Exception:
+            logger.debug("BIZ_EVENT 日志写入失败", exc_info=True)
+
+        return final_result
+
+    async def _call_llm(self, query: str) -> dict:
+        """调用 LLM 完成判断+改写，返回解析后的 dict。"""
+        llm_response = await self.llm.chat_json(
+            system_prompt=SYSTEM_PROMPT,
+            user_payload={"query": query},
+            temperature=self.temperature,
+        )
+        return _parse_rewrite_json(llm_response)
+
+    def _layer5_checks(
+        self,
+        query: str,
+        needs_rewrite: bool,
+        rewritten_query: str,
+        llm_reason: str,
+    ) -> RewriteResult | None:
+        """Layer 5 内容合理性检查。返回 RewriteResult 表示降级，None 表示通过。"""
+        # 不需要改写 → 直接通过
+        if not needs_rewrite:
+            return None
+
+        # 为空 → 降级
+        if not rewritten_query or not rewritten_query.strip():
+            return RewriteResult(
+                original_query=query,
+                rewritten_query=query,
+                needs_rewrite=False,
+                reason="Layer 5: rewritten_query 为空",
+            )
+
+        # 与原始相同 → 降级
+        if rewritten_query.strip() == query.strip():
+            return RewriteResult(
+                original_query=query,
+                rewritten_query=query,
+                needs_rewrite=False,
+                reason="Layer 5: rewritten_query 与原始相同",
+            )
+
+        # None of the above triggered → passed
+        return None
+
+    async def _refine_if_needed(
+        self,
+        query: str,
+        rewritten_query: str,
+        llm_reason: str,
+    ) -> tuple[str, str]:
+        """如果 rewritten_query > 200 字，触发二次精炼。返回 (final_query, reason)。"""
+        if len(rewritten_query) <= 200:
+            return rewritten_query, llm_reason
+
+        try:
+            refined_response = await self.llm.chat_json(
+                system_prompt=REFINE_SYSTEM_PROMPT,
+                user_payload={"query": rewritten_query},
+                temperature=self.temperature,
+            )
+            refined = _parse_refine_json(refined_response)
+            if refined and refined.strip():
+                return refined, f"{llm_reason}（二次精炼）"
+        except Exception:
+            pass
+
+        # 精炼失败 → 降级
+        return query, "二次精炼失败，降级为原始 query"
+
+    # ------------------------------------------------------------------
+    # 缓存
+    # ------------------------------------------------------------------
+
+    async def _check_cache(self, kb_id: str, query: str) -> RewriteResult | None:
+        """检查缓存是否命中。命中返回缓存结果，否则返回 None。
+
+        缓存查找需要 embed query 以计算余弦相似度。
+        embed 失败时不阻断流程，返回 None 走 LLM 路径。
+        """
+        try:
+            vectors = await self.embedder.embed([query])
+            query_vector = vectors[0]
+        except Exception:
+            return None  # embed 失败 → 缓存未命中，继续走 LLM
+
+        now = time.monotonic()
+        async with self._lock:
+            entries = self._cache.get(kb_id, [])
+            best_sim = -1.0
+            best_entry: CacheEntry | None = None
+
+            for entry in entries:
+                # TTL 过期检查
+                if now - entry.timestamp > self.cache_ttl_seconds:
+                    continue
+                sim = _cosine_similarity(query_vector, entry.query_embedding)
+                if sim >= self.cache_similarity_threshold and sim > best_sim:
+                    best_sim = sim
+                    best_entry = entry
+
+            if best_entry is not None:
+                # 日志：缓存命中
+                try:
+                    logger.info(
+                        "",
+                        extra={
+                            "event_type": "BIZ_EVENT",
+                            "event": "rewrite_cache_hit",
+                            "kb_ids": [kb_id],
+                            "query": query[:200],
+                            "similarity": round(best_sim, 4),
+                        },
+                    )
+                except Exception:
+                    logger.debug("BIZ_EVENT 日志写入失败", exc_info=True)
+
+                return best_entry.rewrite_result
+
+        return None
+
+    async def _write_cache(
+        self, kb_ids: list[str], query: str, result: RewriteResult
+    ) -> None:
+        """将改写结果写入所有 KB 的缓存。"""
+        try:
+            vectors = await self.embedder.embed([query])
+            query_vector = vectors[0]
+        except Exception:
+            return  # embed 失败 → 跳过缓存写入
+
+        now = time.monotonic()
+        entry = CacheEntry(
+            query_embedding=query_vector,
+            query_text=query,
+            rewrite_result=result,
+            timestamp=now,
+        )
+
+        async with self._lock:
+            for kb_id in kb_ids:
+                entries = self._cache.setdefault(kb_id, [])
+                # 清理过期条目
+                entries[:] = [
+                    e for e in entries if now - e.timestamp <= self.cache_ttl_seconds
+                ]
+                # 添加入口
+                entries.append(entry)
+                # 超限踢最旧
+                while len(entries) > self.cache_max_entries:
+                    entries.pop(0)
+
+    # ------------------------------------------------------------------
+    # 日志
+    # ------------------------------------------------------------------
+
+    def _log_degraded(
+        self,
+        kb_ids: list[str],
+        query: str,
+        error_type: str,
+        error_message: str,
+    ) -> None:
+        """记录降级日志。"""
+        try:
+            logger.warning(
+                "rewrite 失败，降级为原始 query",
+                extra={
+                    "event_type": "BIZ_EVENT",
+                    "event": "rewrite_degraded",
+                    "kb_ids": kb_ids,
+                    "query": query[:200],
+                    "error_type": error_type,
+                    "error_message": error_message,
+                },
+            )
+        except Exception:
+            logger.debug("BIZ_EVENT 日志写入失败", exc_info=True)
diff --git a/src/ragnexus/adapters/rewrite/noop.py b/src/ragnexus/adapters/rewrite/noop.py
new file mode 100644
index 0000000..a613749
--- /dev/null
+++ b/src/ragnexus/adapters/rewrite/noop.py
@@ -0,0 +1,32 @@
+"""空查询改写适配器 — NoopRewriteProvider。
+
+禁用改写时的直通实现：rewrite 返回原始 query，clear_cache 空实现。
+"""
+
+from ragnexus.domain.ports import RewriteResult
+
+
+class NoopRewriteProvider:
+    """空查询改写提供者 — 禁用改写时的直通实现。
+
+    rewrite 返回 RewriteResult（original=rewritten=query, needs_rewrite=False），
+    clear_cache 空实现（无缓存可清）。
+    """
+
+    async def rewrite(
+        self,
+        *,
+        query: str,
+        kb_ids: list[str],
+    ) -> RewriteResult:
+        """直通返回原始 query，不做任何改写。"""
+        return RewriteResult(
+            original_query=query,
+            rewritten_query=query,
+            needs_rewrite=False,
+            reason="禁用改写，直通",
+        )
+
+    async def clear_cache(self, kb_id: str) -> None:
+        """空实现 — 无缓存可清。"""
+        pass
diff --git a/src/ragnexus/domain/ports.py b/src/ragnexus/domain/ports.py
index 8a9152d..fce90a1 100644
--- a/src/ragnexus/domain/ports.py
+++ b/src/ragnexus/domain/ports.py
@@ -1,12 +1,13 @@
 """领域端口（Protocols）— 适配器接口契约。"""
 
+from dataclasses import dataclass
 from typing import Protocol
 
 from ragnexus.domain.models import Chunk, KnowledgeBase, ParsedDocument, SearchHit
 
 
 class VectorStorePort(Protocol):
     """向量存储 + 检索。骨架实现: pgvector。"""
 
     async def upsert(self, kb_id: str, chunks: list[Chunk]) -> None: ...
 
@@ -72,10 +73,38 @@ class RerankPort(Protocol):
         chunks: list[SearchHit],
         top_n: int,
     ) -> list[SearchHit]: ...
 
     async def clear_cache(self, kb_id: str) -> None:
         """清空指定 KB 的缓存。文档上传后由 composition.py 调用。
 
         NoopRerankProvider 实现为空。
         """
         ...
+
+
+@dataclass
+class RewriteResult:
+    """查询改写结果。"""
+
+    original_query: str
+    rewritten_query: str  # 不需要改写时 = original_query
+    needs_rewrite: bool
+    reason: str  # 仅日志使用
+
+
+class RewritePort(Protocol):
+    """查询改写端口 — 优化口语化/模糊 query 以提升向量检索效果。
+
+    骨架实现: LLMRewriteProvider (启用时), NoopRewriteProvider (禁用时)。
+    """
+
+    async def rewrite(
+        self,
+        *,
+        query: str,
+        kb_ids: list[str],
+    ) -> RewriteResult: ...
+
+    async def clear_cache(self, kb_id: str) -> None:
+        """清空指定 KB 的改写缓存。文档上传后由 composition.py 调用。"""
+        ...
diff --git a/tests/unit/test_llm_rewrite.py b/tests/unit/test_llm_rewrite.py
new file mode 100644
index 0000000..c02892a
--- /dev/null
+++ b/tests/unit/test_llm_rewrite.py
@@ -0,0 +1,476 @@
+"""LLMRewriteProvider 单元测试。
+
+测试场景：
+- 构造器参数存储
+- rewrite 正常流程（needs_rewrite=true）
+- rewrite 不需要改写（needs_rewrite=false）
+- 缓存命中（相同语义 query 跳过 LLM）
+- JSON 5 层防御（markdown 包裹、无效 JSON、缺字段）
+- 降级（LLM 异常 → 返回原始 query）
+- 降级（JSON 解析全失败 → 返回原始 query）
+- clear_cache 清空指定 KB
+- reason 字段仅日志不影响逻辑
+- 二次精炼（rewritten_query > 200 字）
+"""
+
+from __future__ import annotations
+
+from unittest.mock import AsyncMock, patch
+
+import pytest
+
+from ragnexus.adapters.llm.base import LLMProvider
+from ragnexus.domain.ports import RewriteResult
+
+# ============================================================================
+# Fake / Stub 类
+# ============================================================================
+
+
+class FakeLLMProvider(LLMProvider):
+    """模拟 LLMProvider：按预制 responses 顺序返回 JSON。"""
+
+    def __init__(self, responses: list[dict] | None = None):
+        self.responses = responses or []
+        self.call_count = 0
+        self._call_args: list[dict] = []
+
+    async def chat_json(
+        self,
+        *,
+        system_prompt: str,
+        user_payload: dict,
+        temperature: float = 0.0,
+        timeout_seconds: int | None = None,
+    ) -> dict:
+        self._call_args.append(
+            {
+                "system_prompt": system_prompt,
+                "user_payload": user_payload,
+                "temperature": temperature,
+                "timeout_seconds": timeout_seconds,
+            }
+        )
+        idx = self.call_count
+        self.call_count += 1
+        if idx < len(self.responses):
+            return self.responses[idx]
+        raise RuntimeError(f"FakeLLMProvider 用完了预置响应（索引 {idx}）")
+
+
+class FakeEmbedder:
+    """模拟 EmbedderPort：单个文本返回固定向量，多个文本返回固定向量列表。"""
+
+    def __init__(self, fixed_vector: list[float] | None = None):
+        self._fixed_vector = fixed_vector or [0.1, 0.2, 0.3]
+        self.embed_calls: list[list[str]] = []
+
+    async def embed(self, texts: list[str]) -> list[list[float]]:
+        self.embed_calls.append(texts)
+        return [self._fixed_vector] * len(texts)
+
+
+# ============================================================================
+# 导入被测类
+# ============================================================================
+
+from ragnexus.adapters.rewrite.llm import LLMRewriteProvider  # noqa: E402
+
+# ============================================================================
+# 测试
+# ============================================================================
+
+
+class TestConstructor:
+    """构造器参数存储测试。"""
+
+    def test_constructor_stores_defaults(self):
+        """构造器使用默认值时应存储所有参数。"""
+        llm = FakeLLMProvider()
+        embedder = FakeEmbedder()
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        assert provider.llm is llm
+        assert provider.embedder is embedder
+        assert provider.cache_similarity_threshold == 0.95
+        assert provider.cache_max_entries == 100
+        assert provider.cache_ttl_seconds == 300
+        assert provider.temperature == 0.0
+
+    def test_constructor_stores_custom_values(self):
+        """构造器使用自定义值时应存储所有参数。"""
+        llm = FakeLLMProvider()
+        embedder = FakeEmbedder()
+        provider = LLMRewriteProvider(
+            llm=llm,
+            embedder=embedder,
+            cache_similarity_threshold=0.9,
+            cache_max_entries=50,
+            cache_ttl_seconds=600,
+            temperature=0.3,
+        )
+
+        assert provider.cache_similarity_threshold == 0.9
+        assert provider.cache_max_entries == 50
+        assert provider.cache_ttl_seconds == 600
+        assert provider.temperature == 0.3
+
+
+class TestRewriteNormal:
+    """rewrite 正常流程测试。"""
+
+    @pytest.mark.asyncio
+    async def test_rewrite_needs_rewrite(self):
+        """LLM 返回 needs_rewrite=true 时，改写 query。"""
+        llm = FakeLLMProvider(
+            responses=[
+                {
+                    "needs_rewrite": True,
+                    "rewritten_query": "退款政策 申请条件 流程",
+                    "reason": "包含指代词'上次那个'",
+                }
+            ]
+        )
+        embedder = FakeEmbedder()
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        result = await provider.rewrite(query="上次那个退款的事", kb_ids=["kb1"])
+
+        assert result.original_query == "上次那个退款的事"
+        assert result.rewritten_query == "退款政策 申请条件 流程"
+        assert result.needs_rewrite is True
+        assert "指代词" in result.reason
+
+    @pytest.mark.asyncio
+    async def test_rewrite_no_rewrite_needed(self):
+        """LLM 返回 needs_rewrite=false 时，不改写。"""
+        llm = FakeLLMProvider(
+            responses=[
+                {
+                    "needs_rewrite": False,
+                    "rewritten_query": None,
+                    "reason": "查询已包含具体关键词",
+                }
+            ]
+        )
+        embedder = FakeEmbedder()
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        result = await provider.rewrite(query="退款政策 申请条件", kb_ids=["kb1"])
+
+        assert result.original_query == "退款政策 申请条件"
+        assert result.rewritten_query == "退款政策 申请条件"
+        assert result.needs_rewrite is False
+        assert "关键词" in result.reason
+
+
+class TestCacheHit:
+    """缓存测试。"""
+
+    @pytest.mark.asyncio
+    async def test_cache_hit_skips_llm(self):
+        """相同语义 query 第二次调用应命中缓存，跳过 LLM。"""
+        llm = FakeLLMProvider(
+            responses=[
+                {
+                    "needs_rewrite": True,
+                    "rewritten_query": "退款流程 步骤",
+                    "reason": "口语化",
+                }
+            ]
+        )
+        # 使用相同向量，确保余弦相似度 = 1.0，一定命中缓存
+        embedder = FakeEmbedder(fixed_vector=[1.0, 0.0, 0.0])
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        # 第一次调用 — 走 LLM
+        result1 = await provider.rewrite(query="怎么退款", kb_ids=["kb1"])
+        assert result1.rewritten_query == "退款流程 步骤"
+        assert llm.call_count == 1
+
+        # 第二次调用相同 query — 应命中缓存，不调用 LLM
+        result2 = await provider.rewrite(query="怎么退款", kb_ids=["kb1"])
+        assert result2.rewritten_query == "退款流程 步骤"
+        assert llm.call_count == 1  # 仍然为 1，未增加
+
+    @pytest.mark.asyncio
+    async def test_different_kb_no_cross_cache(self):
+        """不同 KB 之间缓存隔离。"""
+        llm = FakeLLMProvider(
+            responses=[
+                {
+                    "needs_rewrite": True,
+                    "rewritten_query": "退款流程",
+                    "reason": "口语化",
+                },
+                {
+                    "needs_rewrite": True,
+                    "rewritten_query": "退货说明",
+                    "reason": "口语化",
+                },
+            ]
+        )
+        embedder = FakeEmbedder(fixed_vector=[1.0, 0.0, 0.0])
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        r1 = await provider.rewrite(query="怎么退款", kb_ids=["kb1"])
+        r2 = await provider.rewrite(query="怎么退款", kb_ids=["kb2"])
+
+        # 两个 KB 各自走一次 LLM（缓存未命中，因为 KB 不同）
+        assert llm.call_count == 2
+        assert r1.rewritten_query == "退款流程"
+        assert r2.rewritten_query == "退货说明"
+
+
+class TestJsonDefense:
+    """JSON 5 层防御测试。"""
+
+    @pytest.mark.asyncio
+    async def test_layer2_markdown_wrapped_json(self):
+        """Layer 2：正则提取 ```json ... ``` 包裹的 JSON。"""
+        from ragnexus.adapters.rewrite.llm import _parse_rewrite_json
+
+        raw = '```json\n{"needs_rewrite": true, "rewritten_query": "测试改写", "reason": "OK"}\n```'
+        result = _parse_rewrite_json(raw)
+        assert result["needs_rewrite"] is True
+        assert result["rewritten_query"] == "测试改写"
+
+    @pytest.mark.asyncio
+    async def test_layer3_outer_braces_extract(self):
+        """Layer 3：正则提取最外层 {...}。"""
+        from ragnexus.adapters.rewrite.llm import _parse_rewrite_json
+
+        raw = '前缀文本 {"needs_rewrite": false, "rewritten_query": null, "reason": "清晰"} 后缀'
+        result = _parse_rewrite_json(raw)
+        assert result["needs_rewrite"] is False
+        assert result["reason"] == "清晰"
+
+    @pytest.mark.asyncio
+    async def test_layer4_schema_validation_missing_field(self):
+        """Layer 4：缺 needs_rewrite 字段 → 降级。"""
+        from ragnexus.adapters.rewrite.llm import _parse_rewrite_json
+
+        raw = '{"rewritten_query": "xxx", "reason": "yyy"}'
+        result = _parse_rewrite_json(raw)
+        # 降级应返回降级 dict
+        assert result.get("_degraded") is True
+
+    @pytest.mark.asyncio
+    async def test_layer4_needs_rewrite_true_requires_rewritten_query(self):
+        """Layer 4：needs_rewrite=true 但 rewritten_query 为 null → 降级。"""
+        from ragnexus.adapters.rewrite.llm import _parse_rewrite_json
+
+        raw = '{"needs_rewrite": true, "rewritten_query": null, "reason": ""}'
+        result = _parse_rewrite_json(raw)
+        assert result.get("_degraded") is True
+
+    @pytest.mark.asyncio
+    async def test_total_parse_failure_degradation(self):
+        """全部 JSON 解析层失败 → 降级返回原始 query。"""
+        llm = FakeLLMProvider(responses=[{"some": "data"}])
+        embedder = FakeEmbedder()
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        # 模拟 _parse_rewrite_json 返回降级标记
+        with patch(
+            "ragnexus.adapters.rewrite.llm._parse_rewrite_json",
+            return_value={"_degraded": True, "reason": "JSON 解析全部失败"},
+        ):
+            result = await provider.rewrite(query="原始查询", kb_ids=["kb1"])
+
+        assert result.original_query == "原始查询"
+        assert result.rewritten_query == "原始查询"
+        assert result.needs_rewrite is False
+        assert "JSON" in result.reason
+
+
+class TestDegradation:
+    """降级测试。"""
+
+    @pytest.mark.asyncio
+    async def test_llm_exception_returns_original(self):
+        """LLM 抛异常 → 降级返回原始 query。"""
+        llm = FakeLLMProvider()
+        # 让 chat_json 抛出异常
+        llm.chat_json = AsyncMock(side_effect=Exception("LLM 超时"))
+        embedder = FakeEmbedder()
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        result = await provider.rewrite(query="原始查询", kb_ids=["kb1"])
+
+        assert result.original_query == "原始查询"
+        assert result.rewritten_query == "原始查询"
+        assert result.needs_rewrite is False
+        assert (
+            "失败" in result.reason
+            or "超时" in result.reason
+            or "异常" in result.reason
+        )
+
+    @pytest.mark.asyncio
+    async def test_embed_exception_returns_original(self):
+        """Embedder 抛异常 → 降级返回原始 query（缓存查找失败不阻断流程）。"""
+        llm = FakeLLMProvider()
+        embedder = FakeEmbedder()
+        embedder.embed = AsyncMock(side_effect=Exception("Embedder 不可用"))
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        result = await provider.rewrite(query="原始查询", kb_ids=["kb1"])
+
+        # 缓存查找失败不应阻断，应继续走 LLM
+        # 但因为 LLM 也没有响应，全链路降级
+        assert result.original_query == "原始查询"
+        assert result.rewritten_query == "原始查询"
+
+
+class TestClearCache:
+    """clear_cache 测试。"""
+
+    @pytest.mark.asyncio
+    async def test_clear_cache_removes_kb(self):
+        """clear_cache 清空指定 KB 的缓存。"""
+        llm = FakeLLMProvider(
+            responses=[
+                {"needs_rewrite": True, "rewritten_query": "改写1", "reason": "口语化"},
+                {"needs_rewrite": True, "rewritten_query": "改写2", "reason": "口语化"},
+            ]
+        )
+        embedder = FakeEmbedder(fixed_vector=[1.0, 0.0, 0.0])
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        # 缓存一个结果
+        await provider.rewrite(query="查询A", kb_ids=["kb1"])
+        assert llm.call_count == 1
+
+        # clear_cache 清空 kb1
+        await provider.clear_cache("kb1")
+
+        # 再次查询同一 query — 缓存已清空，应重新调用 LLM
+        result = await provider.rewrite(query="查询A", kb_ids=["kb1"])
+        assert result.rewritten_query == "改写2"
+        assert llm.call_count == 2  # 重新调用了 LLM
+
+    @pytest.mark.asyncio
+    async def test_clear_cache_does_not_affect_other_kb(self):
+        """clear_cache 不影响其他 KB 的缓存。"""
+        llm = FakeLLMProvider(
+            responses=[
+                {"needs_rewrite": True, "rewritten_query": "改写1", "reason": "口语化"},
+                {"needs_rewrite": True, "rewritten_query": "改写1", "reason": "口语化"},
+                {"needs_rewrite": True, "rewritten_query": "改写2", "reason": "口语化"},
+            ]
+        )
+        embedder = FakeEmbedder(fixed_vector=[1.0, 0.0, 0.0])
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        await provider.rewrite(query="查询A", kb_ids=["kb1"])
+        await provider.rewrite(query="查询A", kb_ids=["kb2"])
+        assert llm.call_count == 2
+
+        # 清空 kb1
+        await provider.clear_cache("kb1")
+
+        r2 = await provider.rewrite(query="查询A", kb_ids=["kb2"])
+        assert r2.rewritten_query == "改写1"
+        assert llm.call_count == 2  # kb2 命中缓存，未调 LLM
+        r1 = await provider.rewrite(query="查询A", kb_ids=["kb1"])
+        assert r1.rewritten_query == "改写2"
+        assert llm.call_count == 3  # kb1 缓存已清，重新调 LLM
+
+
+class TestReasonLoggingOnly:
+    """reason 字段仅日志使用，不影响业务逻辑。"""
+
+    @pytest.mark.asyncio
+    async def test_reason_not_used_in_business_logic(self):
+        """验证 reason 不影响业务逻辑 — 只出现在日志中。"""
+        llm = FakeLLMProvider(
+            responses=[
+                {
+                    "needs_rewrite": True,
+                    "rewritten_query": "改写后的查询",
+                    "reason": "任意原因 — 不影响改写结果",
+                }
+            ]
+        )
+        embedder = FakeEmbedder()
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        result = await provider.rewrite(query="原始查询", kb_ids=["kb1"])
+
+        # 业务逻辑只看 needs_rewrite 和 rewritten_query
+        assert result.needs_rewrite is True
+        assert result.rewritten_query == "改写后的查询"
+        # reason 存在，但仅用于日志
+        assert result.reason == "任意原因 — 不影响改写结果"
+
+
+class TestSecondPassRefinement:
+    """二次精炼测试。"""
+
+    @pytest.mark.asyncio
+    async def test_overly_long_rewrite_triggers_refinement(self):
+        """rewritten_query > 200 字时触发二次精炼。"""
+        long_text = "这是一个非常长的改写结果" * 20  # ~300 字
+        assert len(long_text) > 200
+
+        refined = "精炼后的短文本"
+        llm = FakeLLMProvider(
+            responses=[
+                {
+                    "needs_rewrite": True,
+                    "rewritten_query": long_text,
+                    "reason": "详细改写",
+                },
+                {"rewritten_query": refined},
+            ]
+        )
+        embedder = FakeEmbedder()
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        result = await provider.rewrite(query="原始查询", kb_ids=["kb1"])
+
+        assert result.rewritten_query == refined
+        assert result.needs_rewrite is True
+        assert llm.call_count == 2  # 主调用 + 精炼调用
+
+    @pytest.mark.asyncio
+    async def test_refinement_failure_degradation(self):
+        """二次精炼失败 → 降级返回原始 query。"""
+        long_text = "x" * 250  # > 200 字
+        llm = FakeLLMProvider()
+        llm.chat_json = AsyncMock(
+            side_effect=[
+                {"needs_rewrite": True, "rewritten_query": long_text, "reason": "过长"},
+                Exception("精炼调用失败"),
+            ]
+        )
+        embedder = FakeEmbedder()
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        result = await provider.rewrite(query="原始查询", kb_ids=["kb1"])
+
+        assert result.original_query == "原始查询"
+        assert result.rewritten_query == "原始查询"
+        assert result.needs_rewrite is False
+
+
+class TestAlwaysNoException:
+    """rewrite 永不抛异常测试。"""
+
+    @pytest.mark.asyncio
+    async def test_rewrite_never_raises(self):
+        """无论发生什么，rewrite() 永不抛异常。"""
+        llm = FakeLLMProvider()
+        llm.chat_json = AsyncMock(side_effect=RuntimeError("模拟崩溃"))
+        embedder = FakeEmbedder()
+        embedder.embed = AsyncMock(side_effect=RuntimeError("Embedder 崩溃"))
+        provider = LLMRewriteProvider(llm=llm, embedder=embedder)
+
+        # 不应抛出任何异常
+        result = await provider.rewrite(query="test", kb_ids=["kb1"])
+
+        assert isinstance(result, RewriteResult)
+        assert result.original_query == "test"
+        assert result.rewritten_query == "test"
+        assert result.needs_rewrite is False
diff --git a/tests/unit/test_noop_rewrite.py b/tests/unit/test_noop_rewrite.py
new file mode 100644
index 0000000..c430ac0
--- /dev/null
+++ b/tests/unit/test_noop_rewrite.py
@@ -0,0 +1,115 @@
+"""NoopRewriteProvider 单元测试。
+
+TDD: RED → GREEN。验证直通查询改写提供者的行为正确性。
+"""
+
+from __future__ import annotations
+
+import asyncio
+
+from ragnexus.domain.ports import RewritePort, RewriteResult
+
+
+class TestNoopRewriteProvider:
+    """NoopRewriteProvider 直通行为测试。"""
+
+    def test_provider_exists(self) -> None:
+        """NoopRewriteProvider 应从 adapters.rewrite 包导入。"""
+        from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
+
+        assert NoopRewriteProvider is not None
+
+    def test_satisfies_rewrite_port_protocol(self) -> None:
+        """NoopRewriteProvider 满足 RewritePort 协议 — 行为验证。
+
+        验证方法存在、签名匹配、以及实际调用返回类型正确。
+        """
+        import inspect
+
+        from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
+
+        instance = NoopRewriteProvider()
+        cls = NoopRewriteProvider
+
+        # 验证方法存在
+        assert hasattr(cls, "rewrite"), "缺少 rewrite 方法"
+        assert hasattr(cls, "clear_cache"), "缺少 clear_cache 方法"
+
+        # 验证 rewrite 签名：self + keyword-only 参数
+        rewrite_sig = inspect.signature(cls.rewrite)
+        rewrite_params = list(rewrite_sig.parameters.values())
+        assert (
+            rewrite_sig.return_annotation == RewriteResult
+        ), f"rewrite 返回类型应为 RewriteResult，实际: {rewrite_sig.return_annotation}"
+        for p in rewrite_params[1:]:
+            assert (
+                p.kind == inspect.Parameter.KEYWORD_ONLY
+            ), f"rewrite 参数 {p.name} 应为 KEYWORD_ONLY"
+
+        # 验证 clear_cache 签名
+        cc_sig = inspect.signature(cls.clear_cache)
+        cc_params = list(cc_sig.parameters.values())
+        assert len(cc_params) == 2  # self + kb_id
+        assert cc_params[1].name == "kb_id"
+        assert cc_params[1].annotation is str
+        assert cc_sig.return_annotation is None
+
+        # 验证实际行为：rewrite 返回 RewriteResult
+        async def _run() -> RewriteResult:
+            return await instance.rewrite(
+                query="test query",
+                kb_ids=["kb-1"],
+            )
+
+        result = asyncio.run(_run())
+        assert isinstance(result, RewriteResult)
+
+    def test_rewrite_returns_identity_no_modification(self) -> None:
+        """rewrite() 直通：original_query == rewritten_query == 输入 query。"""
+        from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
+
+        provider = NoopRewriteProvider()
+
+        async def _run() -> RewriteResult:
+            return await provider.rewrite(
+                query="什么是向量数据库？",
+                kb_ids=["kb-1", "kb-2"],
+            )
+
+        result = asyncio.run(_run())
+
+        assert isinstance(result, RewriteResult)
+        assert result.original_query == "什么是向量数据库？"
+        assert result.rewritten_query == "什么是向量数据库？"
+        assert result.original_query == result.rewritten_query
+        assert result.needs_rewrite is False, "直通实现应设置 needs_rewrite=False"
+        assert result.reason == "禁用改写，直通"
+
+    def test_rewrite_custom_query_identity(self) -> None:
+        """不同 query 的直通身份保持。"""
+        from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
+
+        provider = NoopRewriteProvider()
+
+        async def _run() -> RewriteResult:
+            return await provider.rewrite(
+                query="RAG 系统的核心组件有哪些？",
+                kb_ids=[],
+            )
+
+        result = asyncio.run(_run())
+        assert result.original_query == "RAG 系统的核心组件有哪些？"
+        assert result.rewritten_query == "RAG 系统的核心组件有哪些？"
+        assert result.needs_rewrite is False
+
+    def test_clear_cache_is_noop(self) -> None:
+        """clear_cache() 应为空实现，不抛异常。"""
+        from ragnexus.adapters.rewrite.noop import NoopRewriteProvider
+
+        provider = NoopRewriteProvider()
+
+        async def _run() -> None:
+            await provider.clear_cache("kb-1")
+            await provider.clear_cache("nonexistent-kb")
+
+        asyncio.run(_run())  # 通过即表示空实现正确
diff --git a/tests/unit/test_rewrite_port.py b/tests/unit/test_rewrite_port.py
new file mode 100644
index 0000000..6ac558c
--- /dev/null
+++ b/tests/unit/test_rewrite_port.py
@@ -0,0 +1,140 @@
+"""RewritePort Protocol 单元测试。
+
+验证 RewritePort 接口定义正确，以及结构性子类型兼容性。
+"""
+
+from __future__ import annotations
+
+import asyncio
+from dataclasses import is_dataclass
+from typing import Protocol
+
+from ragnexus.domain.ports import RewritePort, RewriteResult
+
+
+class TestRewriteResult:
+    """RewriteResult dataclass 测试。"""
+
+    def test_rewrite_result_is_dataclass(self) -> None:
+        """RewriteResult 应为 dataclass。"""
+        assert is_dataclass(RewriteResult)
+
+    def test_rewrite_result_fields(self) -> None:
+        """RewriteResult 应有 original_query, rewritten_query, needs_rewrite, reason 四个字段。"""
+        result = RewriteResult(
+            original_query="什么是 RAG",
+            rewritten_query="检索增强生成（RAG）是什么",
+            needs_rewrite=True,
+            reason="口语化查询，需要改写为更正式的检索语句",
+        )
+
+        assert result.original_query == "什么是 RAG"
+        assert result.rewritten_query == "检索增强生成（RAG）是什么"
+        assert result.needs_rewrite is True
+        assert result.reason == "口语化查询，需要改写为更正式的检索语句"
+
+    def test_rewrite_result_default_behavior(self) -> None:
+        """不需要改写时 rewritten_query 等于 original_query。"""
+        result = RewriteResult(
+            original_query="检索增强生成",
+            rewritten_query="检索增强生成",
+            needs_rewrite=False,
+            reason="查询已足够清晰",
+        )
+
+        assert result.original_query == result.rewritten_query
+        assert result.needs_rewrite is False
+
+
+class TestRewritePortProtocol:
+    """RewritePort Protocol 签名与结构性子类型测试。"""
+
+    def test_rewrite_port_is_protocol(self) -> None:
+        """RewritePort 应是 typing.Protocol 的子类。"""
+        assert issubclass(RewritePort, Protocol)
+
+    def test_rewrite_method_signature(self) -> None:
+        """rewrite 方法签名：keyword-only 参数，返回 RewriteResult。"""
+        import inspect
+
+        sig = inspect.signature(RewritePort.rewrite)
+
+        params = list(sig.parameters.values())
+        param_names = [p.name for p in params]
+
+        # self + 2 keyword-only 参数
+        assert param_names == [
+            "self",
+            "query",
+            "kb_ids",
+        ], f"参数名不匹配: {param_names}"
+
+        for p in params[1:]:  # 跳过 self
+            assert (
+                p.kind == inspect.Parameter.KEYWORD_ONLY
+            ), f"{p.name} 应为 KEYWORD_ONLY，实际: {p.kind}"
+
+        # 验证返回类型注解为 RewriteResult
+        assert (
+            sig.return_annotation == RewriteResult
+        ), f"返回类型应为 RewriteResult，实际: {sig.return_annotation}"
+
+    def test_clear_cache_method_signature(self) -> None:
+        """clear_cache 方法签名：kb_id: str → None。"""
+        import inspect
+
+        sig = inspect.signature(RewritePort.clear_cache)
+
+        params = list(sig.parameters.values())
+        assert len(params) == 2  # self + kb_id
+        assert params[0].name == "self"
+        assert params[1].name == "kb_id"
+        assert params[1].annotation is str
+        assert sig.return_annotation is None
+
+    def test_minimal_implementation_satisfies_protocol(self) -> None:
+        """一个最小实现类应满足 RewritePort 协议结构。
+
+        Python Protocol 使用静态结构子类型（pyright/mypy），运行时不需要
+        @runtime_checkable。这里通过实际调用来验证行为正确性。
+        """
+
+        class _MinimalRewriter:
+            """最小实现 — 原样返回查询，不做改写。"""
+
+            async def rewrite(
+                self,
+                *,
+                query: str,
+                kb_ids: list[str],
+            ) -> RewriteResult:
+                return RewriteResult(
+                    original_query=query,
+                    rewritten_query=query,
+                    needs_rewrite=False,
+                    reason="no rewrite needed",
+                )
+
+            async def clear_cache(self, kb_id: str) -> None:
+                pass
+
+        instance = _MinimalRewriter()
+
+        async def _run_rewrite() -> RewriteResult:
+            return await instance.rewrite(
+                query="什么是 RAG",
+                kb_ids=["kb1", "kb2"],
+            )
+
+        result = asyncio.run(_run_rewrite())
+
+        assert result.original_query == "什么是 RAG"
+        assert result.rewritten_query == "什么是 RAG"
+        assert result.needs_rewrite is False
+        assert result.reason == "no rewrite needed"
+
+        # 验证 clear_cache 也可正常调用
+        async def _run_clear() -> None:
+            await instance.clear_cache(kb_id="kb1")
+
+        asyncio.run(_run_clear())  # 不应抛异常
