"""异步索引 E2E 测试 — 需要 Docker (test-db + Redis + ES)。

标记: @pytest.mark.e2e
"""

import uuid

import asyncpg
import pytest
import pytest_asyncio

# conftest 已在模块级别设置 pytestmark = [pytest.mark.e2e]
# 此处导入 reuse conftest 的 fixtures

TEST_DSN = "postgresql://ragnexus:ragnexus@localhost:15433/ragnexus_test"


@pytest_asyncio.fixture
async def pg_pool(_require_test_db, _apply_schema):
    """E2E 级的数据库连接池。"""
    pool = await asyncpg.create_pool(
        TEST_DSN, min_size=1, max_size=3, command_timeout=15
    )
    # 确保 default 租户存在
    await pool.execute(
        "INSERT INTO tenants (id, name, status) VALUES ('default', '默认租户', 'active') "
        "ON CONFLICT (id) DO NOTHING"
    )
    yield pool
    await pool.close()


# =============================================================================
# 6.6 E2E: PROCESSING 文档删除拒绝 / KB 下有 PROCESSING 文档时删除 KB 拒绝
# =============================================================================


@pytest.mark.asyncio
async def test_cannot_delete_processing_document(client, pg_pool: asyncpg.Pool):
    """6.6a: PROCESSING 状态的文档，DELETE 返回 RESOURCE_CONFLICT。

    通过 API DELETE /v1/documents/{doc_id} 端点验证。
    需要先创建 KB 和 PROCESSING 文档。
    """
    kb_id = f"kb_{uuid.uuid4().hex[:8]}"
    doc_id = f"doc_{uuid.uuid4().hex[:16]}"

    # 创建 KB
    await pg_pool.execute(
        "INSERT INTO knowledge_bases (id, name, description, tenant_id) "
        "VALUES ($1, 'E2E KB', 'test', 'default')",
        kb_id,
    )

    # 创建 PROCESSING 文档
    await pg_pool.execute(
        "INSERT INTO documents "
        "(doc_id, kb_id, filename, file_hash, file_size, content_type, content, status) "
        "VALUES ($1, $2, 'test.md', 'abc', 100, 'text/markdown', '# Test', 2)",
        doc_id,
        kb_id,
    )

    try:
        # 尝试删除 PROCESSING 文档
        resp = client.delete(f"/v1/documents/{doc_id}")
        body = resp.json()

        # 应被拒绝 — 状态为 PROCESSING
        assert resp.status_code == 409
        assert body["code"] == 10301  # RESOURCE_CONFLICT
        assert "索引" in body["message"] or "PROCESSING" in str(body)

        # 验证文档仍存在
        row = await pg_pool.fetchrow(
            "SELECT status FROM documents WHERE doc_id = $1", doc_id
        )
        assert row is not None
        assert row["status"] == 2

    finally:
        # 清理：先将状态改为 SUCCESS 才能删除
        await pg_pool.execute(
            "UPDATE documents SET status = 1 WHERE doc_id = $1", doc_id
        )
        await pg_pool.execute("DELETE FROM documents WHERE doc_id = $1", doc_id)
        await pg_pool.execute("DELETE FROM knowledge_bases WHERE id = $1", kb_id)


@pytest.mark.asyncio
async def test_cannot_delete_kb_with_processing_docs(client, pg_pool: asyncpg.Pool):
    """6.6b: 知识库下有 PROCESSING 文档时，DELETE KB 返回 RESOURCE_CONFLICT。

    通过 API DELETE /v1/knowledge-bases/{kb_id} 端点验证。
    """
    kb_id = f"kb_{uuid.uuid4().hex[:8]}"
    doc_id = f"doc_{uuid.uuid4().hex[:16]}"

    # 创建 KB + PROCESSING 文档
    await pg_pool.execute(
        "INSERT INTO knowledge_bases (id, name, description, tenant_id) "
        "VALUES ($1, 'E2E KB2', 'test', 'default')",
        kb_id,
    )
    await pg_pool.execute(
        "INSERT INTO documents "
        "(doc_id, kb_id, filename, file_hash, file_size, content_type, content, status) "
        "VALUES ($1, $2, 'test.md', 'abc', 100, 'text/markdown', '# Test', 2)",
        doc_id,
        kb_id,
    )

    try:
        # 尝试删除 KB
        resp = client.delete(f"/v1/knowledge-bases/{kb_id}")
        body = resp.json()

        # 应被拒绝 — 存在 PROCESSING 文档
        assert resp.status_code == 409
        assert body["code"] == 10301  # RESOURCE_CONFLICT
        assert "索引" in body["message"] or "PROCESSING" in str(body)

        # 验证 KB 仍存在
        row = await pg_pool.fetchrow(
            "SELECT id FROM knowledge_bases WHERE id = $1", kb_id
        )
        assert row is not None

    finally:
        await pg_pool.execute(
            "UPDATE documents SET status = 1 WHERE doc_id = $1", doc_id
        )
        await pg_pool.execute("DELETE FROM documents WHERE doc_id = $1", doc_id)
        await pg_pool.execute("DELETE FROM knowledge_bases WHERE id = $1", kb_id)


@pytest.mark.asyncio
async def test_can_delete_success_document(client, pg_pool: asyncpg.Pool):
    """6.6c: 对比例子 — SUCCESS 文档 DELETE 成功（code=0, 文档删除）。"""
    kb_id = f"kb_{uuid.uuid4().hex[:8]}"
    doc_id = f"doc_{uuid.uuid4().hex[:16]}"

    await pg_pool.execute(
        "INSERT INTO knowledge_bases (id, name, description, tenant_id) "
        "VALUES ($1, 'E2E KB3', 'test', 'default')",
        kb_id,
    )
    await pg_pool.execute(
        "INSERT INTO documents "
        "(doc_id, kb_id, filename, file_hash, file_size, content_type, content, status) "
        "VALUES ($1, $2, 'ok.md', 'xyz', 50, 'text/markdown', '# OK', 1)",
        doc_id,
        kb_id,
    )

    try:
        resp = client.delete(f"/v1/documents/{doc_id}")
        body = resp.json()

        assert resp.status_code == 200
        assert body["code"] == 0
        assert body["message"] == "ok"

        # 文档应被删除
        row = await pg_pool.fetchrow(
            "SELECT 1 FROM documents WHERE doc_id = $1", doc_id
        )
        assert row is None

    finally:
        # 确保清理（可能已被删除）
        await pg_pool.execute("DELETE FROM documents WHERE doc_id = $1", doc_id)
        await pg_pool.execute("DELETE FROM knowledge_bases WHERE id = $1", kb_id)
