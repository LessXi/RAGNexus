"""注册租户——创建 tenants 表记录。

用法：
    uv run python scripts/create_tenant.py --id my_tenant --name "我的租户"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg

# 将项目 src 目录加入 sys.path，以便导入 ragnexus 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ragnexus.config import get_settings  # noqa: E402
from ragnexus.core.errors import AppError, ErrorCode  # noqa: E402


async def _create_tenant(tenant_id: str, tenant_name: str) -> None:
    """在 tenants 表中插入一条租户记录。

    若 ID 已存在则抛出 AppError(ErrorCode.RESOURCE_CONFLICT)。
    """
    settings = get_settings()
    conn = await asyncpg.connect(settings.PG_DSN)
    try:
        existing = await conn.fetchval("SELECT 1 FROM tenants WHERE id = $1", tenant_id)
        if existing:
            raise AppError(
                ErrorCode.RESOURCE_CONFLICT,
                f"租户 '{tenant_id}' 已存在",
            )

        await conn.execute(
            "INSERT INTO tenants (id, name) VALUES ($1, $2)",
            tenant_id,
            tenant_name,
        )
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="注册租户")
    parser.add_argument("--id", required=True, help="租户唯一标识")
    parser.add_argument("--name", required=True, help="租户展示名称")
    args = parser.parse_args()

    try:
        asyncio.run(_create_tenant(args.id, args.name))
    except AppError as e:
        print(f"错误 [{e.code}]: {e.message}", file=sys.stderr)
        sys.exit(1)

    print(f"租户创建成功：id={args.id}, name={args.name}")


if __name__ == "__main__":
    main()
