"""PgKnowledgeBaseRepository.list_with_documents() 集成测试。"""

import pytest

from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository

pytestmark = [pytest.mark.integration]

_COUNTER = 0


def _unique_name(prefix: str = "tree") -> str:
    global _COUNTER
    _COUNTER += 1
    return f"{prefix}_{_COUNTER}"


async def _create_kb_with_docs(
    pool, tenant_id: str, kb_name: str, filenames: list[str]
) -> str:
    """创建 KB 并插入文档，返回 kb_id。"""
    repo = PgKnowledgeBaseRepository(pool)
    kb = await repo.create(name=kb_name, name_key=kb_name, tenant_id=tenant_id)
    for fn in filenames:
        doc_id = f"doc_{kb_name}_{fn}"
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO documents (doc_id, kb_id, filename, file_hash, file_size, content_type, chunk_count) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                doc_id,
                kb.id,
                fn,
                "sha1_dummy",
                100,
                "text/markdown",
                3,
            )
    return kb.id


class TestListWithDocuments:
    """PgKnowledgeBaseRepository.list_with_documents() 集成测试。"""

    @pytest.mark.asyncio
    async def test_empty_tree(self, pg_pool):
        """无 KB 时返回空列表。"""
        repo = PgKnowledgeBaseRepository(pg_pool)
        result = await repo.list_with_documents()
        assert result == []

    @pytest.mark.asyncio
    async def test_single_tenant_single_kb_no_docs(self, pg_pool):
        """单个租户单个 KB 无文档 → KBNode.documents 为空。"""
        repo = PgKnowledgeBaseRepository(pg_pool)
        name = _unique_name("naked")
        await repo.create(name=name, name_key=name, tenant_id="tenant_x")

        result = await repo.list_with_documents()
        assert len(result) == 1
        assert result[0].tenant_id == "tenant_x"
        assert len(result[0].knowledge_bases) == 1
        kb_node = result[0].knowledge_bases[0]
        assert kb_node.name == name
        assert kb_node.document_count == 0
        assert kb_node.total_chunks == 0
        assert kb_node.documents == []

    @pytest.mark.asyncio
    async def test_single_tenant_single_kb_with_docs(self, pg_pool):
        """单个租户单个 KB 有文档 → 树结构正确。"""
        tenant = _unique_name("t")
        kb_name = _unique_name("kb")
        await _create_kb_with_docs(pg_pool, tenant, kb_name, ["a.md", "b.md"])

        repo = PgKnowledgeBaseRepository(pg_pool)
        result = await repo.list_with_documents()

        assert len(result) == 1
        assert result[0].tenant_id == tenant
        kb_node = result[0].knowledge_bases[0]
        assert kb_node.name == kb_name
        assert kb_node.document_count == 2
        assert kb_node.total_chunks == 6  # 3 per doc
        filenames = [d.filename for d in kb_node.documents]
        assert set(filenames) == {"a.md", "b.md"}

    @pytest.mark.asyncio
    async def test_multi_tenant(self, pg_pool):
        """多租户分组正确且按 tenant_id 排序。"""
        repo = PgKnowledgeBaseRepository(pg_pool)
        await repo.create(
            name=_unique_name("t1"),
            name_key=_unique_name("t1k"),
            tenant_id="tenant_a",
        )
        await repo.create(
            name=_unique_name("t2"),
            name_key=_unique_name("t2k"),
            tenant_id="tenant_b",
        )

        result = await repo.list_with_documents()
        tenant_ids = [t.tenant_id for t in result]
        assert tenant_ids == sorted(tenant_ids)

    @pytest.mark.asyncio
    async def test_keyword_filter_matches(self, pg_pool):
        """keyword 匹配 tenant_id 子串 → 只返回匹配租户。"""
        repo = PgKnowledgeBaseRepository(pg_pool)
        await repo.create(
            name=_unique_name("m1"),
            name_key=_unique_name("m1k"),
            tenant_id="apple_inc",
        )
        await repo.create(
            name=_unique_name("m2"),
            name_key=_unique_name("m2k"),
            tenant_id="apple_corp",
        )
        await repo.create(
            name=_unique_name("m3"),
            name_key=_unique_name("m3k"),
            tenant_id="banana_corp",
        )

        result = await repo.list_with_documents(keyword="apple")
        assert len(result) == 2
        tenant_ids = [t.tenant_id for t in result]
        assert "apple_inc" in tenant_ids
        assert "apple_corp" in tenant_ids

    @pytest.mark.asyncio
    async def test_keyword_filter_no_match(self, pg_pool):
        """keyword 无匹配 → 返回空列表。"""
        repo = PgKnowledgeBaseRepository(pg_pool)
        await repo.create(
            name=_unique_name("nm"),
            name_key=_unique_name("nmk"),
            tenant_id="only_this",
        )
        result = await repo.list_with_documents(keyword="nope")
        assert result == []
