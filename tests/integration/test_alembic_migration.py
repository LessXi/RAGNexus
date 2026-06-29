"""Alembic 迁移验证测试 — 验证 upgrade/downgrade 和幂等性。

测试步骤:
1. 清理测试数据库所有表（含 alembic_version）
2. alembic upgrade head → 验证所有表存在、版本号正确
3. alembic downgrade -1 → 验证业务表已删除
4. 幂等性: upgrade → downgrade → upgrade → 验证最终状态

注意: alembic_version 表由 alembic 运行时管理，downgrade 后仍存在（仅版本行清空）。
"""

import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DSN = "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"

# FK 逆序排列，确保 DROP TABLE CASCADE 顺序正确
ALL_TABLES = [
    "retrieve_logs",
    "chunks",
    "documents",
    "knowledge_bases",
    "alembic_version",
]

# 业务表 — downgrade 后验证这些表已删除（alembic_version 由运行时保留）
BUSINESS_TABLES = [
    "retrieve_logs",
    "chunks",
    "documents",
    "knowledge_bases",
]

pytestmark = [pytest.mark.integration]


@pytest.fixture
def alembic_env(monkeypatch, ensure_test_db):
    """设置 PG_DSN 为测试库并清除 Settings 缓存。

    alembic/env.py 通过 get_settings() 读取 PG_DSN——
    子进程继承父进程 os.environ，无需额外配置。
    """
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
    """在项目根目录运行 alembic 命令，子进程继承当前 os.environ。"""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )


async def test_alembic_upgrade_downgrade(alembic_env):
    """验证 Alembic 迁移 upgrade/downgrade 及幂等性。

    完整流程:
    1. 清理 → upgrade head → 验证表
    2. downgrade -1 → 验证业务表删除
    3. 幂等性: upgrade → downgrade → upgrade → 最终验证
    """

    # ── 0. 清理测试库 ──
    await _drop_all_tables()

    # ── 1. upgrade head ──
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, (
        f"upgrade head 失败:\nSTDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout}"
    )

    # ── 2. 验证所有表存在 ──
    existing = await _get_existing_tables()
    for table in ALL_TABLES:
        assert table in existing, f"表 '{table}' 应该在 upgrade 后存在"

    version = await _get_alembic_version()
    assert version == "0001", f"版本号应为 '0001'，实际为 '{version}'"

    # ── 3. downgrade -1 ──
    result = _run_alembic("downgrade", "-1")
    assert result.returncode == 0, (
        f"downgrade -1 失败:\nSTDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout}"
    )

    # ── 4. 验证业务表已删除 ──
    existing = await _get_existing_tables()
    for table in BUSINESS_TABLES:
        assert table not in existing, f"表 '{table}' 应该在 downgrade 后不存在"

    # ── 5. 幂等性: upgrade → downgrade → upgrade ──
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, f"幂等 upgrade 失败:\nSTDERR:\n{result.stderr}"

    result = _run_alembic("downgrade", "-1")
    assert result.returncode == 0, f"幂等 downgrade 失败:\nSTDERR:\n{result.stderr}"

    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, f"幂等再 upgrade 失败:\nSTDERR:\n{result.stderr}"

    # 最终状态验证
    existing = await _get_existing_tables()
    for table in ALL_TABLES:
        assert table in existing, f"幂等 upgrade 后表 '{table}' 应存在"

    version = await _get_alembic_version()
    assert version == "0001", f"幂等 upgrade 后版本号应为 '0001'，实际为 '{version}'"
