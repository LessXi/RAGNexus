91c3e7b feat(rerank): 实现 LLMRerankProvider
66ac24d feat(rerank): 创建 NoopRerankProvider 直通实现
54e284a feat(domain): 新增 RerankPort Protocol

 src/ragnexus/adapters/rerank/__init__.py |   6 +
 src/ragnexus/adapters/rerank/llm.py      | 553 ++++++++++++++++++
 src/ragnexus/adapters/rerank/noop.py     |  30 +
 src/ragnexus/domain/ports.py             |  25 +
 tests/unit/domain/test_rerank_port.py    | 123 ++++
 tests/unit/test_llm_rerank.py            | 940 +++++++++++++++++++++++++++++++
 tests/unit/test_noop_rerank.py           | 201 +++++++
 7 files changed, 1878 insertions(+)

diff --git a/src/ragnexus/adapters/rerank/__init__.py b/src/ragnexus/adapters/rerank/__init__.py
new file mode 100644
index 0000000..0413cc4
--- /dev/null
+++ b/src/ragnexus/adapters/rerank/__init__.py
@@ -0,0 +1,6 @@
+"""重排适配器包。"""
+
+from ragnexus.adapters.rerank.llm import LLMRerankProvider
+from ragnexus.adapters.rerank.noop import NoopRerankProvider
+
+__all__ = ["LLMRerankProvider", "NoopRerankProvider"]
diff --git a/src/ragnexus/adapters/rerank/llm.py b/src/ragnexus/adapters/rerank/llm.py
new file mode 100644
index 0000000..d816b80
--- /dev/null
+++ b/src/ragnexus/adapters/rerank/llm.py
@@ -0,0 +1,553 @@
+"""LLM 重排适配器 — LLMRerankProvider。
+
+基于 LLMProvider 对向量召回候选进行相关性重排序，支持：
+- 向量相似度缓存（cosine ≥ 阈值）
+- 候选截断和文本截断
+- JSON 4 层防御解析
+- 降级返回原始排序（永不抛异常）
+- BIZ_EVENT 结构化日志
+"""
+
+from __future__ import annotations
+
+import asyncio
+import json
+import logging
+import math
+import re
+import time
+from dataclasses import dataclass
+from typing import Any
+
+from ragnexus.adapters.llm.base import LLMProvider
+from ragnexus.domain.models import SearchHit
+
+logger = logging.getLogger("ragnexus")
+
+
+# ============================================================================
+# CacheEntry
+# ============================================================================
+
+
+@dataclass
+class CacheEntry:
+    """重排缓存条目。
+
+    存储一次 LLM 重排的全量结果，包括：
+    - query_embedding: 用于余弦相似度匹配
+    - query_text: 原始 query，用于日志
+    - rankings: {chunk_id: rerank_score} 全量打分映射
+    - timestamp: 写入时间，用于 TTL 过期
+    """
+
+    query_embedding: list[float]
+    query_text: str
+    rankings: dict[str, float]
+    timestamp: float
+
+
+# ============================================================================
+# System Prompt
+# ============================================================================
+
+SYSTEM_PROMPT = (
+    "你是 RAG 检索重排器。你的任务是根据用户问题，对候选知识片段进行相关性打分和排序。\n\n"
+    "要求：\n"
+    "1. 只判断候选片段是否有助于回答用户问题。\n"
+    "2. 不要回答用户问题。\n"
+    "3. 不要编造候选片段中不存在的信息。\n"
+    "4. 每个候选片段给出 0 到 1 之间的 rerank_score。\n"
+    "5. 分数越高表示越相关、越适合作为 RAG 上下文。\n"
+    "6. 只返回 JSON，不要返回 Markdown，不要返回解释性文字。\n"
+    "7. reference_scores 中的候选已有最终相关性分数。请在相同评分体系下为 candidates 打分，"
+    "保持分数的一致性和可比性。不要更改或质疑 reference_scores 中的分数。"
+)
+
+
+# ============================================================================
+# 内部辅助函数
+# ============================================================================
+
+
+def _cosine_similarity(a: list[float], b: list[float]) -> float:
+    """计算两个向量的余弦相似度。"""
+    if len(a) != len(b):
+        return 0.0
+    dot = sum(x * y for x, y in zip(a, b, strict=False))
+    na = math.sqrt(sum(x * x for x in a))
+    nb = math.sqrt(sum(y * y for y in b))
+    if na == 0.0 or nb == 0.0:
+        return 0.0
+    return dot / (na * nb)
+
+
+def _build_content_preview(text: str, heading: str | None, max_chars: int) -> str:
+    """构造 content_preview：前置 heading，截取前几个完整句子 ≤ max_chars。
+
+    用于缓存部分命中时的 reference_scores 标尺。
+    """
+    prefix = f"{heading}: " if heading else ""
+    available = max_chars - len(prefix)
+    if available <= 0:
+        return prefix[:max_chars]
+
+    # 截取前几个完整句子
+    if len(text) <= available:
+        return prefix + text
+
+    # 找最后一个句号/问号/感叹号/换行在 available 内的位置
+    truncated = text[:available]
+    for sep in ("。", "！", "？", "\n", ". ", "! ", "? "):
+        idx = truncated.rfind(sep)
+        if idx > 0:
+            return prefix + truncated[: idx + len(sep.rstrip())]
+    # 没找到句子边界 → 硬截断
+    return prefix + truncated
+
+
+def _parse_rankings_json(raw: Any) -> list[dict[str, Any]]:
+    """JSON 4 层防御解析。
+
+    0. API 层 response_format: json_object（LLMProvider 处理）
+    1. 已经是 dict/list → 直接提取
+    2. json.loads — 纯 JSON 字符串
+    3. 正则提取 ```json ... ``` — Markdown 代码块
+    4. 正则提取最外层 {...} — 文本夹杂 JSON
+    5. 全失败返回空列表
+
+    返回 rankings 列表，每个元素为 {"chunk_id": str, "rerank_score": float, ...}
+    """
+    # Layer 1: 已经是 dict/list
+    if isinstance(raw, dict):
+        rankings = raw.get("rankings", [])
+        if isinstance(rankings, list) and rankings:
+            return rankings
+        # 可能是直接返回的 raw 字符串（dict 的 value）
+        return []
+
+    if isinstance(raw, list):
+        return raw
+
+    # 确保是字符串
+    if not isinstance(raw, str):
+        return []
+
+    content = raw.strip()
+    if not content:
+        return []
+
+    # Layer 2: 直接 json.loads
+    try:
+        parsed = json.loads(content)
+        if isinstance(parsed, dict):
+            rankings = parsed.get("rankings", [])
+            if isinstance(rankings, list):
+                return rankings
+        elif isinstance(parsed, list):
+            return parsed
+    except json.JSONDecodeError:
+        pass
+
+    # Layer 3: 提取 ```json ... ``` 代码块
+    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
+    if m:
+        try:
+            parsed = json.loads(m.group(1).strip())
+            if isinstance(parsed, dict):
+                rankings = parsed.get("rankings", [])
+                if isinstance(rankings, list):
+                    return rankings
+            elif isinstance(parsed, list):
+                return parsed
+        except json.JSONDecodeError:
+            pass
+
+    # Layer 4: 提取最外层 {...}
+    m = re.search(r"\{.*\}", content, re.DOTALL)
+    if m:
+        try:
+            parsed = json.loads(m.group(0))
+            if isinstance(parsed, dict):
+                rankings = parsed.get("rankings", [])
+                if isinstance(rankings, list):
+                    return rankings
+            elif isinstance(parsed, list):
+                return parsed
+        except json.JSONDecodeError:
+            pass
+
+    return []
+
+
+def _clamp_score(score: float) -> float:
+    """将分数 clamp 到 [0, 1] 区间。"""
+    if score < 0.0:
+        return 0.0
+    if score > 1.0:
+        return 1.0
+    return score
+
+
+# ============================================================================
+# LLMRerankProvider
+# ============================================================================
+
+
+class LLMRerankProvider:
+    """LLM 驱动的重排提供者。
+
+    对向量召回候选 chunk 进行 LLM 相关性打分重排序。
+    降级安全：任意步骤失败时返回原始向量排序，永不抛异常。
+    """
+
+    def __init__(
+        self,
+        llm: LLMProvider,
+        max_candidates: int = 20,
+        chunk_max_chars: int = 1000,
+        cache_similarity_threshold: float = 0.95,
+        cache_max_entries: int = 100,
+        cache_ttl_seconds: int = 300,
+        cache_preview_max_chars: int = 150,
+        temperature: float = 0.0,
+    ):
+        """初始化 LLM 重排提供者。
+
+        参数:
+            llm: LLMProvider 实例，用于调用大模型
+            max_candidates: 最多送 LLM 的候选数（超出部分截断）
+            chunk_max_chars: 每个 chunk 文本的最大字符数
+            cache_similarity_threshold: 缓存命中的余弦相似度阈值
+            cache_max_entries: 每个 KB 最多缓存的条目数
+            cache_ttl_seconds: 缓存 TTL（秒）
+            cache_preview_max_chars: content_preview 的最大字符数
+            temperature: LLM 采样温度
+        """
+        self.llm = llm
+        self.max_candidates = max_candidates
+        self.chunk_max_chars = chunk_max_chars
+        self.cache_similarity_threshold = cache_similarity_threshold
+        self.cache_max_entries = cache_max_entries
+        self.cache_ttl_seconds = cache_ttl_seconds
+        self.cache_preview_max_chars = cache_preview_max_chars
+        self.temperature = temperature
+        self._cache: dict[str, list[CacheEntry]] = {}
+        self._lock = asyncio.Lock()
+
+    # ========================================================================
+    # rerank — 主入口
+    # ========================================================================
+
+    async def rerank(
+        self,
+        *,
+        query: str,
+        query_vector: list[float],
+        kb_ids: list[str],
+        chunks: list[SearchHit],
+        top_n: int,
+    ) -> list[SearchHit]:
+        """对向量召回候选重排序。
+
+        参数:
+            query: 用户原始问题
+            query_vector: 查询向量（用于缓存余弦相似度匹配）
+            kb_ids: 检索目标 KB 列表（用于缓存分区）
+            chunks: 向量召回的 SearchHit 列表（按 score 降序）
+            top_n: 最终返回数
+
+        返回:
+            排好序的 SearchHit 列表，score 字段保持向量原始分
+        """
+        start_time = time.time()
+        try:
+            return await self._rerank_impl(
+                query=query,
+                query_vector=query_vector,
+                kb_ids=kb_ids,
+                chunks=chunks,
+                top_n=top_n,
+                start_time=start_time,
+            )
+        except Exception as exc:
+            elapsed_ms = round((time.time() - start_time) * 1000, 2)
+            logger.warning(
+                "rerank LLM 调用失败，降级为向量排序",
+                extra={
+                    "event_type": "BIZ_EVENT",
+                    "event": "rerank_degraded",
+                    "kb_ids": kb_ids,
+                    "query": query[:200],
+                    "candidate_count": len(chunks),
+                    "error_type": type(exc).__name__,
+                    "error_message": str(exc)[:500],
+                    "rerank_latency_ms": elapsed_ms,
+                },
+            )
+            return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_n]
+
+    async def _rerank_impl(
+        self,
+        *,
+        query: str,
+        query_vector: list[float],
+        kb_ids: list[str],
+        chunks: list[SearchHit],
+        top_n: int,
+        start_time: float,
+    ) -> list[SearchHit]:
+        """rerank 内部实现（不含降级 try/except）。"""
+        if not chunks:
+            return []
+
+        now = time.time()
+
+        # --- 步骤 a: 查缓存 ---
+        matched_rankings: dict[str, float] = {}
+        unmatched_chunks = list(chunks)
+        cache_hit_entry: CacheEntry | None = None
+        cache_max_sim = 0.0
+
+        async with self._lock:
+            for kb_id in kb_ids:
+                entries = self._cache.get(kb_id, [])
+                for entry in entries:
+                    # TTL 过期检查
+                    if now - entry.timestamp > self.cache_ttl_seconds:
+                        continue
+                    sim = _cosine_similarity(query_vector, entry.query_embedding)
+                    if sim >= self.cache_similarity_threshold and sim > cache_max_sim:
+                        cache_max_sim = sim
+                        cache_hit_entry = entry
+
+        if cache_hit_entry is not None:
+            cached_rankings = cache_hit_entry.rankings
+            matched_ids = set()
+            for chunk in chunks:
+                if chunk.chunk_id in cached_rankings:
+                    matched_rankings[chunk.chunk_id] = cached_rankings[chunk.chunk_id]
+                    matched_ids.add(chunk.chunk_id)
+
+            unmatched_chunks = [c for c in chunks if c.chunk_id not in matched_ids]
+
+            if not unmatched_chunks:
+                # 全命中：直接按缓存分排序返回
+                sorted_chunks = sorted(
+                    chunks,
+                    key=lambda c: matched_rankings.get(c.chunk_id, 0.0),
+                    reverse=True,
+                )
+                elapsed_ms = round((time.time() - start_time) * 1000, 2)
+                logger.info(
+                    "",
+                    extra={
+                        "event_type": "BIZ_EVENT",
+                        "event": "rerank_cache_hit",
+                        "kb_ids": kb_ids,
+                        "query": query[:200],
+                        "similarity": round(cache_max_sim, 4),
+                        "cached_query": cache_hit_entry.query_text[:200],
+                        "matched_count": len(matched_rankings),
+                        "unmatched_count": 0,
+                        "rerank_latency_ms": elapsed_ms,
+                    },
+                )
+                return sorted_chunks[:top_n]
+
+            # 部分命中时记录日志
+            logger.info(
+                "",
+                extra={
+                    "event_type": "BIZ_EVENT",
+                    "event": "rerank_cache_hit",
+                    "kb_ids": kb_ids,
+                    "query": query[:200],
+                    "similarity": round(cache_max_sim, 4),
+                    "cached_query": cache_hit_entry.query_text[:200],
+                    "matched_count": len(matched_rankings),
+                    "unmatched_count": len(unmatched_chunks),
+                },
+            )
+
+        # --- 步骤 b: 候选截断 ---
+        unmatched_candidates = unmatched_chunks[: self.max_candidates]
+
+        # --- 步骤 c: 文本截断 ---
+        truncated_candidates: list[dict[str, Any]] = []
+        for chunk in unmatched_candidates:
+            heading = chunk.metadata.get("heading") if chunk.metadata else None
+            truncated_candidates.append(
+                {
+                    "chunk_id": chunk.chunk_id,
+                    "document_id": chunk.doc_id,
+                    "title": heading if heading else "",
+                    "content": chunk.text[: self.chunk_max_chars],
+                    "vector_score": chunk.score,
+                }
+            )
+
+        # --- 步骤 d: 构造 JSON payload ---
+        payload: dict[str, Any] = {
+            "query": query,
+            "candidates": truncated_candidates,
+            "top_n": top_n,
+        }
+
+        # 部分命中：添加 reference_scores 标尺
+        if matched_rankings and cache_hit_entry is not None:
+            ref_scores: list[dict[str, Any]] = []
+            for cid, rscore in matched_rankings.items():
+                # 找到原始 chunk 信息
+                orig_chunk = next((c for c in chunks if c.chunk_id == cid), None)
+                heading = (
+                    orig_chunk.metadata.get("heading")
+                    if orig_chunk and orig_chunk.metadata
+                    else None
+                )
+                text = orig_chunk.text if orig_chunk else ""
+                preview = _build_content_preview(text, heading, self.cache_preview_max_chars)
+                ref_scores.append(
+                    {
+                        "chunk_id": cid,
+                        "rerank_score": rscore,
+                        "content_preview": preview,
+                    }
+                )
+            payload["reference_scores"] = ref_scores
+
+        # --- 步骤 e: LLM 调用 ---
+        try:
+            llm_response = await self.llm.chat_json(
+                system_prompt=SYSTEM_PROMPT,
+                user_payload=payload,
+                temperature=self.temperature,
+            )
+        except Exception:
+            # LLM 调用失败，但仍在 _rerank_impl 中
+            # 如果有缓存匹配部分，用缓存分 + 原始排序
+            if matched_rankings:
+                return self._merge_and_sort(chunks, matched_rankings, {}, top_n)
+            raise  # 让外层 catch 降级
+
+        # --- 步骤 f: 解析 rankings ---
+        rankings_list = _parse_rankings_json(llm_response)
+        if not rankings_list and not matched_rankings:
+            # 解析全失败且无缓存匹配 → 触发降级
+            return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_n]
+
+        # 构建 LLM 打分映射
+        llm_rankings: dict[str, float] = {}
+        for item in rankings_list:
+            cid = item.get("chunk_id")
+            if not cid:
+                continue
+            score = _clamp_score(float(item.get("rerank_score", 0.0)))
+            llm_rankings[str(cid)] = score
+
+        # --- 合并缓存分 + LLM 分 → 排序 → 裁回 top_n ---
+        result = self._merge_and_sort(chunks, matched_rankings, llm_rankings, top_n)
+
+        # --- 步骤 g: 写入缓存 ---
+        # 合并全量映射（matched + llm），缺失的默认 0
+        full_rankings: dict[str, float] = dict(matched_rankings)
+        for chunk in chunks:
+            if chunk.chunk_id not in full_rankings:
+                full_rankings[chunk.chunk_id] = llm_rankings.get(chunk.chunk_id, 0.0)
+
+        cache_entry = CacheEntry(
+            query_embedding=list(query_vector),
+            query_text=query,
+            rankings=full_rankings,
+            timestamp=time.time(),
+        )
+
+        async with self._lock:
+            for kb_id in kb_ids:
+                if kb_id not in self._cache:
+                    self._cache[kb_id] = []
+                entries = self._cache[kb_id]
+                entries.append(cache_entry)
+                # 超限踢最旧
+                while len(entries) > self.cache_max_entries:
+                    entries.pop(0)
+
+        # --- 日志 ---
+        elapsed_ms = round((time.time() - start_time) * 1000, 2)
+        logger.info(
+            "",
+            extra={
+                "event_type": "BIZ_EVENT",
+                "event": "rerank_completed",
+                "kb_ids": kb_ids,
+                "query": query[:200],
+                "candidate_count": len(chunks),
+                "kept_count": len(result),
+                "rerank_latency_ms": elapsed_ms,
+            },
+        )
+
+        # DEBUG 级别打分详情
+        logger.debug(
+            "rerank 打分详情",
+            extra={
+                "event_type": "RERANK_DEBUG",
+                "kb_ids": kb_ids,
+                "query": query[:200],
+                "rankings": [
+                    {
+                        "chunk_id": item.get("chunk_id", ""),
+                        "rerank_score": item.get("rerank_score", 0.0),
+                        "reason": item.get("reason", ""),
+                    }
+                    for item in rankings_list
+                ],
+            },
+        )
+
+        return result
+
+    # ========================================================================
+    # 内部辅助方法
+    # ========================================================================
+
+    def _merge_and_sort(
+        self,
+        chunks: list[SearchHit],
+        matched_rankings: dict[str, float],
+        llm_rankings: dict[str, float],
+        top_n: int,
+    ) -> list[SearchHit]:
+        """合并缓存分和 LLM 分，按 rerank_score 降序排序，裁回 top_n。
+
+        缓存分优先（已经过 LLM 验证），LLM 分补充未命中 chunk。
+        score 字段保持向量原始分不变。
+        """
+        # 为每个 chunk 确定 rerank_score
+        chunk_scores: dict[str, float] = {}
+        for chunk in chunks:
+            cid = chunk.chunk_id
+            if cid in matched_rankings:
+                chunk_scores[cid] = matched_rankings[cid]
+            elif cid in llm_rankings:
+                chunk_scores[cid] = llm_rankings[cid]
+            else:
+                chunk_scores[cid] = 0.0
+
+        sorted_chunks = sorted(
+            chunks, key=lambda c: chunk_scores.get(c.chunk_id, 0.0), reverse=True
+        )
+        return sorted_chunks[:top_n]
+
+    # ========================================================================
+    # clear_cache
+    # ========================================================================
+
+    async def clear_cache(self, kb_id: str) -> None:
+        """清空指定 KB 的缓存。
+
+        参数:
+            kb_id: 知识库 ID，文档上传后由 composition.py 调用
+        """
+        async with self._lock:
+            self._cache.pop(kb_id, None)
diff --git a/src/ragnexus/adapters/rerank/noop.py b/src/ragnexus/adapters/rerank/noop.py
new file mode 100644
index 0000000..ef59131
--- /dev/null
+++ b/src/ragnexus/adapters/rerank/noop.py
@@ -0,0 +1,30 @@
+"""空重排适配器 — NoopRerankProvider。
+
+禁用重排时的直通实现：rerank 返回原始 chunks，clear_cache 空实现。
+"""
+
+from ragnexus.domain.models import SearchHit
+
+
+class NoopRerankProvider:
+    """空重排提供者 — 禁用重排时的直通实现。
+
+    rerank 直接返回原始 chunks（不排序、不截断），
+    clear_cache 空实现（无缓存可清）。
+    """
+
+    async def rerank(
+        self,
+        *,
+        query: str,
+        query_vector: list[float],
+        kb_ids: list[str],
+        chunks: list[SearchHit],
+        top_n: int,
+    ) -> list[SearchHit]:
+        """直通返回原始 chunks，不做任何重排。"""
+        return chunks
+
+    async def clear_cache(self, kb_id: str) -> None:
+        """空实现 — 无缓存可清。"""
+        pass
diff --git a/src/ragnexus/domain/ports.py b/src/ragnexus/domain/ports.py
index d3bd8e1..8a9152d 100644
--- a/src/ragnexus/domain/ports.py
+++ b/src/ragnexus/domain/ports.py
@@ -47,10 +47,35 @@ class RetrieveLogPort(Protocol):
 
     async def log(
         self,
         *,
         query: str,
         kb_ids: list[str],
         top_k: int,
         hit_count: int,
         latency_ms: int,
     ) -> None: ...
+
+
+class RerankPort(Protocol):
+    """重排端口 — 对向量召回候选 chunk 重排序。
+
+    骨架实现: LLMRerankProvider (启用时), NoopRerankProvider (禁用时)。
+    返回类型为 list[SearchHit] — 排好序，score 保持向量原始分不变。
+    """
+
+    async def rerank(
+        self,
+        *,
+        query: str,
+        query_vector: list[float],
+        kb_ids: list[str],
+        chunks: list[SearchHit],
+        top_n: int,
+    ) -> list[SearchHit]: ...
+
+    async def clear_cache(self, kb_id: str) -> None:
+        """清空指定 KB 的缓存。文档上传后由 composition.py 调用。
+
+        NoopRerankProvider 实现为空。
+        """
+        ...
diff --git a/tests/unit/domain/test_rerank_port.py b/tests/unit/domain/test_rerank_port.py
new file mode 100644
index 0000000..ca525b6
--- /dev/null
+++ b/tests/unit/domain/test_rerank_port.py
@@ -0,0 +1,123 @@
+"""RerankPort Protocol 单元测试。
+
+验证 RerankPort 接口定义正确，以及结构性子类型兼容性。
+"""
+
+from __future__ import annotations
+
+import asyncio
+from typing import Protocol
+
+from ragnexus.domain.models import SearchHit
+from ragnexus.domain.ports import RerankPort
+
+
+class TestRerankPortProtocol:
+    """RerankPort Protocol 签名与结构性子类型测试。"""
+
+    def test_rerank_port_is_protocol(self) -> None:
+        """RerankPort 应是 typing.Protocol 的子类。"""
+        assert issubclass(RerankPort, Protocol)
+
+    def test_rerank_method_signature(self) -> None:
+        """rerank 方法签名：keyword-only 参数，返回 list[SearchHit]。"""
+        import inspect
+
+        sig = inspect.signature(RerankPort.rerank)
+
+        # 所有参数应为 keyword-only（第一个是 self，后面都是 keyword-only）
+        params = list(sig.parameters.values())
+        param_names = [p.name for p in params]
+
+        # self + 5 keyword-only 参数
+        assert param_names == [
+            "self",
+            "query",
+            "query_vector",
+            "kb_ids",
+            "chunks",
+            "top_n",
+        ], f"参数名不匹配: {param_names}"
+
+        for p in params[1:]:  # 跳过 self
+            assert (
+                p.kind == inspect.Parameter.KEYWORD_ONLY
+            ), f"{p.name} 应为 KEYWORD_ONLY，实际: {p.kind}"
+
+        # 验证返回类型注解为 list[SearchHit]
+        assert (
+            sig.return_annotation == list[SearchHit]
+        ), f"返回类型应为 list[SearchHit]，实际: {sig.return_annotation}"
+
+    def test_clear_cache_method_signature(self) -> None:
+        """clear_cache 方法签名：kb_id: str → None。"""
+        import inspect
+
+        sig = inspect.signature(RerankPort.clear_cache)
+
+        params = list(sig.parameters.values())
+        assert len(params) == 2  # self + kb_id
+        assert params[0].name == "self"
+        assert params[1].name == "kb_id"
+        assert params[1].annotation is str
+        assert sig.return_annotation is None
+
+    def test_minimal_implementation_satisfies_protocol(self) -> None:
+        """一个最小实现类应满足 RerankPort 协议结构。
+
+        Python Protocol 使用静态结构子类型（pyright/mypy），运行时不需要
+        @runtime_checkable。这里通过实际调用来验证行为正确性。
+        """
+
+        class _MinimalReranker:
+            """最小实现 — 仅按原始顺序返回，不做重排。"""
+
+            async def rerank(
+                self,
+                *,
+                query: str,
+                query_vector: list[float],
+                kb_ids: list[str],
+                chunks: list[SearchHit],
+                top_n: int,
+            ) -> list[SearchHit]:
+                return chunks[:top_n]
+
+            async def clear_cache(self, kb_id: str) -> None:
+                pass
+
+        instance = _MinimalReranker()
+
+        # 验证实际行为 — 确保返回类型和截断逻辑正确
+        fake_hits = [
+            SearchHit(
+                chunk_id="c1",
+                kb_id="kb1",
+                doc_id="d1",
+                score=0.9,
+                text="hello",
+                metadata={},
+            ),
+            SearchHit(
+                chunk_id="c2",
+                kb_id="kb1",
+                doc_id="d1",
+                score=0.8,
+                text="world",
+                metadata={},
+            ),
+        ]
+
+        async def _run() -> list[SearchHit]:
+            return await instance.rerank(
+                query="test",
+                query_vector=[0.1, 0.2],
+                kb_ids=["kb1"],
+                chunks=fake_hits,
+                top_n=1,
+            )
+
+        result = asyncio.run(_run())
+
+        assert len(result) == 1
+        assert result[0].score == 0.9  # score 保持原始分不变
diff --git a/tests/unit/test_llm_rerank.py b/tests/unit/test_llm_rerank.py
new file mode 100644
index 0000000..c9f55d4
--- /dev/null
+++ b/tests/unit/test_llm_rerank.py
@@ -0,0 +1,940 @@
+"""LLMRerankProvider 单元测试。
+
+TDD: RED → GREEN。覆盖缓存、LLM 调用、JSON 防御、降级、日志等完整流程。
+"""
+
+from __future__ import annotations
+
+import asyncio
+import math
+from typing import Any
+
+from ragnexus.domain.models import SearchHit
+
+# ============================================================================
+# FakeLLMProvider — 用于测试的可控 LLM 实现
+# ============================================================================
+
+
+class FakeLLMProvider:
+    """测试用 LLMProvider，允许预设 chat_json 返回值。
+
+    不继承 ABC，因为测试不需要严格类型检查。
+    通过 responses 队列控制 LLM 返回，队列空了返回默认空 dict。
+    """
+
+    def __init__(self, responses: list[dict] | None = None):
+        self.responses: list[dict] = list(responses or [])
+        self.calls: list[dict] = []  # 记录每次调用的参数
+
+    async def chat_json(
+        self,
+        *,
+        system_prompt: str,
+        user_payload: dict,
+        temperature: float = 0.0,
+        timeout_seconds: int | None = None,
+    ) -> dict:
+        self.calls.append(
+            {
+                "system_prompt": system_prompt,
+                "user_payload": user_payload,
+                "temperature": temperature,
+                "timeout_seconds": timeout_seconds,
+            }
+        )
+        if self.responses:
+            response = self.responses.pop(0)
+            if isinstance(response, Exception):
+                raise response
+            return response
+        return {}
+
+
+# ============================================================================
+# 辅助工具
+# ============================================================================
+
+
+def make_hit(
+    chunk_id: str,
+    kb_id: str = "kb_001",
+    doc_id: str = "doc_001",
+    score: float = 0.9,
+    text: str = "",
+    metadata: dict[str, Any] | None = None,
+) -> SearchHit:
+    """快捷构造 SearchHit 测试数据。"""
+    return SearchHit(
+        chunk_id=chunk_id,
+        kb_id=kb_id,
+        doc_id=doc_id,
+        score=score,
+        text=text,
+        metadata=metadata or {},
+    )
+
+
+def cosine_sim(a: list[float], b: list[float]) -> float:
+    """计算两个向量的 cosine 相似度（纯测试辅助）。"""
+    dot = sum(x * y for x, y in zip(a, b, strict=True))
+    na = math.sqrt(sum(x * x for x in a))
+    nb = math.sqrt(sum(x * x for x in b))
+    if na == 0 or nb == 0:
+        return 0.0
+    return dot / (na * nb)
+
+
+# ============================================================================
+# 测试类
+# ============================================================================
+
+
+class TestLLMRerankProviderConstruction:
+    """构造器参数存储测试。"""
+
+    def test_default_construction(self):
+        """默认构造器参数应正确存储。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider()
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        assert provider.llm is fake
+        assert provider.max_candidates == 20
+        assert provider.chunk_max_chars == 1000
+        assert provider.cache_similarity_threshold == 0.95
+        assert provider.cache_max_entries == 100
+        assert provider.cache_ttl_seconds == 300
+        assert provider.cache_preview_max_chars == 150
+        assert provider.temperature == 0.0
+        assert isinstance(provider._cache, dict)
+
+    def test_custom_construction(self):
+        """自定义构造器参数应正确存储。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider()
+        provider = LLMRerankProvider(
+            llm=fake,  # type: ignore[arg-type]
+            max_candidates=10,
+            chunk_max_chars=500,
+            cache_similarity_threshold=0.90,
+            cache_max_entries=50,
+            cache_ttl_seconds=600,
+            cache_preview_max_chars=100,
+            temperature=0.3,
+        )
+        assert provider.max_candidates == 10
+        assert provider.chunk_max_chars == 500
+        assert provider.cache_similarity_threshold == 0.90
+        assert provider.cache_max_entries == 50
+        assert provider.cache_ttl_seconds == 600
+        assert provider.cache_preview_max_chars == 100
+        assert provider.temperature == 0.3
+
+
+class TestLLMRerankProviderRerank:
+    """rerank 正常流程测试。"""
+
+    def test_rerank_calls_llm_and_returns_reordered(self):
+        """rerank 应调用 LLM、解析 rankings、按 rerank_score 排序返回。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(
+            responses=[
+                {
+                    "rankings": [
+                        {"chunk_id": "c_2", "rerank_score": 0.95, "reason": "best"},
+                        {"chunk_id": "c_1", "rerank_score": 0.30, "reason": "ok"},
+                        {"chunk_id": "c_3", "rerank_score": 0.80, "reason": "good"},
+                    ]
+                }
+            ]
+        )
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        chunks = [
+            make_hit("c_1", score=0.91, text="text 1"),
+            make_hit("c_2", score=0.85, text="text 2"),
+            make_hit("c_3", score=0.70, text="text 3"),
+        ]
+
+        async def _run() -> list[SearchHit]:
+            return await provider.rerank(
+                query="测试问题",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=3,
+            )
+
+        result = asyncio.run(_run())
+
+        # 按 rerank_score 降序：c_2(0.95), c_3(0.80), c_1(0.30)
+        assert len(result) == 3
+        assert result[0].chunk_id == "c_2"
+        assert result[1].chunk_id == "c_3"
+        assert result[2].chunk_id == "c_1"
+
+        # LLM 应该被调用了 1 次
+        assert len(fake.calls) == 1
+
+    def test_rerank_preserves_original_score(self):
+        """重排只改变顺序，不改变 score 字段（保持向量原始分）。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(
+            responses=[
+                {
+                    "rankings": [
+                        {"chunk_id": "c_2", "rerank_score": 0.95},
+                        {"chunk_id": "c_1", "rerank_score": 0.30},
+                    ]
+                }
+            ]
+        )
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        chunks = [
+            make_hit("c_1", score=0.91),
+            make_hit("c_2", score=0.85),
+        ]
+
+        async def _run() -> list[SearchHit]:
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=2,
+            )
+
+        result = asyncio.run(_run())
+
+        # c_2 的 score 仍然是 0.85（不是 0.95）
+        c2 = next(r for r in result if r.chunk_id == "c_2")
+        assert c2.score == 0.85
+        c1 = next(r for r in result if r.chunk_id == "c_1")
+        assert c1.score == 0.91
+
+    def test_rerank_truncates_to_top_n(self):
+        """rerank 应裁回 top_n 条结果。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(
+            responses=[
+                {
+                    "rankings": [
+                        {"chunk_id": f"c_{i}", "rerank_score": 0.9 - i * 0.1} for i in range(10)
+                    ]
+                }
+            ]
+        )
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        chunks = [make_hit(f"c_{i}", score=0.9 - i * 0.05) for i in range(10)]
+
+        async def _run() -> list[SearchHit]:
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=3,
+            )
+
+        result = asyncio.run(_run())
+        assert len(result) == 3
+
+
+class TestLLMRerankProviderCache:
+    """缓存逻辑测试。"""
+
+    def test_cache_full_hit_skips_llm(self):
+        """全命中缓存时应跳过 LLM，直接按缓存分排序返回。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider()
+
+        # 先调用一次写入缓存
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+        fake.responses.append(
+            {
+                "rankings": [
+                    {"chunk_id": "c_1", "rerank_score": 0.80},
+                    {"chunk_id": "c_2", "rerank_score": 0.95},
+                ]
+            }
+        )
+
+        query_vector = [0.1] * 10
+        chunks = [
+            make_hit("c_1", score=0.91, text="text 1"),
+            make_hit("c_2", score=0.85, text="text 2"),
+        ]
+
+        async def _first_run():
+            return await provider.rerank(
+                query="测试问题",
+                query_vector=query_vector,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=2,
+            )
+
+        asyncio.run(_first_run())
+        assert len(fake.calls) == 1  # 第一次调用 LLM
+
+        # 第二次：相同 query_vector，应命中缓存
+        result2 = asyncio.run(_first_run())
+        assert len(fake.calls) == 1  # 未新增 LLM 调用
+        # 结果按缓存分排序
+        assert result2[0].chunk_id == "c_2"  # 0.95
+        assert result2[1].chunk_id == "c_1"  # 0.80
+
+    def test_cache_partial_hit_payload_includes_reference_scores(self):
+        """部分命中时 LLM payload 应包含 reference_scores 标尺。
+
+        场景: 第一次缓存 {c_1, c_2, c_3} 的 rankings，
+        第二次用相同 query_vector 但 chunks 含 {c_1, c_2, c_4}。
+        c_1, c_2 命中缓存 → reference_scores，c_4 送 LLM → candidates。
+        """
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider()
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        query_vector = [0.1] * 10
+
+        # 第一次：3 个 chunks 全送 LLM，写入缓存
+        chunks1 = [
+            make_hit("c_1", score=0.91, text="text 1"),
+            make_hit("c_2", score=0.85, text="text 2"),
+            make_hit("c_3", score=0.70, text="text 3"),
+        ]
+        fake.responses.append(
+            {
+                "rankings": [
+                    {"chunk_id": "c_1", "rerank_score": 0.80},
+                    {"chunk_id": "c_2", "rerank_score": 0.95},
+                    {"chunk_id": "c_3", "rerank_score": 0.60},
+                ]
+            }
+        )
+        asyncio.run(
+            provider.rerank(
+                query="测试问题",
+                query_vector=query_vector,
+                kb_ids=["kb_001"],
+                chunks=chunks1,
+                top_n=3,
+            )
+        )
+
+        # 第二次：相同 query_vector（cosine=1.0，缓存命中）
+        # chunks 含 c_4 不在缓存中 → 部分命中
+        chunks2 = [
+            make_hit("c_1", score=0.91, text="text 1"),
+            make_hit("c_2", score=0.85, text="text 2"),
+            make_hit("c_4", score=0.65, text="text 4"),  # 不在缓存中
+        ]
+        fake.responses.append({"rankings": [{"chunk_id": "c_4", "rerank_score": 0.75}]})
+
+        asyncio.run(
+            provider.rerank(
+                query="测试问题",
+                query_vector=query_vector,
+                kb_ids=["kb_001"],
+                chunks=chunks2,
+                top_n=3,
+            )
+        )
+
+        payload = fake.calls[1]["user_payload"]
+        assert "reference_scores" in payload, "部分命中场景 payload 应包含 reference_scores"
+        # candidates 应只包含未命中的 c_4
+        candidate_ids = {c["chunk_id"] for c in payload["candidates"]}
+        assert candidate_ids == {"c_4"}, f"candidates 应只含未命中 chunk，实际: {candidate_ids}"
+        # reference_scores 应包含 c_1, c_2
+        ref_ids = {r["chunk_id"] for r in payload["reference_scores"]}
+        assert ref_ids == {
+            "c_1",
+            "c_2",
+        }, f"reference_scores 应含命中 chunk，实际: {ref_ids}"
+
+    def test_cache_similarity_mismatch_goes_to_llm(self):
+        """缓存向量不相似时应走 LLM。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider()
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        query_vector_a = [0.1] * 10
+        chunks = [
+            make_hit("c_1", score=0.9, text="text 1"),
+        ]
+
+        # 第一次写入缓存
+        fake.responses.append(
+            {
+                "rankings": [{"chunk_id": "c_1", "rerank_score": 0.8}],
+            }
+        )
+        asyncio.run(
+            provider.rerank(
+                query="问题A",
+                query_vector=query_vector_a,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=1,
+            )
+        )
+
+        # 第二次：非常不同的 query_vector
+        fake.responses.append(
+            {
+                "rankings": [{"chunk_id": "c_1", "rerank_score": 0.7}],
+            }
+        )
+        asyncio.run(
+            provider.rerank(
+                query="问题B",
+                query_vector=[-0.1] * 10,  # 完全不同
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=1,
+            )
+        )
+
+        # 两次都调了 LLM
+        assert len(fake.calls) == 2
+
+    def test_cache_tll_expiry(self):
+        """TTL 过期缓存不应被命中。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider()
+        provider = LLMRerankProvider(llm=fake, cache_ttl_seconds=300)  # type: ignore[arg-type]
+
+        query_vector = [0.1] * 10
+        chunks = [make_hit("c_1", score=0.9, text="text 1")]
+
+        fake.responses.append(
+            {
+                "rankings": [{"chunk_id": "c_1", "rerank_score": 0.8}],
+            }
+        )
+        asyncio.run(
+            provider.rerank(
+                query="测试",
+                query_vector=query_vector,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=1,
+            )
+        )
+
+        # 将缓存条目的 timestamp 改为很久以前（模拟 TTL 过期）
+        import time
+
+        for entry in provider._cache.get("kb_001", []):
+            entry.timestamp = time.time() - 600  # 10 分钟前
+
+        # 第二次调用：缓存应已过期，走 LLM
+        fake.responses.append(
+            {
+                "rankings": [{"chunk_id": "c_1", "rerank_score": 0.7}],
+            }
+        )
+        asyncio.run(
+            provider.rerank(
+                query="测试",
+                query_vector=query_vector,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=1,
+            )
+        )
+
+        assert len(fake.calls) == 2
+
+
+class TestLLMRerankProviderCandidateTruncation:
+    """候选截断相关测试。"""
+
+    def test_truncates_to_max_candidates(self):
+        """超过 max_candidates 时应截断。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(
+            responses=[
+                {"rankings": [{"chunk_id": f"c_{i}", "rerank_score": 0.5} for i in range(3)]}
+            ]
+        )
+
+        provider = LLMRerankProvider(llm=fake, max_candidates=3)  # type: ignore[arg-type]
+
+        chunks = [make_hit(f"c_{i}", score=0.9 - i * 0.05) for i in range(10)]
+
+        async def _run():
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=3,
+            )
+
+        asyncio.run(_run())
+
+        # LLM payload 中 candidates 不应超过 3
+        payload = fake.calls[0]["user_payload"]
+        assert len(payload["candidates"]) == 3
+
+    def test_text_truncates_at_chunk_max_chars(self):
+        """chunk 文本应截断到 chunk_max_chars。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(responses=[{"rankings": [{"chunk_id": "c_1", "rerank_score": 0.8}]}])
+
+        provider = LLMRerankProvider(llm=fake, chunk_max_chars=50)  # type: ignore[arg-type]
+
+        long_text = "A" * 200
+        chunks = [make_hit("c_1", score=0.9, text=long_text)]
+
+        async def _run():
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=1,
+            )
+
+        asyncio.run(_run())
+
+        payload = fake.calls[0]["user_payload"]
+        assert len(payload["candidates"][0]["content"]) <= 50
+
+
+class TestLLMRerankProviderJsonDefense:
+    """JSON 解析防御测试。"""
+
+    def test_parse_plain_json(self):
+        """Layer 1: 普通 JSON 应正确解析。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(responses=[{"rankings": [{"chunk_id": "c_1", "rerank_score": 0.9}]}])
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+        chunks = [make_hit("c_1", score=0.9, text="test")]
+
+        async def _run():
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=1,
+            )
+
+        result = asyncio.run(_run())
+        assert len(result) == 1
+
+    def test_parse_markdown_json_block(self):
+        """Layer 2: LLM 返回 markdown 包裹的 JSON 应正确提取。"""
+
+        # FakeLLMProvider 返回 dict 但实际 LLM 返回的可能是字符串
+        # 我们需要模拟 chat_json 返回原始文本的场景
+        # 这里验证的是解析逻辑，所以直接用内部解析方法
+        from ragnexus.adapters.rerank.llm import _parse_rankings_json
+
+        markdown_json = '```json\n{"rankings": [{"chunk_id": "c_1", "rerank_score": 0.9}]}\n```'
+        result = _parse_rankings_json(markdown_json)
+        assert len(result) == 1
+        assert result[0]["chunk_id"] == "c_1"
+        assert result[0]["rerank_score"] == 0.9
+
+    def test_parse_json_in_text(self):
+        """Layer 3: 文本中夹杂 JSON 应正确提取。"""
+        from ragnexus.adapters.rerank.llm import _parse_rankings_json
+
+        messy = '这是分析结果 {"rankings": [{"chunk_id": "c_1", "rerank_score": 0.9}]} 分析完毕'
+        result = _parse_rankings_json(messy)
+        assert len(result) == 1
+        assert result[0]["chunk_id"] == "c_1"
+
+    def test_parse_all_failed_returns_empty(self):
+        """Layer 4: 全失败时应返回空列表。"""
+        from ragnexus.adapters.rerank.llm import _parse_rankings_json
+
+        result = _parse_rankings_json("not json at all")
+        assert result == []
+
+
+class TestLLMRerankProviderDegradation:
+    """降级逻辑测试。"""
+
+    def test_degrade_on_llm_exception(self):
+        """LLM 抛异常时降级返回原始向量排序。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(responses=[RuntimeError("LLM boom")])
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        chunks = [
+            make_hit("c_2", score=0.85, text="text 2"),
+            make_hit("c_1", score=0.91, text="text 1"),
+            make_hit("c_3", score=0.70, text="text 3"),
+        ]
+
+        async def _run():
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=2,
+            )
+
+        result = asyncio.run(_run())
+
+        # 降级：不抛异常，返回原始向量排序的前 top_n
+        assert len(result) == 2
+        # 原始向量排序：c_1(0.91), c_2(0.85), c_3(0.70)
+        assert result[0].chunk_id == "c_1"
+        assert result[1].chunk_id == "c_2"
+        # score 不变
+        assert result[0].score == 0.91
+        assert result[1].score == 0.85
+
+    def test_degrade_on_json_parse_failure(self):
+        """JSON 解析全失败时降级返回原始排序。
+
+        模拟 LLM 返回无法解析的 dict（无 rankings 字段）。
+        """
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(responses=[{"garbage": "no rankings"}])
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        chunks = [
+            make_hit("c_1", score=0.91, text="text 1"),
+            make_hit("c_2", score=0.85, text="text 2"),
+        ]
+
+        async def _run():
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=2,
+            )
+
+        result = asyncio.run(_run())
+
+        # 降级返回原始排序
+        assert len(result) == 2
+        assert result[0].chunk_id == "c_1"
+
+    def test_degrade_never_throws(self):
+        """rerank 在任何情况下都不应抛异常。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        # 空 chunks
+        fake = FakeLLMProvider()
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        async def _run():
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=[],
+                top_n=5,
+            )
+
+        result = asyncio.run(_run())
+        assert result == []
+
+
+class TestLLMRerankProviderClearCache:
+    """clear_cache 测试。"""
+
+    def test_clear_cache_removes_kb_entries(self):
+        """clear_cache 应清空指定 KB 的缓存。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(
+            responses=[
+                {"rankings": [{"chunk_id": "c_1", "rerank_score": 0.8}]},
+                {"rankings": [{"chunk_id": "c_1", "rerank_score": 0.7}]},
+            ]
+        )
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        query_vector = [0.1] * 10
+        chunks = [make_hit("c_1", score=0.9, text="text 1")]
+
+        # 第一次调用写入缓存
+        asyncio.run(
+            provider.rerank(
+                query="测试",
+                query_vector=query_vector,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=1,
+            )
+        )
+        assert len(fake.calls) == 1
+
+        # 清空缓存
+        asyncio.run(provider.clear_cache("kb_001"))
+
+        # 第二次应再次调用 LLM（缓存被清空）
+        asyncio.run(
+            provider.rerank(
+                query="测试",
+                query_vector=query_vector,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=1,
+            )
+        )
+        assert len(fake.calls) == 2
+
+    def test_clear_cache_nonexistent_kb(self):
+        """clear_cache 对不存在的 KB 不应抛异常。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider()
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        async def _run():
+            await provider.clear_cache("nonexistent")
+
+        asyncio.run(_run())  # 不应抛异常
+
+
+class TestLLMRerankProviderPayloadConstruction:
+    """LLM payload 构造测试。"""
+
+    def test_payload_structure_full_miss(self):
+        """全 miss 场景下 payload 应包含 query、candidates、top_n。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(
+            responses=[
+                {
+                    "rankings": [
+                        {"chunk_id": "c_1", "rerank_score": 0.9},
+                        {"chunk_id": "c_2", "rerank_score": 0.8},
+                    ]
+                }
+            ]
+        )
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        chunks = [
+            make_hit(
+                "c_1",
+                score=0.91,
+                doc_id="d1",
+                text="chunk one",
+                metadata={"heading": "标题一"},
+            ),
+            make_hit("c_2", score=0.85, doc_id="d2", text="chunk two"),
+        ]
+
+        async def _run():
+            return await provider.rerank(
+                query="测试问题?",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=2,
+            )
+
+        asyncio.run(_run())
+
+        payload = fake.calls[0]["user_payload"]
+        assert payload["query"] == "测试问题?"
+        assert payload["top_n"] == 2
+        assert len(payload["candidates"]) == 2
+
+        c1 = payload["candidates"][0]
+        assert c1["chunk_id"] == "c_1"
+        assert c1["document_id"] == "d1"
+        assert c1["title"] == "标题一"
+        assert c1["content"] == "chunk one"
+        assert c1["vector_score"] == 0.91
+
+        c2 = payload["candidates"][1]
+        assert c2["title"] == ""  # 无 heading
+
+    def test_payload_title_none_fallback(self):
+        """metadata 无 heading 时 title 应为空字符串。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(responses=[{"rankings": [{"chunk_id": "c_1", "rerank_score": 0.9}]}])
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        chunks = [make_hit("c_1", score=0.9, text="test", metadata={})]
+
+        async def _run():
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=1,
+            )
+
+        asyncio.run(_run())
+
+        payload = fake.calls[0]["user_payload"]
+        assert payload["candidates"][0]["title"] == ""
+
+
+class TestLLMRerankProviderScoreEdgeCases:
+    """分数边界测试。"""
+
+    def test_llm_missing_chunk_id_gets_default_score(self):
+        """LLM 未返回某个 chunk 时，该 chunk 默认 rerank_score = 0。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(
+            responses=[
+                {
+                    "rankings": [
+                        {"chunk_id": "c_1", "rerank_score": 0.9},
+                        # c_2 被 LLM 漏掉
+                    ]
+                }
+            ]
+        )
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        chunks = [
+            make_hit("c_1", score=0.91, text="t1"),
+            make_hit("c_2", score=0.85, text="t2"),
+        ]
+
+        async def _run():
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=2,
+            )
+
+        result = asyncio.run(_run())
+
+        # c_1 (0.9) 在前，c_2 (0.0) 在后
+        assert result[0].chunk_id == "c_1"
+        assert result[1].chunk_id == "c_2"
+
+    def test_llm_unknown_chunk_id_ignored(self):
+        """LLM 返回不存在的 chunk_id 应被忽略。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(
+            responses=[
+                {
+                    "rankings": [
+                        {"chunk_id": "c_1", "rerank_score": 0.9},
+                        {
+                            "chunk_id": "c_unknown",
+                            "rerank_score": 0.99,
+                        },  # 不在输入 chunks 中
+                    ]
+                }
+            ]
+        )
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        chunks = [make_hit("c_1", score=0.91, text="t1")]
+
+        async def _run():
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=1,
+            )
+
+        result = asyncio.run(_run())
+        assert len(result) == 1
+        assert result[0].chunk_id == "c_1"
+
+    def test_rerank_score_clamped_to_0_1(self):
+        """超出 [0,1] 的 rerank_score 应被 clamp。"""
+        from ragnexus.adapters.rerank.llm import LLMRerankProvider
+
+        fake = FakeLLMProvider(
+            responses=[
+                {
+                    "rankings": [
+                        {"chunk_id": "c_1", "rerank_score": 1.5},
+                        {"chunk_id": "c_2", "rerank_score": -0.5},
+                    ]
+                }
+            ]
+        )
+
+        provider = LLMRerankProvider(llm=fake)  # type: ignore[arg-type]
+
+        chunks = [
+            make_hit("c_1", score=0.91, text="t1"),
+            make_hit("c_2", score=0.85, text="t2"),
+        ]
+
+        async def _run():
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.1] * 10,
+                kb_ids=["kb_001"],
+                chunks=chunks,
+                top_n=2,
+            )
+
+        result = asyncio.run(_run())
+        assert len(result) == 2
+        # c_1 的 rerank_score 被 clamp 到 1.0，应排前面
+        assert result[0].chunk_id == "c_1"  # clamped to 1.0
+        # score 仍然是原始向量分
+        assert result[0].score == 0.91
+
+
+class TestCacheEntry:
+    """CacheEntry 数据类测试。"""
+
+    def test_cache_entry_fields(self):
+        """CacheEntry 应正确存储字段。"""
+        from ragnexus.adapters.rerank.llm import CacheEntry
+
+        entry = CacheEntry(
+            query_embedding=[0.1, 0.2],
+            query_text="测试",
+            rankings={"c_1": 0.9},
+            timestamp=123456.0,
+        )
+        assert entry.query_embedding == [0.1, 0.2]
+        assert entry.query_text == "测试"
+        assert entry.rankings == {"c_1": 0.9}
+        assert entry.timestamp == 123456.0
diff --git a/tests/unit/test_noop_rerank.py b/tests/unit/test_noop_rerank.py
new file mode 100644
index 0000000..c2c6357
--- /dev/null
+++ b/tests/unit/test_noop_rerank.py
@@ -0,0 +1,201 @@
+"""NoopRerankProvider 单元测试。
+
+TDD: RED → GREEN。验证直通重排提供者的行为正确性。
+"""
+
+from __future__ import annotations
+
+import asyncio
+
+from ragnexus.domain.models import SearchHit
+from ragnexus.domain.ports import RerankPort
+
+
+class TestNoopRerankProvider:
+    """NoopRerankProvider 直通行为测试。"""
+
+    def test_provider_exists(self) -> None:
+        """NoopRerankProvider 应从 adapters.rerank 包导入。"""
+        from ragnexus.adapters.rerank.noop import NoopRerankProvider
+
+        assert NoopRerankProvider is not None
+
+    def test_satisfies_rerank_port_protocol(self) -> None:
+        """NoopRerankProvider 满足 RerankPort 协议 — 行为验证。
+
+        运行时通过 inspect 验证方法签名匹配 Protocol 定义，
+        并实际调用验证返回类型正确。不使用 issubclass
+        （RerankPort 非 @runtime_checkable）。
+        """
+        import inspect
+
+        from ragnexus.adapters.rerank.noop import NoopRerankProvider
+
+        instance = NoopRerankProvider()
+        cls = NoopRerankProvider
+
+        # 验证方法存在
+        assert hasattr(cls, "rerank"), "缺少 rerank 方法"
+        assert hasattr(cls, "clear_cache"), "缺少 clear_cache 方法"
+
+        # 验证 rerank 签名：keyword-only 参数
+        rerank_sig = inspect.signature(cls.rerank)
+        rerank_params = list(rerank_sig.parameters.values())
+        # self + 5 keyword-only 参数
+        assert (
+            rerank_sig.return_annotation == list[SearchHit]
+        ), f"rerank 返回类型应为 list[SearchHit]，实际: {rerank_sig.return_annotation}"
+        for p in rerank_params[1:]:
+            assert (
+                p.kind == inspect.Parameter.KEYWORD_ONLY
+            ), f"rerank 参数 {p.name} 应为 KEYWORD_ONLY"
+
+        # 验证 clear_cache 签名
+        cc_sig = inspect.signature(cls.clear_cache)
+        cc_params = list(cc_sig.parameters.values())
+        assert len(cc_params) == 2  # self + kb_id
+        assert cc_params[1].name == "kb_id"
+        assert cc_params[1].annotation is str
+        assert cc_sig.return_annotation is None
+
+        # 验证实际行为：rerank 返回 list[SearchHit]
+        async def _run() -> list[SearchHit]:
+            return await instance.rerank(
+                query="test",
+                query_vector=[0.1],
+                kb_ids=["kb1"],
+                chunks=[],
+                top_n=5,
+            )
+
+        result = asyncio.run(_run())
+        assert isinstance(result, list)
+
+    def test_rerank_returns_same_chunks_no_modification(self) -> None:
+        """rerank() 直接返回原始 chunks，不排序、不截断。
+
+        禁用重排时的直通行为：传入什么就返回什么，不做任何修改。
+        """
+        from ragnexus.adapters.rerank.noop import NoopRerankProvider
+
+        provider = NoopRerankProvider()
+
+        chunks = [
+            SearchHit(
+                chunk_id="c1",
+                kb_id="kb_alpha",
+                doc_id="doc_a",
+                score=0.5,
+                text="中等相关",
+                metadata={"page": 1},
+            ),
+            SearchHit(
+                chunk_id="c3",
+                kb_id="kb_alpha",
+                doc_id="doc_a",
+                score=0.9,
+                text="高度相关",
+                metadata={"page": 3},
+            ),
+            SearchHit(
+                chunk_id="c2",
+                kb_id="kb_alpha",
+                doc_id="doc_a",
+                score=0.3,
+                text="低相关",
+                metadata={"page": 2},
+            ),
+        ]
+
+        async def _run() -> list[SearchHit]:
+            return await provider.rerank(
+                query="测试查询",
+                query_vector=[0.1, 0.2, 0.3],
+                kb_ids=["kb_alpha"],
+                chunks=chunks,
+                top_n=2,
+            )
+
+        result = asyncio.run(_run())
+
+        # 返回的列表长度与原始相同（不截断，忽略 top_n）
+        assert len(result) == 3, f"直通应返回全部 chunks，期望 3，实际 {len(result)}"
+
+        # 返回的是同一批对象（is 检查），表示没有复制
+        assert result is chunks, f"rerank 应返回完全相同的列表对象"
+
+        # 分值不变 — 不排序，保持原始顺序
+        assert result[0].score == 0.5, "第一个元素分值不应改变"
+        assert result[1].score == 0.9, "第二个元素分值不应改变"
+        assert result[2].score == 0.3, "第三个元素分值不应改变"
+
+        # 所有字段保持不变
+        assert result[0].chunk_id == "c1"
+        assert result[0].text == "中等相关"
+        assert result[0].metadata == {"page": 1}
+        assert result[1].chunk_id == "c3"
+        assert result[1].text == "高度相关"
+        assert result[1].metadata == {"page": 3}
+        assert result[2].chunk_id == "c2"
+        assert result[2].text == "低相关"
+        assert result[2].metadata == {"page": 2}
+
+    def test_rerank_empty_list_returns_empty(self) -> None:
+        """空列表传入时应返回空列表。"""
+        from ragnexus.adapters.rerank.noop import NoopRerankProvider
+
+        provider = NoopRerankProvider()
+
+        async def _run() -> list[SearchHit]:
+            return await provider.rerank(
+                query="测试",
+                query_vector=[0.0],
+                kb_ids=[],
+                chunks=[],
+                top_n=10,
+            )
+
+        result = asyncio.run(_run())
+        assert result == []
+
+    def test_rerank_ignores_top_n(self) -> None:
+        """即使 top_n < len(chunks)，也应该返回全部 chunks（直通）。"""
+        from ragnexus.adapters.rerank.noop import NoopRerankProvider
+
+        provider = NoopRerankProvider()
+
+        chunks = [
+            SearchHit(
+                chunk_id=f"c{i}",
+                kb_id="kb1",
+                doc_id="d1",
+                score=float(i),
+                text=f"chunk {i}",
+                metadata={},
+            )
+            for i in range(5)
+        ]
+
+        async def _run() -> list[SearchHit]:
+            return await provider.rerank(
+                query="q",
+                query_vector=[0.0],
+                kb_ids=["kb1"],
+                chunks=chunks,
+                top_n=2,  # 请求只取前2，但直通应忽略
+            )
+
+        result = asyncio.run(_run())
+        assert len(result) == 5, f"直通应返回全部 5 个 chunks，实际 {len(result)}"
+
+    def test_clear_cache_is_noop(self) -> None:
+        """clear_cache() 应为空实现，不抛异常。"""
+        from ragnexus.adapters.rerank.noop import NoopRerankProvider
+
+        provider = NoopRerankProvider()
+
+        # 不应抛出任何异常
+        async def _run() -> None:
+            await provider.clear_cache("kb_any")
+
+        asyncio.run(_run())  # 通过即表示空实现正确
