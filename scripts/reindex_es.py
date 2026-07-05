"""一次性脚本：将 PostgreSQL 所有 chunk 重新索引到 Elasticsearch。"""

import asyncio
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import json

import asyncpg

from ragnexus.adapters.keyword_search.elasticsearch import ESKeywordSearchProvider
from ragnexus.config import get_settings
from ragnexus.domain.models import Chunk


async def main() -> None:
    s = get_settings()
    if not s.ES_ENABLED:
        print("❌ ES 未启用，请先设置 ES_ENABLED=true")
        return

    pg = await asyncpg.connect(dsn=s.PG_DSN)
    total = await pg.fetchval("SELECT COUNT(*) FROM chunks")
    print(f"📊 PG 中共 {total} 个 chunks")

    es = ESKeywordSearchProvider(
        url=s.ELASTICSEARCH_URL,
        index=s.ELASTICSEARCH_INDEX,
        request_timeout=30,
    )
    await es.connect()
    await es.ensure_index()

    batch_size = 200
    offset = 0
    indexed = 0
    while True:
        rows = await pg.fetch(
            "SELECT id, kb_id, doc_id, text, metadata FROM chunks ORDER BY doc_id, id LIMIT $1 OFFSET $2",
            batch_size,
            offset,
        )
        if not rows:
            break

        by_kb: dict[str, list[Chunk]] = defaultdict(list)
        for r in rows:
            by_kb[r["kb_id"]].append(
                Chunk(
                    id=r["id"],
                    kb_id=r["kb_id"],
                    doc_id=r["doc_id"],
                    text=r["text"],
                    vector=[],
                    metadata=json.loads(r["metadata"] or "{}"),
                )
            )

        for kb_id, chunks in by_kb.items():
            await es.upsert(kb_id, chunks)
            indexed += len(chunks)

        offset += batch_size
        print(f"  {indexed}/{total}")

    await es.close()
    await pg.close()
    print(f"🎉 {indexed} 个 chunks 已索引")


if __name__ == "__main__":
    asyncio.run(main())
