"""展示 rewrite 的实际输出质量"""

import asyncio
import os
import time

os.environ["RERANK_ENABLED"] = "true"
os.environ["REWRITE_ENABLED"] = "true"

from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder  # noqa: E402
from ragnexus.adapters.llm.openai_compatible import (
    OpenAICompatibleLLMProvider,
)  # noqa: E402
from ragnexus.adapters.rewrite.llm import LLMRewriteProvider  # noqa: E402
from ragnexus.config import get_settings  # noqa: E402


async def show_rewrite(llm, embedder, query, kb_ids):
    rewriter = LLMRewriteProvider(llm=llm, embedder=embedder)
    t0 = time.perf_counter()
    result = await rewriter.rewrite(query=query, kb_ids=kb_ids)
    elapsed = time.perf_counter() - t0
    changed = "✏️改写" if result.needs_rewrite else "➡️直通"
    print(f"  [{changed}] {elapsed:.1f}s")
    print(f'  Input:  "{result.original_query}"')
    if result.needs_rewrite:
        print(f'  Output: "{result.rewritten_query}"')
        print(f"  Why:    {result.reason}")
    return result


async def main():
    cfg = get_settings()
    embedder = OpenAICompatEmbedder(
        base_url=cfg.EMBED_BASE_URL,
        api_key=cfg.EMBED_API_KEY,
        model=cfg.EMBED_MODEL,
        dim=cfg.EMBED_DIM,
    )
    llm = OpenAICompatibleLLMProvider(
        base_url=cfg.LLM_BASE_URL,
        api_key=cfg.LLM_API_KEY,
        model=cfg.LLM_MODEL,
    )
    kb_ids = ["kb_3FtAzN4Z"]

    queries = [
        "它跟传统搜索比有啥好处",
        "怎么做智能助手",
        "agent咋用",
        "Transformer自注意力机制",
    ]

    print("=" * 60)
    print("Rewrite 质量 — LLM 改写决策")
    print("=" * 60)
    for q in queries:
        print(f'\n--- "{q}" ---')
        try:
            await show_rewrite(llm, embedder, q, kb_ids)
        except Exception as e:
            print(f"  ❌ {e}")

    print("\n" + "=" * 60)


asyncio.run(main())
