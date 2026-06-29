"""集成测试：UploadDocumentUseCase 全链路 — 端到端上传、检索、DB 验证。

依赖 test-db (Docker + pgvector, 端口 5433)。
embedder HTTP 通过 httpx_mock 模拟，返回预定义向量 [0.1]*dim。
"""

import json
import re

import httpx
import pytest
from pgvector.asyncpg import register_vector

from ragnexus.adapters.embedder.openai_compat import OpenAICompatEmbedder
from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository
from ragnexus.adapters.parsers.md_and_txt import MarkdownAndTextParser
from ragnexus.adapters.vector_store.pgvector import PgVectorStore
from ragnexus.application.upload_doc_use_case import UploadDocumentUseCase
from ragnexus.domain.chunking import heading_aware_split

pytestmark = [pytest.mark.integration]

# 对齐 Settings.EMBED_DIM 和 schema.sql 默认值
TEST_DIM = 1024
# 预定义向量 — 所有 chunk 共享同一 mock 向量
_MOCK_VEC = [0.1] * TEST_DIM

_COUNTER = 0


def _unique_suffix() -> str:
    """生成递增编号，确保每次测试产生不同的 KB ID。"""
    global _COUNTER
    _COUNTER += 1
    return f"int{_COUNTER}"


_MD_BODY = """\
# 标题一
这是第一个章节的内容，包含一些测试文字。
这是第一段的第二句，用于增加内容长度。
这是第一段的第三句，进一步扩展文本量以产生多个 chunk。

## 子标题 A
这是子章节 A 的内容，用于测试 Markdown 标题解析。
这里还有更多内容以确保 chunker 能够正确分块。
添加第三行来确保有足够的文本量用于多个块的生成。

# 标题二
这是第二个章节的完整内容，与标题一完全独立。
第二段的补充内容，用于验证分段逻辑的正确性。
第三行继续补充内容以确保 chunk 数至少为 2。

## 子标题 B
更深层级的章节，用于测试多级标题下的内容分段。

这一章节内容足够多，保证单独成为一个 chunk。
继续添加文本以确保 chunker 按预期工作。

# 标题三
第三个一级章节，增加更多独立内容。
确保最终至少有 2 个 chunk 被创建。
文本长短不一以验证 chunker 边界行为。
"""

_MD_FILE = _MD_BODY.encode("utf-8")


class TestUploadFullChain:
    """UploadDocumentUseCase 真实集成测试 — 全链路验证。"""

    async def test_upload_creates_chunks_and_retrievable(self, pg_pool, httpx_mock):
        """端到端：创建 KB → 上传 Markdown → chunk_count >= 2 → 检索命中 → DB 验证。

        1. PgKnowledgeBaseRepository 创建 KB
        2. UploadDocumentUseCase（真实依赖 + HTTP mock）上传 Markdown
        3. 断言 chunk_count >= 2
        4. PgVectorStore.search_by_vector 检索 → ≥1 命中
        5. 直接查询 chunks 表 → 验证行数、text、embedding 维度

        所有 HTTP 请求通过 httpx_mock 拦截，embedder 返回 [0.1]*1024。
        """

        # ── 0. Mock embedder HTTP ──
        def _embed_callback(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            texts_input = body.get("input", [])
            count = len(texts_input) if isinstance(texts_input, list) else 1
            return httpx.Response(
                status_code=200,
                json={"data": [{"embedding": _MOCK_VEC, "index": i} for i in range(count)]},
            )

        httpx_mock.add_callback(
            _embed_callback,
            method="POST",
            url=re.compile(r".*/embeddings$"),
        )

        # ── 1. 创建 KB ──
        suffix = _unique_suffix()
        kb_repo = PgKnowledgeBaseRepository(pg_pool)
        kb = await kb_repo.create(name=f"上传测试_{suffix}", name_key=f"upload_test_{suffix}")

        # ── 2. 构建依赖 ──
        embedder = OpenAICompatEmbedder(
            base_url="http://mock-embedder/v1",
            api_key="test-key",
            model="test-model",
            dim=TEST_DIM,
            batch_size=50,
            max_concurrency=2,
            max_retries=1,
            request_timeout=5.0,
            connect_timeout=2.0,
            retry_backoff_base=0.01,
        )

        parser = MarkdownAndTextParser()
        chunker = heading_aware_split
        store = PgVectorStore(dsn="ignored", pool_min=1, pool_max=2)
        # 复用 pg_pool（external_pool 模式）避免创建额外连接池
        await store.connect(external_pool=pg_pool)

        # ── 3. 构建 Use Case ──
        uc = UploadDocumentUseCase(
            kb_repo=kb_repo,
            parser=parser,
            embedder=embedder,
            chunker=chunker,
            store=store,
            chunk_max_chars=500,  # 较小 chunk 确保 >= 2
            chunk_overlap=50,
        )

        # ── 4. 上传 ──
        result = await uc.execute(
            kb_id=kb.id,
            file_content=_MD_FILE,
            filename="test_upload.md",
            content_type="text/markdown",
        )

        assert result.chunk_count >= 2, f"期望至少 2 个 chunk，实际 {result.chunk_count}"
        assert result.doc_id.startswith("doc_")
        assert result.kb_id == kb.id

        # ── 5. 检索验证 ──
        hits = await store.search_by_vector(
            query_vector=_MOCK_VEC,
            top_k=10,
            kb_ids=[kb.id],
        )

        assert len(hits) >= 1, f"检索期望至少 1 个命中，实际 {len(hits)}"
        # 验证命中属于当前 doc
        assert all(h.kb_id == kb.id for h in hits)

        # ── 6. DB 直接验证 ──
        async with pg_pool.acquire() as conn:
            # external_pool 不自动注册 pgvector 编解码器，需手动注册
            await register_vector(conn)

            # 验证 chunks 表
            rows = await conn.fetch(
                "SELECT id, kb_id, doc_id, text, embedding, metadata "
                "FROM chunks WHERE kb_id = $1 ORDER BY id",
                kb.id,
            )
            assert len(rows) == result.chunk_count, (
                f"chunks 表 {len(rows)} 行 != {result.chunk_count}"
            )
            for row in rows:
                assert row["text"], f"chunk {row['id']} text 为空"
                assert row["embedding"] is not None, f"chunk {row['id']} embedding 为 None"
                assert len(row["embedding"]) == TEST_DIM, (
                    f"chunk {row['id']} 维度 {len(row['embedding'])} != {TEST_DIM}"
                )

            # 验证 documents 表
            doc_rows = await conn.fetch(
                "SELECT doc_id, kb_id, filename, chunk_count FROM documents WHERE doc_id = $1",
                result.doc_id,
            )
            assert len(doc_rows) == 1, f"documents 表缺少 {result.doc_id}"
            assert doc_rows[0]["chunk_count"] == result.chunk_count
            assert doc_rows[0]["filename"] == "test_upload.md"

        # ── 清理 ──
        await embedder.close()
