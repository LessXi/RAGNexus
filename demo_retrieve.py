"""RAGNexus LLM 重排/改写 功能演示 v2 (parser 修复后)。
对比禁用/启用两种模式下的 retrieve 输出差异。
用法: uv run python demo_retrieve.py
"""

import asyncio
import os
import time

# 指向 test-db，在 import config 前设置
os.environ["PG_DSN"] = "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"
os.environ["RERANK_ENABLED"] = "false"
os.environ["REWRITE_ENABLED"] = "false"

from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder  # noqa: E402
from ragnexus.adapters.llm.openai_compatible import (
    OpenAICompatibleLLMProvider,
)  # noqa: E402
from ragnexus.adapters.rerank.llm import LLMRerankProvider  # noqa: E402
from ragnexus.adapters.rewrite.llm import LLMRewriteProvider  # noqa: E402
from ragnexus.application.create_kb_use_case import (
    CreateKnowledgeBaseUseCase,
)  # noqa: E402
from ragnexus.application.retrieve_use_case import RetrieveUseCase  # noqa: E402
from ragnexus.composition import build_app  # noqa: E402
from ragnexus.config import get_settings  # noqa: E402

_BASE_DOC = """# RAG 检索增强生成技术指南

## 什么是 RAG
RAG (Retrieval-Augmented Generation) 是一种结合检索和生成的大语言模型应用范式。
它先从知识库中检索相关文档片段，再将检索结果作为上下文注入到大模型的生成过程中。

## RAG 的核心组件
1. **文档解析器** — 将 PDF、Markdown、Word 等格式解析为纯文本
2. **文本分块器** — 按语义边界将长文档切分为合适大小的 chunk
3. **嵌入模型** — 将文本片段编码为稠密向量
4. **向量数据库** — 存储和索引高维向量，支持近似最近邻搜索
5. **检索器** — 根据用户查询从向量库中召回相关片段
6. **生成器** — 大语言模型根据检索到的上下文生成回答

## 高级优化技术
- **查询改写**：在嵌入前对用户 query 进行优化，补全指代、纠正拼写、扩展语义
- **重排序**：用交叉编码器或 LLM 对向量召回的候选进行精排，提升 Top-K 准确率
- **混合检索**：结合向量检索和关键词检索 (BM25)，取长补短

## 常见问题
1. 检索到的文档可能包含不相关的噪音
2. 向量相似度高不代表语义相关性强
3. 短查询缺乏上下文，导致嵌入质量差

## 最佳实践
- 使用 LLM 进行查询改写，将口语化表达转为标准化查询
- 在重排序阶段引入 LLM，对候选文档进行相关性评分
- 保持 chunk 大小适中 (500-1500 字符)，避免过长或过短
"""


def _make_doc(ts: int) -> str:
    return f"<!-- ts={ts} -->\n{_BASE_DOC}"


def print_separator(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


async def demo():
    ts = int(time.time())
    print_separator(f"RAGNexus LLM 重排/改写 功能演示 v2 (ts={ts})")

    app = build_app()
    async with app.router.lifespan_context(app):
        cfg = get_settings()
        print(f"\n[启动] PG_DSN={cfg.PG_DSN}")
        print(f"  RERANK_ENABLED={cfg.RERANK_ENABLED} REWRITE_ENABLED={cfg.REWRITE_ENABLED}")

        wrapped = app.state.upload_doc_uc
        kb_repo = wrapped._inner._kb_repo

        # --- KB + 文档 ---
        print_separator("创建 KB 并上传文档")
        kb = await CreateKnowledgeBaseUseCase(kb_repo=kb_repo).execute(name=f"演示KB-{ts % 100000}")
        kb_id = kb.id
        print(f"  KB: {kb_id}")

        result = await wrapped.execute(
            kb_id=kb_id,
            file_content=_make_doc(ts).encode("utf-8"),
            filename="rag_guide.md",
            content_type="text/markdown",
        )
        print(f"  文档: {result.doc_id} chunks={len(result.chunks)}")
        await asyncio.sleep(1)

        # --- 基线 ---
        print_separator("基线模式 (禁用 Rerank+Rewrite)")
        query = "怎么优化检索的准确率"
        base = app.state.retrieve_uc

        print(f"  查询: 「{query}」")
        hits_bl = await base.execute(query=query, kb_ids=[kb_id], top_k=5)
        print(f"  结果 ({len(hits_bl)}):")
        for i, h in enumerate(hits_bl):
            print(f"    {i + 1}. [{h.score:.4f}] {h.chunk_id} | {h.text[:80]}...")

        # --- LLM 增强 ---
        print_separator("LLM 增强模式 (Rewrite+Rerank)")

        llm = OpenAICompatibleLLMProvider(
            base_url=cfg.LLM_BASE_URL,
            api_key=cfg.LLM_API_KEY,
            model=cfg.LLM_MODEL,
            max_concurrency=cfg.LLM_MAX_CONCURRENCY,
            max_retries=cfg.LLM_MAX_RETRIES,
            request_timeout=cfg.LLM_REQUEST_TIMEOUT,
            connect_timeout=cfg.LLM_CONNECT_TIMEOUT,
            retry_backoff_base=cfg.LLM_RETRY_BACKOFF_BASE,
        )
        embedder = OpenAICompatEmbedder(
            base_url=cfg.EMBED_BASE_URL,
            api_key=cfg.EMBED_API_KEY,
            model=cfg.EMBED_MODEL,
            dim=cfg.EMBED_DIM,
            batch_size=cfg.EMBED_BATCH_SIZE,
            max_concurrency=cfg.EMBED_MAX_CONCURRENCY,
            max_retries=cfg.EMBED_MAX_RETRIES,
            request_timeout=cfg.EMBED_REQUEST_TIMEOUT,
            connect_timeout=cfg.EMBED_CONNECT_TIMEOUT,
            retry_backoff_base=cfg.EMBED_RETRY_BACKOFF_BASE,
        )

        enhanced = RetrieveUseCase(
            kb_repo=base._kb_repo,
            embedder=embedder,
            store=base._store,
            log_port=base._log_port,
            reranker=LLMRerankProvider(
                llm=llm,
                max_candidates=cfg.RERANK_MAX_CANDIDATES,
                chunk_max_chars=cfg.RERANK_CHUNK_MAX_CHARS,
                cache_similarity_threshold=cfg.RERANK_CACHE_SIMILARITY_THRESHOLD,
                cache_max_entries=cfg.RERANK_CACHE_MAX_ENTRIES,
                cache_ttl_seconds=cfg.RERANK_CACHE_TTL_SECONDS,
                temperature=cfg.RERANK_TEMPERATURE,
            ),
            rewriter=LLMRewriteProvider(
                llm=llm,
                embedder=embedder,
                cache_similarity_threshold=cfg.REWRITE_CACHE_SIMILARITY_THRESHOLD,
                cache_max_entries=cfg.REWRITE_CACHE_MAX_ENTRIES,
                cache_ttl_seconds=cfg.REWRITE_CACHE_TTL_SECONDS,
                temperature=cfg.REWRITE_TEMPERATURE,
            ),
            candidate_multiplier=cfg.RERANK_CANDIDATE_MULTIPLIER,
            min_candidates=cfg.RERANK_MIN_CANDIDATES,
        )

        print(f"  查询: 「{query}」")
        t0 = time.monotonic()
        hits_en = await enhanced.execute(query=query, kb_ids=[kb_id], top_k=5)
        elapsed = time.monotonic() - t0
        print(f"\n  耗时: {elapsed:.2f}s  结果 ({len(hits_en)}):")
        for i, h in enumerate(hits_en):
            print(f"    {i + 1}. [{h.score:.4f}] {h.chunk_id} | {h.text[:80]}...")

        # --- 对比 ---
        print_separator("对比")
        changed = any(
            i < len(hits_bl) and i < len(hits_en) and hits_bl[i].chunk_id != hits_en[i].chunk_id
            for i in range(min(len(hits_bl), len(hits_en)))
        )
        if changed:
            print("  ✅ LLM 重排改变了结果顺序！(parser 修复生效)")
        else:
            print("  ℹ️  排序未变")
        print("  🔍 检查: WARNING 'rewrite降级' 应消失 | Rerank 排序应变化")

    print(f"\n{'=' * 60}\n  演示完成\n{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(demo())
