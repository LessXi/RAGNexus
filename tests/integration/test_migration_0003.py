"""Alembic 0003 迁移测试 — 验证 tenants/api_keys 表的 upgrade/downgrade 和幂等性。

测试步骤:
1. 清理测试数据库所有表（含 alembic_version）
2. alembic upgrade head → 验证 tenants/api_keys 表存在、版本号为 0003
3. alembic downgrade -1 → 验证 tenants/api_keys 已删除、其他表保留、版本回退 0002
4. 幂等性: upgrade → downgrade → upgrade → 验证最终状态
"""

import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DSN = "postgresql://ragnexus:ragnexus@localhost:15433/ragnexus_test"

# FK 逆序排列，确保 DROP TABLE CASCADE 顺序正确（新增 tenants, api_keys）
ALL_TABLES = [
    "api_keys",
    "tenants",
    "retrieve_logs",
    "chunks",
    "documents",
    "knowledge_bases",
    "alembic_version",
]

# upgrade head 后应存在的所有表
ALL_TABLES_HEAD = [
    "retrieve_logs",
    "chunks",
    "documents",
    "knowledge_bases",
    "tenants",
    "api_keys",
    "alembic_version",
]

# downgrade -1 后应删除的表（仅 0003 新增的）
TABLES_REMOVED = ["tenants", "api_keys"]

# downgrade -1 后应保留的表
TABLES_SURVIVING = [
    "retrieve_logs",
    "chunks",
    "documents",
    "knowledge_bases",
]

pytestmark = [pytest.mark.integration]


@pytest.fixture
def alembic_env(monkeypatch, ensure_test_db):
    """设置 PG_DSN 为测试库并清除 Settings 缓存。"""
    monkeypatch.setenv("PG_DSN", TEST_DSN)
    from ragnexus.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _drop_all_tables() -> None:
    """删除测试库所有表（CASCADE），为 alembic 提供干净起点。"""
    conn = await asyncpg.connect(TEST_DSN)
    try:
        for table in ALL_TABLES:
            await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        # 二次确认
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        )
        remaining = [r["table_name"] for r in rows if r["table_name"] in ALL_TABLES]
        if remaining:
            raise RuntimeError(f"清理失败：以下表未删除: {remaining}")
    finally:
        await conn.close()


async def _get_existing_tables() -> set[str]:
    """返回 public schema 中存在的表名集合。"""
    conn = await asyncpg.connect(TEST_DSN)
    try:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        return {r["table_name"] for r in rows}
    finally:
        await conn.close()


async def _get_alembic_version() -> str | None:
    """返回 alembic_version 表中的版本号，无记录时返回 None。"""
    conn = await asyncpg.connect(TEST_DSN)
    try:
        return await conn.fetchval("SELECT version_num FROM alembic_version")
    finally:
        await conn.close()


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    """在项目根目录运行 alembic 命令。"""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )


async def test_migration_0003_upgrade_downgrade(alembic_env):
    """验证 0003 迁移 upgrade/downgrade 及幂等性。"""

    # ── 0. 清理测试库 ──
    await _drop_all_tables()

    # ── 1. upgrade head → 应包含 0003 ──
    result = _run_alembic("upgrade", "head")
    assert (
        result.returncode == 0
    ), f"upgrade head 失败:\nSTDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout}"

    # ── 2. 验证所有表存在 ──
    existing = await _get_existing_tables()
    for table in ALL_TABLES_HEAD:
        assert table in existing, f"表 '{table}' 应该在 upgrade head 后存在"

    version = await _get_alembic_version()
    assert version == "0003", f"版本号应为 '0003'，实际为 '{version}'"

    # ── 3. downgrade -1 → 回退到 0002 ──
    result = _run_alembic("downgrade", "-1")
    assert (
        result.returncode == 0
    ), f"downgrade -1 失败:\nSTDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout}"

    # ── 4. 验证 tenants/api_keys 已删除 ──
    existing = await _get_existing_tables()
    for table in TABLES_REMOVED:
        assert table not in existing, f"表 '{table}' 应该在 downgrade 后不存在"

    # ── 5. 验证其他表保留 ──
    for table in TABLES_SURVIVING:
        assert table in existing, f"表 '{table}' 应该在 downgrade 后仍然存在"

    version = await _get_alembic_version()
    assert version == "0002", f"downgrade 后版本号应为 '0002'，实际为 '{version}'"

    # ── 6. 幂等性: upgrade → downgrade → upgrade ──
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, f"幂等 upgrade 失败:\nSTDERR:\n{result.stderr}"

    result = _run_alembic("downgrade", "-1")
    assert result.returncode == 0, f"幂等 downgrade 失败:\nSTDERR:\n{result.stderr}"

    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, f"幂等再 upgrade 失败:\nSTDERR:\n{result.stderr}"

    # 最终状态验证
    existing = await _get_existing_tables()
    for table in ALL_TABLES_HEAD:
        assert table in existing, f"幂等 upgrade 后表 '{table}' 应存在"

    version = await _get_alembic_version()
    assert version == "0003", f"幂等 upgrade 后版本号应为 '0003'，实际为 '{version}'"


# ─────────────────────────────────────────────────────────────────
# FK 约束验证：knowledge_bases.tenant_id → tenants.id
# ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def migrated_db(alembic_env, ensure_test_db):
    """确保迁移 0003 已完全应用，返回 asyncpg pool 用于 FK 测试。"""
    await _drop_all_tables()
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, f"FK 测试前 upgrade 失败:\n{result.stderr}"
    pool = await asyncpg.create_pool(
        TEST_DSN, min_size=1, max_size=3, command_timeout=15
    )
    yield pool
    await pool.close()


async def test_fk_exists(migrated_db):
    """验证 knowledge_bases.tenant_id → tenants.id FK 存在。"""
    async with migrated_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = 'fk_knowledge_bases_tenant' "
            "AND constraint_type = 'FOREIGN KEY'"
        )
    assert row is not None, "FK fk_knowledge_bases_tenant 应存在"


async def test_fk_restrict_delete(migrated_db):
    """验证 ON DELETE RESTRICT：有 knowledge_bases 引用时删租户被拒绝。"""
    async with migrated_db.acquire() as conn:
        # 创建测试租户
        await conn.execute(
            "INSERT INTO tenants (id, name) VALUES ('fk_test_t', 'FK测试') "
            "ON CONFLICT (id) DO NOTHING"
        )
        # 创建 KB 引用该租户
        await conn.execute(
            "INSERT INTO knowledge_bases (id, name, name_key, tenant_id) "
            "VALUES ('fk_test_kb', 'FK测试KB', 'fk_test_kb_key', 'fk_test_t') "
            "ON CONFLICT (id) DO NOTHING"
        )
        # 尝试删除租户 → 应被 RESTRICT 拒绝
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute("DELETE FROM tenants WHERE id = 'fk_test_t'")
        # 清理：先删 KB 再删租户
        await conn.execute("DELETE FROM knowledge_bases WHERE id = 'fk_test_kb'")
        await conn.execute("DELETE FROM tenants WHERE id = 'fk_test_t'")
