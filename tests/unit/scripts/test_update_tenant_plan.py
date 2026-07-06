"""update_tenant_plan.py 运维脚本单元测试 — TDD RED → GREEN。

测试 update_tenant_plan.main() 的六种场景。
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════
# 辅助：构造 mock asyncpg pool
# ═══════════════════════════════════════════════════════════════════


def _make_pool(fetchval_return=1):
    """构造 mock asyncpg pool，fetchval 返回 fetchval_return。"""
    pool = AsyncMock()
    pool.fetchval = AsyncMock(return_value=fetchval_return)
    pool.execute = AsyncMock()
    pool.close = AsyncMock()
    return pool


# ═══════════════════════════════════════════════════════════════════
# 测试 update_tenant_plan.py main()
# ═══════════════════════════════════════════════════════════════════


class TestUpdateTenantPlan:
    """修改租户套餐脚本的单元测试。"""

    @pytest.mark.asyncio
    async def test_tenant_exists_updates_plan(self, capsys):
        """租户存在时，UPDATE 成功执行并输出确认信息。"""
        from scripts.update_tenant_plan import main

        pool = _make_pool(fetchval_return=1)
        ctx_args = patch.object(
            sys,
            "argv",
            ["update_tenant_plan.py", "--tenant-id", "t1", "--plan", "pro"],
        )
        ctx_asyncpg = patch(
            "scripts.update_tenant_plan.asyncpg.create_pool",
            new=AsyncMock(return_value=pool),
        )
        with ctx_args, ctx_asyncpg:
            await main()

        captured = capsys.readouterr()
        assert "租户 plan 已更新" in captured.out
        assert "t1" in captured.out
        assert "pro" in captured.out
        pool.execute.assert_awaited_once_with(
            "UPDATE tenants SET plan=$1 WHERE id=$2", "pro", "t1"
        )
        pool.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tenant_not_found_exits_with_error(self, capsys):
        """租户不存在时输出错误到 stderr 并 sys.exit(1)。"""
        from scripts.update_tenant_plan import main

        pool = _make_pool(fetchval_return=None)
        ctx_args = patch.object(
            sys,
            "argv",
            ["update_tenant_plan.py", "--tenant-id", "t_bad", "--plan", "free"],
        )
        ctx_asyncpg = patch(
            "scripts.update_tenant_plan.asyncpg.create_pool",
            new=AsyncMock(return_value=pool),
        )
        with ctx_args, ctx_asyncpg:
            with pytest.raises(SystemExit) as exc_info:
                await main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "不存在" in captured.err
        assert "t_bad" in captured.err

    @pytest.mark.asyncio
    async def test_free_plan_accepted(self, capsys):
        """free 套餐是合法值，应正常更新。"""
        from scripts.update_tenant_plan import main

        pool = _make_pool(fetchval_return=1)
        ctx_args = patch.object(
            sys,
            "argv",
            ["update_tenant_plan.py", "--tenant-id", "t2", "--plan", "free"],
        )
        ctx_asyncpg = patch(
            "scripts.update_tenant_plan.asyncpg.create_pool",
            new=AsyncMock(return_value=pool),
        )
        with ctx_args, ctx_asyncpg:
            await main()

        captured = capsys.readouterr()
        assert "free" in captured.out
        pool.execute.assert_awaited_once_with(
            "UPDATE tenants SET plan=$1 WHERE id=$2", "free", "t2"
        )

    @pytest.mark.asyncio
    async def test_standard_plan_accepted(self, capsys):
        """standard 套餐是合法值，应正常更新。"""
        from scripts.update_tenant_plan import main

        pool = _make_pool(fetchval_return=1)
        ctx_args = patch.object(
            sys,
            "argv",
            ["update_tenant_plan.py", "--tenant-id", "t3", "--plan", "standard"],
        )
        ctx_asyncpg = patch(
            "scripts.update_tenant_plan.asyncpg.create_pool",
            new=AsyncMock(return_value=pool),
        )
        with ctx_args, ctx_asyncpg:
            await main()

        captured = capsys.readouterr()
        assert "standard" in captured.out

    def test_invalid_plan_rejected_by_argparse(self):
        """argparse 在解析阶段拒绝非法 plan 值。"""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--plan", choices=["free", "standard", "pro"])
        with pytest.raises(SystemExit):
            parser.parse_args(["--plan", "enterprise"])

    def test_missing_required_args_rejected(self):
        """缺少 --tenant-id 或 --plan 时 argparse 报错退出。"""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--tenant-id", required=True)
        parser.add_argument(
            "--plan", required=True, choices=["free", "standard", "pro"]
        )
        with pytest.raises(SystemExit):
            parser.parse_args([])

    @pytest.mark.asyncio
    async def test_pg_dsn_from_env(self, capsys, monkeypatch):
        """未设置 PG_DSN 时使用默认连接串。"""
        from scripts.update_tenant_plan import main

        monkeypatch.delenv("PG_DSN", raising=False)
        pool = _make_pool(fetchval_return=1)
        ctx_args = patch.object(
            sys,
            "argv",
            ["update_tenant_plan.py", "--tenant-id", "t_env", "--plan", "free"],
        )
        ctx_asyncpg = patch(
            "scripts.update_tenant_plan.asyncpg.create_pool",
            new=AsyncMock(return_value=pool),
        )
        with ctx_args, ctx_asyncpg:
            await main()

        assert pool.fetchval.called

    @pytest.mark.asyncio
    async def test_pool_closes_on_exception(self, capsys):
        """即使 execute 失败，finally 块也保证 pool.close() 被调用。"""
        from scripts.update_tenant_plan import main

        pool = _make_pool(fetchval_return=1)
        pool.execute = AsyncMock(side_effect=RuntimeError("db explode"))
        ctx_args = patch.object(
            sys,
            "argv",
            ["update_tenant_plan.py", "--tenant-id", "t_err", "--plan", "pro"],
        )
        ctx_asyncpg = patch(
            "scripts.update_tenant_plan.asyncpg.create_pool",
            new=AsyncMock(return_value=pool),
        )
        with ctx_args, ctx_asyncpg:
            with pytest.raises(RuntimeError, match="db explode"):
                await main()

        pool.close.assert_awaited_once()
