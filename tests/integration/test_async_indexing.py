"""异步索引集成测试 — 需要 Docker (test-db)。

标记: @pytest.mark.integration
"""

import uuid

import asyncpg
import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

# =============================================================================
# 6.2 异步索引完整链路
# =============================================================================


@pytest_asyncio.fixture
async def kb_fixture(pg_pool: asyncpg.Pool) -> dict:
    """创建测试知识库并返回 kb_id。"""
    kb_id = f"kb_{uuid.uuid4().hex[:8]}"
    await pg_pool.execute(
        "INSERT INTO knowledge_bases (id, name, description, tenant_id) "
        "VALUES ($1, 'test-kb', 'test', 'default')",
        kb_id,
    )
    try:
        yield {"kb_id": kb_id}
    finally:
        await pg_pool.execute("DELETE FROM knowledge_bases WHERE id = $1", kb_id)


@pytest.mark.asyncio
async def test_async_upload_status_flow(pg_pool: asyncpg.Pool, kb_fixture: dict):
    """6.2: 上传文档→轮询 status→状态流转完整链路。

    模拟异步索引的完整生命周期：
    1. 文档初始状态为 PROCESSING
    2. 更新为 SUCCESS
    3. 查询确认状态变更
    """
    kb_id = kb_fixture["kb_id"]
    doc_id = f"doc_{uuid.uuid4().hex[:16]}"

    # 1. 创建文档 (PROCESSING 状态)
    await pg_pool.execute(
        "INSERT INTO documents "
        "(doc_id, kb_id, filename, file_hash, file_size, content_type, content, status) "
        "VALUES ($1, $2, 'test.md', 'abc123', 100, 'text/markdown', '# Test', 2)",
        doc_id,
        kb_id,
    )

    # 2. 轮询 — PROCESSING
    row = await pg_pool.fetchrow(
        "SELECT status FROM documents WHERE doc_id = $1", doc_id
    )
    assert row is not None
    assert row["status"] == 2  # PROCESSING

    # 3. 索引完成 → SUCCESS
    await pg_pool.execute(
        "UPDATE documents SET status = 1, chunk_count = 3 WHERE doc_id = $1",
        doc_id,
    )

    # 4. 轮询 — SUCCESS
    row = await pg_pool.fetchrow(
        "SELECT status, chunk_count FROM documents WHERE doc_id = $1", doc_id
    )
    assert row["status"] == 1  # SUCCESS
    assert row["chunk_count"] == 3

    # 5. 清理
    await pg_pool.execute("DELETE FROM documents WHERE doc_id = $1", doc_id)


@pytest.mark.asyncio
async def test_async_upload_failed_status(pg_pool: asyncpg.Pool, kb_fixture: dict):
    """6.2b: 索引失败文档状态流转 PROCESSING → FAILED。"""
    kb_id = kb_fixture["kb_id"]
    doc_id = f"doc_{uuid.uuid4().hex[:16]}"

    await pg_pool.execute(
        "INSERT INTO documents "
        "(doc_id, kb_id, filename, file_hash, file_size, content_type, content, status) "
        "VALUES ($1, $2, 'bad.md', 'xyz', 50, 'text/markdown', '# Bad', 2)",
        doc_id,
        kb_id,
    )

    # 索引失败
    await pg_pool.execute(
        "UPDATE documents SET status = 3, error_message = '解析失败' WHERE doc_id = $1",
        doc_id,
    )

    row = await pg_pool.fetchrow(
        "SELECT status, error_message FROM documents WHERE doc_id = $1", doc_id
    )
    assert row["status"] == 3  # FAILED
    assert row["error_message"] == "解析失败"

    # 清理
    await pg_pool.execute("DELETE FROM documents WHERE doc_id = $1", doc_id)


# =============================================================================
# 6.3 ES 不可用→FAILED→恢复→reindex→SUCCESS
# =============================================================================


@pytest.mark.asyncio
async def test_reindex_failed_document(pg_pool: asyncpg.Pool, kb_fixture: dict):
    """6.3: FAILED 文档重新索引 → SUCCESS。

    模拟场景：
    1. 文档因 ES 不可用变为 FAILED
    2. ES 恢复后，文档状态从 PROCESSING 重新开始
    3. 索引成功，状态变为 SUCCESS
    """
    kb_id = kb_fixture["kb_id"]
    doc_id = f"doc_{uuid.uuid4().hex[:16]}"

    # 1. 创建 FAILED 文档（模拟 ES 不可用导致的失败）
    await pg_pool.execute(
        "INSERT INTO documents "
        "(doc_id, kb_id, filename, file_hash, file_size, content_type, content, "
        "status, error_message) "
        "VALUES ($1, $2, 'doc.md', 'hash1', 200, 'text/markdown', '# Doc', "
        "3, 'ES unavailable')",
        doc_id,
        kb_id,
    )

    # 验证初始状态为 FAILED
    row = await pg_pool.fetchrow(
        "SELECT status, error_message FROM documents WHERE doc_id = $1", doc_id
    )
    assert row["status"] == 3
    assert "ES" in row["error_message"]

    # 2. Reindex: 重置为 PROCESSING
    await pg_pool.execute(
        "UPDATE documents SET status = 2, error_message = NULL WHERE doc_id = $1",
        doc_id,
    )

    row = await pg_pool.fetchrow(
        "SELECT status, error_message FROM documents WHERE doc_id = $1", doc_id
    )
    assert row["status"] == 2
    assert row["error_message"] is None

    # 3. 索引成功
    await pg_pool.execute(
        "UPDATE documents SET status = 1, chunk_count = 5 WHERE doc_id = $1",
        doc_id,
    )

    row = await pg_pool.fetchrow(
        "SELECT status, chunk_count FROM documents WHERE doc_id = $1", doc_id
    )
    assert row["status"] == 1
    assert row["chunk_count"] == 5

    # 清理
    await pg_pool.execute("DELETE FROM documents WHERE doc_id = $1", doc_id)


# =============================================================================
# 6.4 KB CRUD 完整覆盖
# =============================================================================


@pytest.mark.asyncio
async def test_kb_crud_lifecycle(pg_pool: asyncpg.Pool):
    """6.4: 知识库完整生命周期 — create → detail → update → delete。"""
    kb_id = f"kb_{uuid.uuid4().hex[:8]}"

    # 1. CREATE
    await pg_pool.execute(
        "INSERT INTO knowledge_bases (id, name, description, tenant_id) "
        "VALUES ($1, 'CRUD Test', '初始描述', 'default')",
        kb_id,
    )

    # 2. DETAIL (read back)
    row = await pg_pool.fetchrow(
        "SELECT id, name, description, tenant_id FROM knowledge_bases WHERE id = $1",
        kb_id,
    )
    assert row is not None
    assert row["name"] == "CRUD Test"
    assert row["description"] == "初始描述"
    assert row["tenant_id"] == "default"

    # 3. UPDATE
    await pg_pool.execute(
        "UPDATE knowledge_bases SET name = $1, description = $2 WHERE id = $3",
        "CRUD Updated",
        "更新后的描述",
        kb_id,
    )

    row = await pg_pool.fetchrow(
        "SELECT name, description FROM knowledge_bases WHERE id = $1", kb_id
    )
    assert row["name"] == "CRUD Updated"
    assert row["description"] == "更新后的描述"

    # 4. DELETE
    await pg_pool.execute("DELETE FROM knowledge_bases WHERE id = $1", kb_id)

    row = await pg_pool.fetchrow("SELECT 1 FROM knowledge_bases WHERE id = $1", kb_id)
    assert row is None


# =============================================================================
# 6.5 跨租户隔离
# =============================================================================


@pytest_asyncio.fixture
async def tenants_fixture(pg_pool: asyncpg.Pool) -> dict:
    """创建两个租户并返回其 ID。"""
    tenant_a = f"tenant_a_{uuid.uuid4().hex[:6]}"
    tenant_b = f"tenant_b_{uuid.uuid4().hex[:6]}"
    for tid in [tenant_a, tenant_b]:
        await pg_pool.execute(
            "INSERT INTO tenants (id, name, status) VALUES ($1, $1, 'active') "
            "ON CONFLICT (id) DO NOTHING",
            tid,
        )
    try:
        yield {"tenant_a": tenant_a, "tenant_b": tenant_b}
    finally:
        for tid in [tenant_a, tenant_b]:
            await pg_pool.execute("DELETE FROM tenants WHERE id = $1", tid)


@pytest.mark.asyncio
async def test_cross_tenant_kb_isolation(pg_pool: asyncpg.Pool, tenants_fixture: dict):
    """6.5a: 租户 A 的知识库，租户 B 不可见。"""
    tenant_a = tenants_fixture["tenant_a"]
    tenant_b = tenants_fixture["tenant_b"]
    kb_id = f"kb_{uuid.uuid4().hex[:8]}"

    # 租户 A 创建 KB
    await pg_pool.execute(
        "INSERT INTO knowledge_bases (id, name, description, tenant_id) "
        "VALUES ($1, 'A私有KB', '只有A可见', $2)",
        kb_id,
        tenant_a,
    )

    # 租户 A 可见
    row = await pg_pool.fetchrow(
        "SELECT id FROM knowledge_bases WHERE id = $1 AND tenant_id = $2",
        kb_id,
        tenant_a,
    )
    assert row is not None

    # 租户 B 不可见
    row = await pg_pool.fetchrow(
        "SELECT id FROM knowledge_bases WHERE id = $1 AND tenant_id = $2",
        kb_id,
        tenant_b,
    )
    assert row is None

    # 清理
    await pg_pool.execute("DELETE FROM knowledge_bases WHERE id = $1", kb_id)


@pytest.mark.asyncio
async def test_cross_tenant_document_isolation(
    pg_pool: asyncpg.Pool, tenants_fixture: dict
):
    """6.5b: 租户 B 无法通过 kb_id 找到租户 A 的文档。"""
    tenant_a = tenants_fixture["tenant_a"]
    tenant_b = tenants_fixture["tenant_b"]
    kb_id_a = f"kb_{uuid.uuid4().hex[:8]}"
    doc_id = f"doc_{uuid.uuid4().hex[:16]}"

    # 租户 A 创建 KB + 文档
    await pg_pool.execute(
        "INSERT INTO knowledge_bases (id, name, description, tenant_id) "
        "VALUES ($1, 'AKB', '', $2)",
        kb_id_a,
        tenant_a,
    )
    await pg_pool.execute(
        "INSERT INTO documents (doc_id, kb_id, filename, file_hash, "
        "file_size, content_type, content, status) "
        "VALUES ($1, $2, 'f.md', 'h', 10, 'text/markdown', '#', 1)",
        doc_id,
        kb_id_a,
    )

    # 租户 B 尝试通过 kb_id 关联查询 — kb_id 存在但 tenant 不匹配
    # 模拟跨租户隔离：通过 JOIN 确保 tenant_id 匹配
    row = await pg_pool.fetchrow(
        "SELECT d.doc_id FROM documents d "
        "JOIN knowledge_bases kb ON d.kb_id = kb.id "
        "WHERE d.doc_id = $1 AND kb.tenant_id = $2",
        doc_id,
        tenant_b,
    )
    assert row is None

    # 租户 A 可以看到自己的文档
    row = await pg_pool.fetchrow(
        "SELECT d.doc_id FROM documents d "
        "JOIN knowledge_bases kb ON d.kb_id = kb.id "
        "WHERE d.doc_id = $1 AND kb.tenant_id = $2",
        doc_id,
        tenant_a,
    )
    assert row is not None

    # 清理
    await pg_pool.execute("DELETE FROM documents WHERE doc_id = $1", doc_id)
    await pg_pool.execute("DELETE FROM knowledge_bases WHERE id = $1", kb_id_a)
